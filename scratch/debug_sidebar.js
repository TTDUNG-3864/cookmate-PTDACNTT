const http = require('http');
const { spawn } = require('child_process');

async function debugSidebar() {
  const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
    '--headless=new',
    '--remote-debugging-port=9261',
    '--disable-gpu',
    '--no-sandbox',
    '--user-data-dir=C:/temp/cdbg_sb_' + Date.now()
  ]);
  await new Promise(r => setTimeout(r, 1200));

  const target = await new Promise((resolve) => {
    http.request({ host: '127.0.0.1', port: 9261, path: '/json/new?http://127.0.0.1:8089/pages/auth/login.html', method: 'PUT' }, res => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(JSON.parse(d)));
    }).end();
  });

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 1;
  const send = (m, p = {}) => new Promise((resolve) => {
    const i = id++;
    const h = (e) => { const d = JSON.parse(e.data); if (d.id === i) { ws.removeEventListener('message', h); resolve(d.result); } };
    ws.addEventListener('message', h);
    ws.send(JSON.stringify({ id: i, method: m, params: p }));
  });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1366, height: 500, deviceScaleFactor: 1, mobile: false });

  // Log in as admin via localStorage directly
  const loginRes = await send('Runtime.evaluate', { expression: `
    (function() {
      try {
        localStorage.setItem('cookmate_current_user', JSON.stringify({
          id: 'admin1',
          name: 'Quản trị viên CookMate',
          email: 'admin@cookmate.vn',
          role: 'admin'
        }));
        window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';
        return { success: true };
      } catch(e) {
        return { error: e.message, stack: e.stack };
      }
    })()
  `, returnByValue: true });
  console.log('   Login Eval Result:', loginRes);
  
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 200));
    const u = await send('Runtime.evaluate', { expression: 'window.location.href + " | title: " + document.title + " | sidebar: " + !!document.getElementById("adminSidebar")', returnByValue: true });
    console.log('   Polling:', u.result.value);
    if (u.result.value.includes('adminSidebar: true') || u.result.value.includes('sidebar: true')) break;
  }

  const diag = await send('Runtime.evaluate', {
    expression: `
      (function() {
        var sidebar = document.getElementById('adminSidebar');
        if (!sidebar) return { error: 'No sidebar found' };
        var sRect = sidebar.getBoundingClientRect();
        var cs = getComputedStyle(sidebar);
        var report = {
          sidebar: {
            width: cs.width,
            clientWidth: sidebar.clientWidth,
            scrollWidth: sidebar.scrollWidth,
            clientHeight: sidebar.clientHeight,
            scrollHeight: sidebar.scrollHeight,
            overflowX: cs.overflowX,
            overflowY: cs.overflowY,
            hasHScroll: sidebar.scrollWidth > sidebar.clientWidth
          },
          overflowingElements: []
        };

        var all = sidebar.querySelectorAll('*');
        var childReports = [];
        all.forEach(function(el) {
          childReports.push({
            tag: el.tagName,
            id: el.id,
            className: el.className,
            clientWidth: el.clientWidth,
            scrollWidth: el.scrollWidth,
            offsetWidth: el.offsetWidth,
            rectWidth: el.getBoundingClientRect().width,
            text: el.textContent.trim().substring(0, 30)
          });
        });
        var header = sidebar.querySelector('.admin-sidebar__header');
        var logo = sidebar.querySelector('.admin-sidebar__logo');
        var badge = sidebar.querySelector('.admin-sidebar__badge');
        var toggle = sidebar.querySelector('#sidebarToggleBtn');
        var nav = sidebar.querySelector('.admin-sidebar__nav');
        var footer = sidebar.querySelector('.admin-sidebar__footer');

        report.headerBreakdown = {
          headerClientWidth: header ? header.clientWidth : 0,
          headerScrollWidth: header ? header.scrollWidth : 0,
          headerPaddingLeft: header ? getComputedStyle(header).paddingLeft : 0,
          headerPaddingRight: header ? getComputedStyle(header).paddingRight : 0,
          logoWidth: logo ? logo.getBoundingClientRect().width : 0,
          badgeWidth: badge ? badge.getBoundingClientRect().width : 0,
          toggleWidth: toggle ? toggle.getBoundingClientRect().width : 0,
          sumOfParts: (logo ? logo.getBoundingClientRect().width : 0) + 
                      (badge ? badge.getBoundingClientRect().width : 0) + 
                      (toggle ? toggle.getBoundingClientRect().width : 0) + 24 /* gaps */
        };

        var navH = nav ? nav.scrollHeight : 0;
        var headerH = header ? header.offsetHeight : 0;
        var footerH = footer ? footer.offsetHeight : 0;
        report.heights = {
          sidebarClientHeight: sidebar.clientHeight,
          sidebarScrollHeight: sidebar.scrollHeight,
          headerH: headerH,
          navH: navH,
          footerH: footerH,
          totalChildrenHeight: headerH + navH + footerH
        };
        return report;
      })()
    `,
    returnByValue: true
  });

  // Test scrolling to bottom
  const scrollTest = await send('Runtime.evaluate', {
    expression: `
      (function() {
        var sidebar = document.getElementById('adminSidebar');
        sidebar.scrollTop = 400;
        var logoutBtn = sidebar.querySelector('button[onclick*="handleLogout"], button.admin-sidebar__link.text-danger');
        var logoutRect = logoutBtn ? logoutBtn.getBoundingClientRect() : null;
        var footer = sidebar.querySelector('.admin-sidebar__footer');
        var footerRect = footer ? footer.getBoundingClientRect() : null;
        return {
          scrollTopAfterScroll: sidebar.scrollTop,
          canScroll: sidebar.scrollTop > 0,
          logoutRect: logoutRect,
          footerRect: footerRect,
          windowHeight: window.innerHeight,
          logoutVisible: logoutRect ? (logoutRect.top >= 0 && logoutRect.bottom <= window.innerHeight) : false,
          footerVisible: footerRect ? (footerRect.top >= 0 && footerRect.bottom <= window.innerHeight + 1) : false
        };
      })()
    `,
    returnByValue: true
  });
  console.log('SCROLL TO BOTTOM TEST:', scrollTest.result.value);
  chrome.kill();
}
debugSidebar();
