const http = require('http');
const { spawn } = require('child_process');

async function testIcons() {
  const PORT = 9272;
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    '--user-data-dir=C:\\temp\\chrome_icon_test_' + Date.now()
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

  let id = 1;
  const send = (m, p = {}) => new Promise((resolve, reject) => {
    const curId = id++;
    const handler = (event) => {
      const data = JSON.parse(event.data);
      if (data.id === curId) {
        ws.removeEventListener('message', handler);
        if (data.error) reject(data.error);
        else resolve(data.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id: curId, method: m, params: p }));
  });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('DOM.enable');

  const testClasses = [
    'fa-solid fa-house',
    'fa-solid fa-book-open',
    'fa-solid fa-layer-group',
    'fa-solid fa-sparkles',
    'fa-solid fa-wand-magic-sparkles',
    'fa-solid fa-clock',
    'fa-solid fa-bolt',
    'fa-solid fa-fire',
    'fa-solid fa-fire-flame-curved',
    'fa-solid fa-star',
    'fa-solid fa-calendar-days',
    'fa-solid fa-magnifying-glass',
    'fa-solid fa-circle-plus',
    'fa-solid fa-heart',
    'fa-solid fa-book-bookmark',
    'fa-solid fa-book',
    'fa-solid fa-bookmark'
  ];

  const results = await send('Runtime.evaluate', {
    expression: `
      (async function() {
        await document.fonts.ready;
        const div = document.createElement('div');
        document.body.appendChild(div);
        const list = ${JSON.stringify(testClasses)};
        return list.map(cls => {
          const i = document.createElement('i');
          i.className = cls;
          div.appendChild(i);
          const before = window.getComputedStyle(i, '::before');
          const res = {
            cls,
            content: before.content,
            fontFamily: before.fontFamily
          };
          return res;
        });
      })()
    `,
    awaitPromise: true,
    returnByValue: true
  });

  console.log(JSON.stringify(results.result.value, null, 2));
  chrome.kill();
}
testIcons();
