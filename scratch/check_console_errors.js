const http = require('http');
const { spawn } = require('child_process');

async function checkConsole() {
  const DEBUG_PORT = 9268;
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    '--user-data-dir=C:\\temp\\chrome_err_' + Date.now()
  ], { stdio: 'ignore' });

  await new Promise(r => setTimeout(r, 1500));

  const target = await new Promise((res, rej) => {
    const req = http.request({ host: '127.0.0.1', port: DEBUG_PORT, path: '/json/new?http://127.0.0.1:8089/index.html', method: 'PUT' }, r => {
      let d = ''; r.on('data', c => d += c); r.on('end', () => res(JSON.parse(d)));
    });
    req.on('error', rej);
    req.end();
  });

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);

  const errors = [];
  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.method === 'Runtime.exceptionThrown') {
      errors.push(data.params.exceptionDetails);
    }
  };

  let id = 1;
  const send = (m, p = {}) => ws.send(JSON.stringify({ id: id++, method: m, params: p }));
  send('Runtime.enable');
  send('Page.enable');

  await new Promise(r => setTimeout(r, 500));
  send('Runtime.evaluate', {
    expression: `
      localStorage.setItem('cookmate_current_user', JSON.stringify({ id: 'admin_1', name: 'Quản trị viên', role: 'admin' }));
      localStorage.setItem('cookmate_admin_session', JSON.stringify({ adminId: 'admin_1', role: 'admin' }));
      window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';
    `
  });

  await new Promise(r => setTimeout(r, 2000));

  console.log('Console exceptions recorded:', errors.length);
  if (errors.length > 0) {
    errors.forEach(e => console.log('Error:', e.text, e.exception ? e.exception.description : ''));
  }

  chrome.kill();
}
checkConsole();
