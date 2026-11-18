// test_header_overlap_and_icons.js
// Automated verification suite for CookMate Bug A (Admin Header Overlap) and Bug B (Missing Drawer Icons)
const http = require('http');
const fs = require('fs');
const path = require('path');

const CHROME_DEBUG_PORT = 9222;
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
    if (postData) {
      req.write(postData);
    }
    req.end();
  });
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.id = 1;
    this.callbacks = new Map();
    this.ws = null;
  }

  async connect() {
    const WebSocket = require('ws');
    this.ws = new WebSocket(this.wsUrl);
    return new Promise((resolve, reject) => {
      this.ws.on('open', resolve);
      this.ws.on('error', reject);
      this.ws.on('message', (msg) => {
        const parsed = JSON.parse(msg.toString());
        if (parsed.id && this.callbacks.has(parsed.id)) {
          const { resolve, reject } = this.callbacks.get(parsed.id);
          this.callbacks.delete(parsed.id);
          if (parsed.error) reject(parsed.error);
          else resolve(parsed.result);
        }
      });
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.id++;
      this.callbacks.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true
    });
    if (res.exceptionDetails) {
      throw new Error(JSON.stringify(res.exceptionDetails));
    }
    return res.result.value;
  }

  async captureScreenshot(filename) {
    const res = await this.send('Page.captureScreenshot', { format: 'png' });
    const fullPath = path.join(SCREENSHOT_DIR, filename);
    fs.writeFileSync(fullPath, Buffer.from(res.data, 'base64'));
    console.log(`Saved screenshot: ${fullPath}`);
    return fullPath;
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

async function getOrCreateTarget() {
  const version = await sendHttpRequest({
    host: '127.0.0.1',
    port: CHROME_DEBUG_PORT,
    path: '/json/version',
    method: 'GET'
  });
  console.log('Connected to Chrome version:', version['User-Agent'] || version['Browser']);

  const newTab = await sendHttpRequest({
    host: '127.0.0.1',
    port: CHROME_DEBUG_PORT,
    path: '/json/new?' + encodeURIComponent(BASE_URL + '/index.html'),
    method: 'PUT'
  });

  return newTab.webSocketDebuggerUrl;
}

async function runSuite() {
  const wsUrl = await getOrCreateTarget();
  const cdp = new CDPClient(wsUrl);
  await cdp.connect();
  console.log('CDP WebSocket connected!');

  await cdp.send('Page.enable');
  await cdp.send('DOM.enable');
  await cdp.send('CSS.enable');

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

  const results = {
    overlapTests: [],
    drawerIconTests: [],
    adminWebsitePreviewTest: null
  };

  // Helper to set viewport
  async function setViewport(w, h) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: w,
      height: h,
      deviceScaleFactor: 2,
      mobile: w < 1024
    });
  }

  // Set user as Admin in localStorage first
  await cdp.eval(`
    localStorage.setItem('cookmate_current_user', JSON.stringify({
      id: 99,
      username: 'admin',
      name: 'Nguyễn Quản Trị',
      email: 'admin@cookmate.vn',
      role: 'admin',
      avatar: ''
    }));
  `);

  console.log('\n======================================================');
  console.log('TEST SUITE 1: HEADER OVERLAP & LAYOUT ON VIEWPORTS');
  console.log('======================================================');

  for (const vp of testViewports) {
    await setViewport(vp.width, vp.height);
    await cdp.send('Page.navigate', { url: BASE_URL + '/index.html' });
    await sleep(400);

    const metrics = await cdp.eval(`
      (function() {
        var menuToggle = document.getElementById('menuToggle');
        var logo = document.querySelector('.logo') || document.querySelector('.site-header__logo');
        var logoIcon = document.querySelector('.logo-icon');
        var logoText = document.querySelector('.logo-text');
        var favBtn = document.querySelector('.header-fav-btn');
        var authArea = document.getElementById('authArea');
        var floatingBtn = document.querySelector('.admin-sidebar-toggle-btn--floating');

        var docWidth = document.documentElement.clientWidth;
        var scrollWidth = document.documentElement.scrollWidth;

        var mtRect = menuToggle ? menuToggle.getBoundingClientRect() : null;
        var logoRect = logo ? logo.getBoundingClientRect() : null;
        var favRect = favBtn ? favBtn.getBoundingClientRect() : null;
        var authRect = authArea ? authArea.getBoundingClientRect() : null;
        var floatRect = floatingBtn ? floatingBtn.getBoundingClientRect() : null;

        var mtStyle = menuToggle ? window.getComputedStyle(menuToggle) : null;
        var logoStyle = logo ? window.getComputedStyle(logo) : null;

        // Check horizontal overlap between menuToggle and logo:
        // They overlap if (mtRect.right > logoRect.left) AND (mtRect.left < logoRect.right)
        var isMenuToggleVisible = mtStyle && mtStyle.display !== 'none' && mtRect.width > 0;
        var overlapsWithLogo = false;
        var horizontalGap = 0;

        if (isMenuToggleVisible && logoRect) {
          if (mtRect.right > logoRect.left && mtRect.left < logoRect.right) {
            overlapsWithLogo = true;
          } else {
            horizontalGap = logoRect.left - mtRect.right;
          }
        }

        // Check if floatingBtn is visible and overlaps
        var floatingOverlaps = false;
        if (floatingBtn) {
          var floatStyle = window.getComputedStyle(floatingBtn);
          if (floatStyle.display !== 'none' && floatRect.width > 0 && logoRect) {
            if (floatRect.right > logoRect.left && floatRect.left < logoRect.right) {
              floatingOverlaps = true;
            }
          }
        }

        return {
          viewportWidth: window.innerWidth,
          scrollWidth: scrollWidth,
          hasHorizontalOverflow: scrollWidth > docWidth + 1,
          isMenuToggleVisible: isMenuToggleVisible,
          menuToggleRect: mtRect ? { left: mtRect.left, right: mtRect.right, width: mtRect.width, height: mtRect.height } : null,
          logoRect: logoRect ? { left: logoRect.left, right: logoRect.right, width: logoRect.width, height: logoRect.height } : null,
          horizontalGapBetweenToggleAndLogo: horizontalGap,
          overlapsWithLogo: overlapsWithLogo,
          floatingOverlaps: floatingOverlaps,
          favBtnRight: favRect ? favRect.right : null,
          authAreaRight: authRect ? authRect.right : null
        };
      })()
    `);

    const passed = !metrics.overlapsWithLogo && !metrics.floatingOverlaps && !metrics.hasHorizontalOverflow;
    console.log(`[${vp.name} (${vp.width}px)] Passed: ${passed ? 'YES' : 'FAILED'}`);
    console.log(`  - Menu Toggle visible: ${metrics.isMenuToggleVisible}`);
    if (metrics.menuToggleRect && metrics.logoRect) {
      console.log(`  - MenuToggle [${metrics.menuToggleRect.left.toFixed(1)} -> ${metrics.menuToggleRect.right.toFixed(1)}] vs Logo [${metrics.logoRect.left.toFixed(1)} -> ${metrics.logoRect.right.toFixed(1)}]`);
      console.log(`  - Gap between Toggle & Logo: ${metrics.horizontalGapBetweenToggleAndLogo.toFixed(1)}px (Overlap: ${metrics.overlapsWithLogo})`);
    }
    console.log(`  - Horizontal scroll overflow: ${metrics.hasHorizontalOverflow} (scrollWidth=${metrics.scrollWidth}, clientWidth=${metrics.viewportWidth})`);

    results.overlapTests.push({ viewport: vp, metrics, passed });

    if (vp.width === 320 || vp.width === 375 || vp.width === 430 || vp.width === 1200) {
      await cdp.captureScreenshot(`fix_header_${vp.width}px.png`);
    }
  }

  console.log('\n======================================================');
  console.log('TEST SUITE 2: DRAWER OPEN & ICON GLYPH VERIFICATION');
  console.log('======================================================');

  // Set viewport to 375px for mobile drawer test
  await setViewport(375, 812);
  await cdp.send('Page.navigate', { url: BASE_URL + '/index.html' });
  await sleep(400);

  // Click #menuToggle to open drawer
  await cdp.eval(`
    var btn = document.getElementById('menuToggle');
    if (btn) btn.click();
  `);
  await sleep(400);

  const drawerData = await cdp.eval(`
    (function() {
      var nav = document.getElementById('mobileNav');
      var overlay = document.getElementById('mobileNavOverlay');
      var isOpen = nav && nav.classList.contains('is-open');
      var isOverlayVisible = overlay && overlay.classList.contains('is-visible');

      var links = Array.from(nav.querySelectorAll('.mobile-nav__link'));
      var linkResults = links.map(function(link) {
        var icon = link.querySelector('i');
        var text = link.querySelector('span') ? link.querySelector('span').innerText.trim() : link.innerText.trim();
        var iconComputed = icon ? window.getComputedStyle(icon) : null;
        var iconBeforeComputed = icon ? window.getComputedStyle(icon, '::before') : null;

        var content = iconBeforeComputed ? iconBeforeComputed.getPropertyValue('content') : 'none';
        var charCode = (content && content.length > 2) ? content.charCodeAt(1).toString(16) : null;

        return {
          text: text,
          iconClass: icon ? icon.className : null,
          fontFamily: iconComputed ? iconComputed.fontFamily : null,
          hasIconElement: !!icon,
          renderedContent: content,
          hexCode: charCode,
          iconWidth: icon ? icon.offsetWidth : 0,
          iconHeight: icon ? icon.offsetHeight : 0,
          isValidGlyph: content !== 'none' && content !== '""' && content !== 'normal'
        };
      });

      return {
        isOpen: isOpen,
        isOverlayVisible: isOverlayVisible,
        linkCount: links.length,
        links: linkResults
      };
    })()
  `);

  console.log(`Drawer is-open: ${drawerData.isOpen}, overlay: ${drawerData.isOverlayVisible}`);
  console.log(`Found ${drawerData.linkCount} drawer navigation links:`);

  let allIconsValid = true;
  for (const item of drawerData.links) {
    const status = item.isValidGlyph ? 'OK' : 'MISSING/PRO-ONLY';
    if (!item.isValidGlyph) allIconsValid = false;
    console.log(`  • "${item.text}" => class: [${item.iconClass}], glyph: ${item.renderedContent} (U+${item.hexCode}), size: ${item.iconWidth}x${item.iconHeight}px -> ${status}`);
  }

  results.drawerIconTests = drawerData;
  await cdp.captureScreenshot('fix_drawer_all_icons_375px.png');

  // Test drawer close
  await cdp.eval(`
    var closeBtn = document.getElementById('mobileNavClose');
    if (closeBtn) closeBtn.click();
  `);
  await sleep(300);

  const isClosed = await cdp.eval(`
    var nav = document.getElementById('mobileNav');
    return nav && !nav.classList.contains('is-open');
  `);
  console.log(`Drawer closed cleanly: ${isClosed}`);

  console.log('\n======================================================');
  console.log('TEST SUITE 3: ADMIN PREVIEW "XEM WEBSITE" NO OVERLAP');
  console.log('======================================================');

  await setViewport(375, 812);
  await cdp.send('Page.navigate', { url: BASE_URL + '/pages/admin/index.html?view=website' });
  await sleep(800);

  const previewMetrics = await cdp.eval(`
    (function() {
      var floatingBtn = document.querySelector('.admin-sidebar-toggle-btn--floating');
      var floatStyle = floatingBtn ? window.getComputedStyle(floatingBtn) : null;
      var isFloatingVisible = floatStyle && floatStyle.display !== 'none';

      var iframe = document.getElementById('adminWebsitePreviewFrame');
      var iframeRect = iframe ? iframe.getBoundingClientRect() : null;

      return {
        floatingBtnExists: !!floatingBtn,
        isFloatingVisibleOnMobile: isFloatingVisible,
        floatingDisplay: floatStyle ? floatStyle.display : null,
        iframeRect: iframeRect ? { width: iframeRect.width, height: iframeRect.height } : null
      };
    })()
  `);

  console.log('Admin Viewing Website preview:');
  console.log(`  - Floating toggle button exists: ${previewMetrics.floatingBtnExists}`);
  console.log(`  - Floating toggle button display on mobile: ${previewMetrics.floatingDisplay}`);
  console.log(`  - Is floating toggle button visible on mobile: ${previewMetrics.isFloatingVisibleOnMobile} (Must be false!)`);

  await cdp.captureScreenshot('fix_admin_viewing_website_375px.png');
  results.adminWebsitePreviewTest = previewMetrics;

  cdp.close();
  console.log('\nAll tests complete!');
  return { results, allIconsValid };
}

runSuite().catch(err => {
  console.error('Test suite failed with error:', err);
  process.exit(1);
});
