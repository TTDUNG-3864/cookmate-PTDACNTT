const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const DEBUG_PORT = 9267;
const SCREENSHOT_DIR = path.join(__dirname, 'screenshots_mobile_header');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

let testIndex = 0;
let passCount = 0;
let failCount = 0;

function assert(condition, message) {
  testIndex++;
  if (condition) {
    passCount++;
    console.log(`  [PASS #${testIndex}] ${message}`);
  } else {
    failCount++;
    console.error(`  [FAIL #${testIndex}] ${message}`);
  }
}

async function runHeaderSuite() {
  console.log('========================================================================');
  console.log('  COOKMATE: ADMIN MOBILE HEADER RESPONSIVE VERIFICATION SUITE           ');
  console.log('========================================================================\n');

  const userDataDir = 'C:\\temp\\chrome_header_' + Date.now();
  const chrome = spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    '--disable-gpu',
    '--no-sandbox',
    `--user-data-dir=${userDataDir}`
  ], { stdio: 'ignore' });

  await sleep(1500);

  async function createPage(url, viewport = { width: 375, height: 667 }) {
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
      mobile: viewport.width < 1024
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
    // -------------------------------------------------------------
    // TEST GROUP 1: MULTI-VIEWPORT VERIFICATION (320px - 430px)
    // -------------------------------------------------------------
    console.log('\n--- TEST GROUP 1: BẢO VỆ TIÊU ĐỀ, CHIỀU CAO VÀ TRÀN NGANG MOBILE ---');

    const mobileViewports = [
      { name: '320px', width: 320, height: 600 },
      { name: '360px', width: 360, height: 800 },
      { name: '375px', width: 375, height: 667 },
      { name: '390px', width: 390, height: 844 },
      { name: '414px', width: 414, height: 896 },
      { name: '430px', width: 430, height: 932 }
    ];

    for (const vp of mobileViewports) {
      const page = await createPage('http://127.0.0.1:8089/index.html', vp);
      await sleep(300);

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
        window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';
      `);
      await sleep(1000);

      const metrics = await page.evalJs(`
        (function() {
          const header = document.querySelector('.admin-header');
          const title = header ? header.querySelector('.admin-header__title') : null;
          const toggle = header ? header.querySelector('.admin-sidebar-toggle-btn') : null;
          const actions = header ? header.querySelector('.admin-header__actions') : null;
          const postBtn = actions ? actions.querySelector('a') : null;
          const logoutBtn = actions ? actions.querySelector('button') : null;

          const hRect = header ? header.getBoundingClientRect() : { height: 0 };
          const tRect = title ? title.getBoundingClientRect() : { width: 0 };

          return {
            headerHeight: Math.round(hRect.height),
            titleWidth: Math.round(tRect.width),
            titleWhiteSpace: title ? window.getComputedStyle(title).whiteSpace : '',
            hasHorizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
            toggleVisible: toggle ? toggle.getBoundingClientRect().width > 0 : false,
            logoutVisible: logoutBtn ? logoutBtn.getBoundingClientRect().width > 0 : false,
            postBtnText: postBtn ? postBtn.innerText.trim() : ''
          };
        })()
      `);

      assert(metrics.headerHeight <= 110, `${vp.name}: Chiều cao header gọn gàng (${metrics.headerHeight}px <= 110px, trước đây 425px)`);
      assert(metrics.titleWidth >= 200, `${vp.name}: Tiêu đề có độ rộng đầy đủ (${metrics.titleWidth}px >= 200px, không bị bóp 7px)`);
      assert(metrics.titleWhiteSpace === 'nowrap', `${vp.name}: Tiêu đề có white-space: nowrap (triệt tiêu 100% rớt từng ký tự)`);
      assert(!metrics.hasHorizontalScroll, `${vp.name}: Không có cuộn ngang toàn trang (scrollW: ${metrics.scrollWidth}px === clientW: ${metrics.clientWidth}px)`);
      assert(metrics.toggleVisible, `${vp.name}: Nút hamburger hiển thị đầy đủ, dễ bấm`);
      assert(metrics.logoutVisible, `${vp.name}: Nút đăng xuất hiển thị rõ ràng, dễ bấm`);

      await page.screenshot(`verified_${vp.name}.png`);
      await page.close();
    }

    // -------------------------------------------------------------
    // TEST GROUP 2: TƯƠNG TÁC HAMBURGER DRAWER TRÊN MOBILE
    // -------------------------------------------------------------
    console.log('\n--- TEST GROUP 2: TƯƠNG TÁC HAMBURGER DRAWER TRÊN MOBILE (375x667) ---');
    {
      const page = await createPage('http://127.0.0.1:8089/index.html', { width: 375, height: 667 });
      await sleep(300);
      await page.evalJs(`
        localStorage.setItem('cookmate_current_user', JSON.stringify({ id: 'admin_1', name: 'Quản trị viên', role: 'admin' }));
        localStorage.setItem('cookmate_admin_session', JSON.stringify({ adminId: 'admin_1', role: 'admin' }));
        window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';
      `);
      await sleep(1000);

      // Ban đầu: Sidebar đóng
      const initialOpen = await page.evalJs(`document.getElementById('adminSidebar').classList.contains('active')`);
      assert(!initialOpen, 'Khởi tạo trên Mobile: Sidebar đóng mặc định');

      // Click nút Hamburger
      await page.evalJs(`
        const btn = document.getElementById('sidebarToggleBtn');
        if (btn) btn.click();
      `);
      await sleep(400);

      const afterOpen = await page.evalJs(`
        ({
          sidebarActive: document.getElementById('adminSidebar').classList.contains('active'),
          backdropActive: document.getElementById('sidebarBackdrop').classList.contains('active'),
          sidebarWidth: document.getElementById('adminSidebar').getBoundingClientRect().width
        })
      `);
      assert(afterOpen.sidebarActive, 'Bấm Hamburger: Drawer mở ra (.active)');
      assert(afterOpen.backdropActive, 'Bấm Hamburger: Backdrop phủ mờ màn hình (.active)');
      assert(afterOpen.sidebarWidth <= 375, `Drawer vừa vặn trong màn hình (${afterOpen.sidebarWidth}px <= 375px)`);

      await page.screenshot('drawer_opened_375px.png');

      // Click backdrop để đóng drawer
      await page.evalJs(`document.getElementById('sidebarBackdrop').click();`);
      await sleep(400);

      const afterClose = await page.evalJs(`
        ({
          sidebarActive: document.getElementById('adminSidebar').classList.contains('active'),
          backdropActive: document.getElementById('sidebarBackdrop').classList.contains('active')
        })
      `);
      assert(!afterClose.sidebarActive, 'Bấm Backdrop: Drawer đóng lại');
      assert(!afterClose.backdropActive, 'Bấm Backdrop: Backdrop ẩn');

      await page.close();
    }

    // -------------------------------------------------------------
    // TEST GROUP 3: CUỘN TRANG KHÔNG BỊ HEADER CHE NỘI DUNG
    // -------------------------------------------------------------
    console.log('\n--- TEST GROUP 3: CUỘN TRANG VÀ KIỂM TRA HEADER STICKY KHÔNG CHE NỘI DUNG ---');
    {
      const page = await createPage('http://127.0.0.1:8089/index.html', { width: 375, height: 667 });
      await sleep(300);
      await page.evalJs(`
        localStorage.setItem('cookmate_current_user', JSON.stringify({ id: 'admin_1', name: 'Quản trị viên', role: 'admin' }));
        localStorage.setItem('cookmate_admin_session', JSON.stringify({ adminId: 'admin_1', role: 'admin' }));
        window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';
      `);
      await sleep(1000);

      // Cuộn xuống 300px
      await page.evalJs(`window.scrollTo(0, 300);`);
      await sleep(300);

      const scrollCheck = await page.evalJs(`
        (function() {
          const header = document.querySelector('.admin-header');
          const hRect = header.getBoundingClientRect();
          const cards = document.querySelectorAll('.stat-card');
          const firstCard = cards[0];
          const cRect = firstCard ? firstCard.getBoundingClientRect() : null;

          return {
            headerTop: hRect.top,
            headerHeight: Math.round(hRect.height),
            scrollY: window.scrollY,
            viewportHeight: window.innerHeight,
            contentVisibleArea: window.innerHeight - hRect.height
          };
        })()
      `);

      assert(scrollCheck.headerTop === 0, 'Header giữ vị trí sticky top 0 khi cuộn');
      assert(scrollCheck.contentVisibleArea >= 500, `Vùng nhìn thấy nội dung trang rộng rãi (${scrollCheck.contentVisibleArea}px / ${scrollCheck.viewportHeight}px)`);

      await page.screenshot('scrolled_375px.png');
      await page.close();
    }

    // -------------------------------------------------------------
    // TEST GROUP 4: CÁC TRANG QUẢN TRỊ KHÁC TRÊN MOBILE
    // -------------------------------------------------------------
    console.log('\n--- TEST GROUP 4: KIỂM TRA CÁC TRANG QUẢN TRỊ KHÁC TRÊN MOBILE (375x667) ---');

    const otherPages = [
      { url: 'approve-recipes.html', expectedTitle: 'Hàng đợi Duyệt công thức' },
      { url: 'categories.html', expectedTitle: 'Quản lý Danh mục món ăn' },
      { url: 'ingredients.html', expectedTitle: 'Quản lý Bảng Nguyên liệu' },
      { url: 'accounts.html', expectedTitle: 'Quản lý Tài khoản' },
      { url: 'comments.html', expectedTitle: 'Quản lý Bình luận' },
      { url: 'statistics.html', expectedTitle: 'Báo cáo & Thống kê' }
    ];

    for (const p of otherPages) {
      const page = await createPage('http://127.0.0.1:8089/index.html', { width: 375, height: 667 });
      await sleep(200);
      await page.evalJs(`
        localStorage.setItem('cookmate_current_user', JSON.stringify({ id: 'admin_1', name: 'Quản trị viên', role: 'admin' }));
        localStorage.setItem('cookmate_admin_session', JSON.stringify({ adminId: 'admin_1', role: 'admin' }));
        window.location.href = 'http://127.0.0.1:8089/pages/admin/${p.url}';
      `);
      await sleep(1000);

      const res = await page.evalJs(`
        (function() {
          const header = document.querySelector('.admin-header');
          const title = header ? header.querySelector('.admin-header__title') : null;
          const hRect = header ? header.getBoundingClientRect() : { height: 0 };
          return {
            height: Math.round(hRect.height),
            hasHScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            titleText: title ? title.innerText.trim() : ''
          };
        })()
      `);

      assert(res.height <= 110, `${p.url}: Chiều cao header gọn gàng (${res.height}px <= 110px)`);
      assert(!res.hasHScroll, `${p.url}: Không tràn ngang`);

      await page.close();
    }

    // -------------------------------------------------------------
    // TEST GROUP 5: BẢO VỆ GIAO DIỆN DESKTOP VÀ TABLET (KHÔNG HỒI QUY)
    // -------------------------------------------------------------
    console.log('\n--- TEST GROUP 5: KIỂM TRA DESKTOP VÀ TABLET (KHÔNG BỊ ẢNH HƯỞNG) ---');

    const desktopViewports = [
      { name: '768px (iPad Portrait)', width: 768, height: 1024 },
      { name: '1024px (iPad Landscape)', width: 1024, height: 768 },
      { name: '1366px (Laptop HD)', width: 1366, height: 768 },
      { name: '1440px (MacBook)', width: 1440, height: 900 }
    ];

    for (const vp of desktopViewports) {
      const page = await createPage('http://127.0.0.1:8089/index.html', vp);
      await sleep(200);
      await page.evalJs(`
        localStorage.setItem('cookmate_current_user', JSON.stringify({ id: 'admin_1', name: 'Quản trị viên', role: 'admin' }));
        localStorage.setItem('cookmate_admin_session', JSON.stringify({ adminId: 'admin_1', role: 'admin' }));
        window.location.href = 'http://127.0.0.1:8089/pages/admin/index.html';
      `);
      await sleep(1000);

      const dMetrics = await page.evalJs(`
        (function() {
          const header = document.querySelector('.admin-header');
          const title = header ? header.querySelector('.admin-header__title') : null;
          const actions = header ? header.querySelector('.admin-header__actions') : null;
          const postBtn = actions ? actions.querySelector('a') : null;
          const hRect = header ? header.getBoundingClientRect() : { height: 0 };

          return {
            height: Math.round(hRect.height),
            titleText: title ? title.innerText.trim() : '',
            postBtnText: postBtn ? postBtn.innerText.trim() : '',
            hasHScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth
          };
        })()
      `);

      assert(dMetrics.height >= 50 && dMetrics.height <= 85, `${vp.name}: Chiều cao header desktop chuẩn (${dMetrics.height}px)`);
      if (vp.width >= 1024) {
        assert(dMetrics.titleText.includes('Bảng điều khiển Quản trị'), `${vp.name}: Tiêu đề desktop đầy đủ ("${dMetrics.titleText}")`);
        assert(dMetrics.postBtnText.includes('Đăng món mới (Admin)'), `${vp.name}: Nút đăng món hiển thị đầy đủ nhãn desktop ("${dMetrics.postBtnText}")`);
      }
      assert(!dMetrics.hasHScroll, `${vp.name}: 0 tràn ngang`);

      await page.screenshot(`desktop_${vp.width}.png`);
      await page.close();
    }

    console.log('\n========================================================================');
    console.log(`  KẾT QUẢ KIỂM THỬ: ${passCount} PASSED / ${failCount} FAILED (TỔNG: ${testIndex} TESTS)`);
    console.log('========================================================================\n');

    if (failCount === 0) {
      console.log('>>> XUẤT SẮC! TOÀN BỘ CÁC BÀI TEST MOBILE VÀ DESKTOP ĐỀU ĐẠT 100%! <<<\n');
    }

  } catch (err) {
    console.error('Fatal error during test suite:', err);
  } finally {
    chrome.kill();
  }
}

runHeaderSuite();
