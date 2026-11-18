// scratch/run_full_validation.js
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = 9288;
const BASE_URL = 'http://127.0.0.1:8089';
const SCREENSHOT_DIR = path.resolve('C:/Users/TTD/.gemini/antigravity/brain/76e43c54-2a95-4105-8066-69e53cbabdc0');

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function sendHttpRequest(options, postData = null) {
  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve(data);
        }
      });
    });
    req.on('error', reject);
    if (postData) req.write(postData);
    req.end();
  });
}

async function main() {
  console.log('--- STARTING COOKMATE MOBILE UI VALIDATION SUITE ---');

  const userDataDir = 'C:\\temp\\chrome_val_' + Date.now();
  if (!fs.existsSync('C:\\temp')) {
    fs.mkdirSync('C:\\temp', { recursive: true });
  }

  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    `--user-data-dir=${userDataDir}`
  ], { stdio: 'ignore' });

  // Wait for Chrome to listen
  let retries = 20;
  let version = null;
  while (retries > 0) {
    try {
      version = await sendHttpRequest({ host: '127.0.0.1', port: PORT, path: '/json/version', method: 'GET' });
      if (version) break;
    } catch (e) {
      await sleep(200);
      retries--;
    }
  }

  if (!version) {
    console.error('Failed to start Chrome remote debugging');
    chrome.kill();
    process.exit(1);
  }

  console.log('Chrome Debugger attached on port', PORT);

  // Create target
  const newTab = await sendHttpRequest({
    host: '127.0.0.1',
    port: PORT,
    path: '/json/new?' + encodeURIComponent(BASE_URL + '/index.html'),
    method: 'PUT'
  });

  const ws = new WebSocket(newTab.webSocketDebuggerUrl);
  let msgId = 1;
  const callbacks = new Map();

  ws.onmessage = (event) => {
    const parsed = JSON.parse(event.data);
    if (parsed.id && callbacks.has(parsed.id)) {
      const { resolve, reject } = callbacks.get(parsed.id);
      callbacks.delete(parsed.id);
      if (parsed.error) reject(parsed.error);
      else resolve(parsed.result);
    }
  };

  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });

  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = msgId++;
      callbacks.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evalExpr(expression) {
    const res = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true
    });
    if (res.exceptionDetails) {
      throw new Error(JSON.stringify(res.exceptionDetails));
    }
    return res.result.value;
  }

  async function setViewport(w, h) {
    await send('Emulation.setDeviceMetricsOverride', {
      width: w,
      height: h,
      deviceScaleFactor: 2,
      mobile: w < 1024
    });
  }

  async function captureScreenshot(filename) {
    const res = await send('Page.captureScreenshot', { format: 'png' });
    const fullPath = path.join(SCREENSHOT_DIR, filename);
    fs.writeFileSync(fullPath, Buffer.from(res.data, 'base64'));
    console.log(`  [Screenshot saved] ${filename}`);
    return fullPath;
  }

  await send('Page.enable');
  await send('DOM.enable');
  await send('CSS.enable');

  const testViewports = [
    { name: 'iPhone SE (Ultra-Compact)', width: 320, height: 568 },
    { name: 'Galaxy S8 (Compact)', width: 360, height: 740 },
    { name: 'iPhone X / 12 Mini', width: 375, height: 812 },
    { name: 'iPhone 14 Pro', width: 390, height: 844 },
    { name: 'iPhone XR / 11', width: 414, height: 896 },
    { name: 'iPhone 15 Pro Max', width: 430, height: 932 },
    { name: 'iPad Portrait', width: 768, height: 1024 },
    { name: 'Desktop Standard', width: 1200, height: 800 }
  ];

  try {
    // -------------------------------------------------------------
    // PART 1: HEADER OVERLAP & HORIZONTAL OVERFLOW ON ALL VIEWPORTS
    // -------------------------------------------------------------
    console.log('\n======================================================');
    console.log('PART 1: HEADER OVERLAP & HORIZONTAL SCROLL TESTS');
    console.log('======================================================');

    // Setup Admin user
    await evalExpr(`
      localStorage.setItem('cookmate_current_user', JSON.stringify({
        id: 99,
        username: 'admin',
        name: 'Nguyễn Quản Trị',
        email: 'admin@cookmate.vn',
        role: 'admin'
      }));
    `);

    let allOverlapPassed = true;

    for (const vp of testViewports) {
      await setViewport(vp.width, vp.height);
      await send('Page.navigate', { url: BASE_URL + '/index.html' });
      await sleep(400);

      const m = await evalExpr(`
        (function() {
          var menuToggle = document.getElementById('menuToggle');
          var logo = document.querySelector('.logo') || document.querySelector('.site-header__logo');
          var favBtn = document.querySelector('.header-fav-btn');
          var authArea = document.getElementById('authArea');
          var floatingBtn = document.querySelector('.admin-sidebar-toggle-btn--floating');

          var docWidth = document.documentElement.clientWidth;
          var scrollWidth = document.documentElement.scrollWidth;

          var mtRect = menuToggle ? menuToggle.getBoundingClientRect() : null;
          var logoRect = logo ? logo.getBoundingClientRect() : null;
          var favRect = favBtn ? favBtn.getBoundingClientRect() : null;
          var authRect = authArea ? authArea.getBoundingClientRect() : null;

          var mtStyle = menuToggle ? window.getComputedStyle(menuToggle) : null;
          var isToggleVisible = mtStyle && mtStyle.display !== 'none' && mtRect.width > 0;

          var overlapsWithLogo = false;
          var gap = 0;
          if (isToggleVisible && logoRect) {
            if (mtRect.right > logoRect.left && mtRect.left < logoRect.right) {
              overlapsWithLogo = true;
            } else {
              gap = logoRect.left - mtRect.right;
            }
          }

          var floatingVisible = false;
          if (floatingBtn) {
            var fs = window.getComputedStyle(floatingBtn);
            floatingVisible = fs.display !== 'none';
          }

          return {
            clientWidth: docWidth,
            scrollWidth: scrollWidth,
            hasHorizontalOverflow: scrollWidth > docWidth + 1,
            isToggleVisible: isToggleVisible,
            menuToggleRect: mtRect ? { left: mtRect.left, right: mtRect.right, width: mtRect.width, height: mtRect.height } : null,
            logoRect: logoRect ? { left: logoRect.left, right: logoRect.right, width: logoRect.width, height: logoRect.height } : null,
            gap: gap,
            overlapsWithLogo: overlapsWithLogo,
            floatingVisible: floatingVisible
          };
        })()
      `);

      const passed = !m.overlapsWithLogo && !m.hasHorizontalOverflow && (!m.floatingVisible || vp.width >= 1024);
      if (!passed) allOverlapPassed = false;

      console.log(`[${vp.name} - ${vp.width}px]`);
      console.log(`  - Toggle visible: ${m.isToggleVisible}`);
      if (m.menuToggleRect && m.logoRect) {
        console.log(`  - MenuToggle: [${m.menuToggleRect.left.toFixed(1)} -> ${m.menuToggleRect.right.toFixed(1)}]px (width=${m.menuToggleRect.width}px)`);
        console.log(`  - Logo: [${m.logoRect.left.toFixed(1)} -> ${m.logoRect.right.toFixed(1)}]px (width=${m.logoRect.width}px)`);
        console.log(`  - Gap: ${m.gap.toFixed(1)}px | Overlap: ${m.overlapsWithLogo ? 'YES (BUG)' : 'NO (PASSED)'}`);
      }
      console.log(`  - Scroll width: ${m.scrollWidth}px vs client width: ${m.clientWidth}px (Overflow: ${m.hasHorizontalOverflow})`);
      console.log(`  - Floating toggle visible: ${m.floatingVisible}`);
      console.log(`  -> RESULT: ${passed ? 'PASSED ✓' : 'FAILED ✗'}\n`);

      if ([320, 360, 375, 430, 1200].includes(vp.width)) {
        await captureScreenshot(`fix_verified_${vp.width}px.png`);
      }
    }

    // -------------------------------------------------------------
    // PART 2: DRAWER ICONS & PSEUDO-ELEMENT GLYPH VERIFICATION
    // -------------------------------------------------------------
    console.log('\n======================================================');
    console.log('PART 2: DRAWER OPEN & ICON GLYPH VERIFICATION');
    console.log('======================================================');

    await setViewport(375, 812);
    await send('Page.navigate', { url: BASE_URL + '/index.html' });
    await sleep(400);

    // Click menu toggle
    await evalExpr(`document.getElementById('menuToggle').click();`);
    await sleep(400);

    const drawerData = await evalExpr(`
      (function() {
        var nav = document.getElementById('mobileNav');
        var overlay = document.getElementById('mobileNavOverlay');
        var isOpen = nav && nav.classList.contains('is-open');

        var links = Array.from(nav.querySelectorAll('.mobile-nav__link'));
        var linkResults = links.map(function(link) {
          var icon = link.querySelector('i');
          var textSpan = link.querySelector('span');
          var text = textSpan ? textSpan.innerText.trim() : link.innerText.trim();
          var iconComputed = icon ? window.getComputedStyle(icon) : null;
          var beforeStyle = icon ? window.getComputedStyle(icon, '::before') : null;

          var content = beforeStyle ? beforeStyle.getPropertyValue('content') : 'none';
          var charCode = (content && content.length > 2) ? content.charCodeAt(1).toString(16).toUpperCase() : null;

          return {
            text: text,
            iconClass: icon ? icon.className : null,
            fontFamily: iconComputed ? iconComputed.fontFamily : null,
            content: content,
            charCode: charCode,
            iconWidth: icon ? icon.offsetWidth : 0,
            iconHeight: icon ? icon.offsetHeight : 0,
            isValid: content !== 'none' && content !== '""' && content !== 'normal' && (icon ? icon.offsetHeight > 0 : false)
          };
        });

        return {
          isOpen: isOpen,
          linkCount: links.length,
          links: linkResults
        };
      })()
    `);

    console.log(`Drawer is-open: ${drawerData.isOpen}, total links: ${drawerData.linkCount}`);
    let allIconsPassed = true;

    for (const item of drawerData.links) {
      const status = item.isValid ? 'PASSED ✓' : 'FAILED ✗ (MISSING GLYPH)';
      if (!item.isValid) allIconsPassed = false;
      console.log(`  • "${item.text}": class=[${item.iconClass}], glyph=${item.content} (U+${item.charCode}), size=${item.iconWidth}x${item.iconHeight}px -> ${status}`);
    }

    await captureScreenshot('fix_verified_drawer_icons_375px.png');

    // Test drawer close
    await evalExpr(`document.getElementById('mobileNavClose').click();`);
    await sleep(300);

    const drawerClosed = await evalExpr(`!document.getElementById('mobileNav').classList.contains('is-open')`);
    console.log(`Drawer closed successfully: ${drawerClosed}`);

    // -------------------------------------------------------------
    // PART 3: ADMIN "XEM WEBSITE" VIEWING MODE - NO OVERLAP
    // -------------------------------------------------------------
    console.log('\n======================================================');
    console.log('PART 3: ADMIN "XEM WEBSITE" PREVIEW - NO OVERLAP');
    console.log('======================================================');

    await setViewport(375, 812);
    await send('Page.navigate', { url: BASE_URL + '/pages/admin/index.html?view=website' });
    await sleep(800);

    const adminPreviewData = await evalExpr(`
      (function() {
        var floatingBtn = document.querySelector('.admin-sidebar-toggle-btn--floating');
        var floatStyle = floatingBtn ? window.getComputedStyle(floatingBtn) : null;
        var isFloatingVisible = floatStyle && floatStyle.display !== 'none';

        var iframe = document.getElementById('adminWebsitePreviewFrame');
        var iframeRect = iframe ? iframe.getBoundingClientRect() : null;

        return {
          hasFloatingBtn: !!floatingBtn,
          floatingDisplay: floatStyle ? floatStyle.display : null,
          isFloatingVisible: isFloatingVisible,
          iframeRect: iframeRect ? { width: iframeRect.width, height: iframeRect.height } : null
        };
      })()
    `);

    console.log(`Admin Viewing Website (375px):`);
    console.log(`  - Floating toggle display on mobile: ${adminPreviewData.floatingDisplay}`);
    console.log(`  - Is floating toggle visible on mobile: ${adminPreviewData.isFloatingVisible} (Must be false to prevent logo overlap!)`);
    console.log(`  - Iframe size: ${adminPreviewData.iframeRect ? `${adminPreviewData.iframeRect.width}x${adminPreviewData.iframeRect.height}` : 'None'}`);

    const previewPassed = !adminPreviewData.isFloatingVisible;
    console.log(`  -> RESULT: ${previewPassed ? 'PASSED ✓' : 'FAILED ✗'}`);

    await captureScreenshot('fix_verified_admin_viewing_website_375px.png');

    console.log('\n======================================================');
    console.log('OVERALL TEST RESULTS:');
    console.log(`  1. Header Overlap Tests: ${allOverlapPassed ? '100% PASSED' : 'FAILED'}`);
    console.log(`  2. Drawer Icons Tests:   ${allIconsPassed ? '100% PASSED' : 'FAILED'}`);
    console.log(`  3. Admin Preview Test:   ${previewPassed ? '100% PASSED' : 'FAILED'}`);
    console.log('======================================================');

  } finally {
    ws.close();
    chrome.kill();
  }
}

main().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
