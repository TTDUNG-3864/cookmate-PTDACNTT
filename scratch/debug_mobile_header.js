const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const DEBUG_PORT = 9266;
const SCREENSHOT_DIR = path.join(__dirname, 'screenshots_mobile_header');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function debugHeader() {
  const userDataDir = 'C:\\temp\\chrome_mob_' + Date.now();
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    `--user-data-dir=${userDataDir}`
  ], { stdio: 'ignore' });

  await sleep(1500);

  async function createPage(url, viewport = { width: 360, height: 800 }) {
    const target = await new Promise((resolve, reject) => {
      const req = http.request({
        host: '127.0.0.1',
        port: DEBUG_PORT,
        path: `/json/new?${encodeURIComponent(url)}`,
        method: 'PUT'
      }, res => {
        let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(JSON.parse(d)));
      });
      req.on('error', reject);
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

    await send('Emulation.setDeviceMetricsOverride', {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: true
    });

    const evalJs = async (exp) => {
      const r = await send('Runtime.evaluate', { expression: exp, returnByValue: true });
      if (r.exceptionDetails) {
        throw new Error(r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception ? r.exceptionDetails.exception.description : ''));
      }
      return r.result ? r.result.value : undefined;
    };

    const screenshot = async (filename) => {
      const data = await send('Page.captureScreenshot', { format: 'png' });
      const filePath = path.join(SCREENSHOT_DIR, filename);
      fs.writeFileSync(filePath, Buffer.from(data.data, 'base64'));
      return filePath;
    };

    return { send, evalJs, screenshot, close: () => send('Target.closeTarget', { targetId: target.id }) };
  }

  try {
    const testViewports = [
      { name: '320px', width: 320, height: 600 },
      { name: '360px', width: 360, height: 800 },
      { name: '375px', width: 375, height: 667 },
      { name: '390px', width: 390, height: 844 },
      { name: '414px', width: 414, height: 896 },
      { name: '430px', width: 430, height: 932 }
    ];

    for (const vp of testViewports) {
      console.log(`\n--- Testing ${vp.name} (${vp.width}x${vp.height}) ---`);
      const page = await createPage('http://127.0.0.1:8089/index.html', vp);
      await sleep(500);
      
      // Setup admin session
      await page.evalJs(`
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
      `);

      await page.evalJs(`window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';`);
      await sleep(1500);

      const headerInfo = await page.evalJs(`
        (function() {
          const header = document.querySelector('.admin-header');
          if (!header) return { error: 'No .admin-header' };

          const rect = header.getBoundingClientRect();
          const computed = window.getComputedStyle(header);
          
          const toggle = header.querySelector('.admin-sidebar-toggle-btn') || document.querySelector('.admin-sidebar-toggle-btn');
          const title = header.querySelector('.admin-header__title');
          const actions = header.querySelector('.admin-header__actions');
          const postBtn = actions ? actions.querySelector('a') : null;
          const logoutBtn = actions ? actions.querySelector('button') : null;

          return {
            headerRect: { width: rect.width, height: rect.height, top: rect.top },
            computedHeader: {
              display: computed.display,
              flexWrap: computed.flexWrap,
              padding: computed.padding,
              gap: computed.gap
            },
            toggle: toggle ? {
              rect: toggle.getBoundingClientRect(),
              classes: toggle.className,
              parent: toggle.parentElement.className
            } : null,
            title: title ? {
              rect: title.getBoundingClientRect(),
              text: title.innerText,
              computed: {
                fontSize: window.getComputedStyle(title).fontSize,
                whiteSpace: window.getComputedStyle(title).whiteSpace,
                overflowWrap: window.getComputedStyle(title).overflowWrap,
                wordBreak: window.getComputedStyle(title).wordBreak,
                minWidth: window.getComputedStyle(title).minWidth,
                flex: window.getComputedStyle(title).flex,
                width: window.getComputedStyle(title).width
              }
            } : null,
            actions: actions ? {
              rect: actions.getBoundingClientRect(),
              computed: {
                display: window.getComputedStyle(actions).display,
                flexWrap: window.getComputedStyle(actions).flexWrap,
                gap: window.getComputedStyle(actions).gap,
                marginLeft: window.getComputedStyle(actions).marginLeft
              }
            } : null,
            postBtn: postBtn ? {
              rect: postBtn.getBoundingClientRect(),
              text: postBtn.innerText.trim(),
              computed: {
                whiteSpace: window.getComputedStyle(postBtn).whiteSpace,
                fontSize: window.getComputedStyle(postBtn).fontSize,
                padding: window.getComputedStyle(postBtn).padding
              }
            } : null,
            logoutBtn: logoutBtn ? {
              rect: logoutBtn.getBoundingClientRect()
            } : null,
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth
          };
        })()
      `);

      console.log('Header info:', JSON.stringify(headerInfo, null, 2));

      await page.screenshot(`after_${vp.name}.png`);
      await page.close();
    }

  } catch (err) {
    console.error('Debug error:', err);
  } finally {
    chrome.kill();
  }
}

debugHeader();
