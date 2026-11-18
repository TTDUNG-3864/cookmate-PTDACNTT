const { spawn } = require('child_process');
const http = require('http');

async function test320() {
  const PORT = 9295;
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new', '--remote-debugging-port=' + PORT, '--disable-gpu', '--no-sandbox', '--user-data-dir=C:\\temp\\c320_' + Date.now()
  ], { stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1200));
  const newTab = await new Promise((res, rej) => {
    const req = http.request({ host: '127.0.0.1', port: PORT, path: '/json/new?http://127.0.0.1:8089/index.html', method: 'PUT' }, r => {
      let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
    });
    req.on('error', rej); req.end();
  });
  const ws = new WebSocket(newTab.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 1;
  const send = (m, p = {}) => new Promise((resolve) => {
    const curId = id++;
    const handler = (e) => {
      const data = JSON.parse(e.data);
      if (data.id === curId) { ws.removeEventListener('message', handler); resolve(data.result); }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id: curId, method: m, params: p }));
  });
  await send('Emulation.setDeviceMetricsOverride', { width: 320, height: 568, deviceScaleFactor: 2, mobile: true });
  await send('Runtime.evaluate', {
    expression: 'localStorage.setItem("cookmate_current_user", JSON.stringify({ id: 1, username: "user", name: "Nguyễn Văn A", role: "member" }));'
  });
  await send('Page.navigate', { url: 'http://127.0.0.1:8089/index.html' });
  await new Promise(r => setTimeout(r, 600));
  const res = await send('Runtime.evaluate', {
    expression: '(() => { const mt = document.getElementById("menuToggle"); const logo = document.querySelector(".logo"); const fav = document.querySelector(".header-fav-btn"); const auth = document.getElementById("authArea"); const userAvatar = document.querySelector(".user-avatar"); return { mt: mt ? mt.getBoundingClientRect().toJSON() : null, logo: logo ? logo.getBoundingClientRect().toJSON() : null, fav: fav ? fav.getBoundingClientRect().toJSON() : null, userAvatar: userAvatar ? userAvatar.getBoundingClientRect().toJSON() : null, scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth }; })()',
    returnByValue: true
  });
  console.log('320px metrics:', JSON.stringify(res.result.value, null, 2));
  ws.close();
  chrome.kill();
}
test320();
