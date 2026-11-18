const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');

async function testHeaderViews() {
  const PORT = 9271;
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    '--user-data-dir=C:\\temp\\chrome_header_views_' + Date.now()
  ], { stdio: 'ignore' });

  await new Promise(r => setTimeout(r, 1500));

  const target = await new Promise((res, rej) => {
    const req = http.request({ host: '127.0.0.1', port: PORT, path: '/json/new?http://127.0.0.1:8089/index.html', method: 'PUT' }, r => {
      let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
    });
    req.on('error', rej);
    req.end();
  });

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);

  let msgId = 1;
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = msgId++;
    const handler = (event) => {
      const data = JSON.parse(event.data);
      if (data.id === id) {
        ws.removeEventListener('message', handler);
        if (data.error) reject(data.error);
        else resolve(data.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id, method, params }));
  });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('DOM.enable');

  const vps = [320, 360, 375, 390, 414, 430];

  for (const w of vps) {
    await send('Emulation.setDeviceMetricsOverride', {
      width: w,
      height: 800,
      deviceScaleFactor: 1,
      mobile: true
    });

    // 1. GUEST STATE on index.html
    await send('Runtime.evaluate', {
      expression: `
        localStorage.clear();
        window.location.reload();
      `
    });
    await new Promise(r => setTimeout(r, 800));

    let ss = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(`d:\\cookmate\\scratch\\header_guest_${w}.png`, Buffer.from(ss.data, 'base64'));

    // 2. ADMIN LOGGED IN STATE on index.html
    await send('Runtime.evaluate', {
      expression: `
        localStorage.setItem('cookmate_current_user', JSON.stringify({
          id: 'admin_1',
          name: 'Quản trị viên',
          email: 'admin@cookmate.vn',
          role: 'admin'
        }));
        localStorage.setItem('cookmate_admin_session', JSON.stringify({
          adminId: 'admin_1',
          token: 'token_admin_test',
          role: 'admin'
        }));
        window.location.reload();
      `
    });
    await new Promise(r => setTimeout(r, 800));

    ss = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(`d:\\cookmate\\scratch\\header_admin_${w}.png`, Buffer.from(ss.data, 'base64'));

    // 3. ADMIN IN ADMIN DASHBOARD (pages/admin/index.html)
    await send('Runtime.evaluate', {
      expression: `
        window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';
      `
    });
    await new Promise(r => setTimeout(r, 1000));

    ss = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(`d:\\cookmate\\scratch\\admin_dashboard_${w}.png`, Buffer.from(ss.data, 'base64'));

    // 4. ADMIN VIEWING WEBSITE PREVIEW
    await send('Runtime.evaluate', {
      expression: `
        const btn = document.getElementById('btnViewWebsite');
        if (btn) btn.click();
      `
    });
    await new Promise(r => setTimeout(r, 1000));

    ss = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(`d:\\cookmate\\scratch\\admin_viewing_website_${w}.png`, Buffer.from(ss.data, 'base64'));
  }

  console.log('All screenshots captured!');
  chrome.kill();
}

testHeaderViews();
