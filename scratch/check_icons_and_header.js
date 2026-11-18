const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function check() {
  const PORT = 9270;
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    '--user-data-dir=C:\\temp\\chrome_check_' + Date.now()
  ], { stdio: 'ignore' });

  await sleep(1500);

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

  await send('Emulation.setDeviceMetricsOverride', {
    width: 375,
    height: 812,
    deviceScaleFactor: 1,
    mobile: true
  });

  await sleep(1000);

  // 1. Inspect Header elements
  const headerInfo = await send('Runtime.evaluate', {
    expression: `
      (function() {
        const header = document.querySelector('.site-header') || document.querySelector('header');
        const logo = document.querySelector('.logo') || document.querySelector('.site-header__logo');
        const menuToggle = document.querySelector('.menu-toggle');
        const favBtn = document.querySelector('.header-fav-btn');
        const authArea = document.querySelector('.auth-area');
        const floatingBtn = document.querySelector('.admin-sidebar-toggle-btn--floating');

        return {
          header: header ? header.getBoundingClientRect() : null,
          logo: logo ? { rect: logo.getBoundingClientRect(), classes: logo.className } : null,
          menuToggle: menuToggle ? { rect: menuToggle.getBoundingClientRect(), computed: {
            position: window.getComputedStyle(menuToggle).position,
            order: window.getComputedStyle(menuToggle).order,
            display: window.getComputedStyle(menuToggle).display
          } } : null,
          favBtn: favBtn ? favBtn.getBoundingClientRect() : null,
          authArea: authArea ? authArea.getBoundingClientRect() : null,
          floatingBtn: floatingBtn ? floatingBtn.getBoundingClientRect() : null,
          allButtonsInHeader: [...header.querySelectorAll('button, a')].map(el => ({
            tag: el.tagName,
            class: el.className,
            text: el.innerText.trim(),
            rect: el.getBoundingClientRect()
          }))
        };
      })()
    `,
    returnByValue: true
  });
  console.log('--- HEADER INFO (375px) ---');
  console.log(JSON.stringify(headerInfo.result.value, null, 2));

  // Open mobile drawer
  await send('Runtime.evaluate', {
    expression: `document.getElementById('menuToggle').click();`
  });
  await sleep(500);

  // 2. Inspect Mobile Nav Menu items & icons
  const drawerInfo = await send('Runtime.evaluate', {
    expression: `
      (function() {
        const links = [...document.querySelectorAll('.mobile-nav__link')];
        return links.map(link => {
          const icon = link.querySelector('i');
          const span = link.querySelector('span');
          let iconInfo = null;
          if (icon) {
            const beforeStyle = window.getComputedStyle(icon, '::before');
            const iconRect = icon.getBoundingClientRect();
            iconInfo = {
              className: icon.className,
              beforeContent: beforeStyle.content,
              fontFamily: beforeStyle.fontFamily,
              width: iconRect.width,
              height: iconRect.height,
              display: window.getComputedStyle(icon).display
            };
          }
          return {
            text: span ? span.innerText.trim() : link.innerText.trim(),
            href: link.getAttribute('href'),
            hasIcon: !!icon,
            iconInfo
          };
        });
      })()
    `,
    returnByValue: true
  });
  console.log('\n--- DRAWER MENU LINKS & ICONS ---');
  console.log(JSON.stringify(drawerInfo.result.value, null, 2));

  // Capture screenshot of drawer
  const ss = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync('d:\\cookmate\\scratch\\debug_drawer_icons_375.png', Buffer.from(ss.data, 'base64'));
  console.log('\nScreenshot saved to scratch/debug_drawer_icons_375.png');

  chrome.kill();
}

check();
