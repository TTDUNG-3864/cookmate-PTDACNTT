// CookMate ChefBot AI — 100% MySQL 300-Recipe Grounded Culinary Assistant.
// API credentials remain strictly server-managed; this widget exchanges only chat & diagnostics metadata.
(function () {
  'use strict';

  var state = { open: false, expanded: false, busy: false, sessionId: '', csrfToken: '', recipeId: null };
  var API_BASE = String(window.COOKMATE_API_BASE_URL || '').replace(/\/$/, '');
  var QUICK_PROMPTS = [
    ['🥘', 'Gợi ý món từ nguyên liệu', 'Tôi có thịt gà và cà chua, nấu món gì?'],
    ['🍜', 'Đặc sản vùng miền', 'Hướng dẫn nấu Bún thang Hà Nội tinh hoa phố cổ'],
    ['🔄', 'Thay thế nguyên liệu', 'Không có xì dầu thì thay bằng gì?'],
    ['🌿', 'Khử mùi & sơ chế', 'Thịt gà của tôi bị hôi có thể xử lý bằng gì?'],
    ['⚖️', 'Co giãn khẩu phần', 'Quy đổi Phở bò Hà Nội cho 8 người ăn'],
    ['🆘', 'Cứu món bị mặn', 'Cá kho bị mặn thì xử lý sao cho vừa miệng?']
  ];
  var RECIPE_PROMPTS = [
    ['⚖️', 'Đổi sang 6 người', 'Quy đổi công thức món này cho 6 người ăn'],
    ['📊', 'Calo & Dinh dưỡng', 'Món này có bao nhiêu calo mỗi phần?'],
    ['🔄', 'Thay thế gia vị', 'Nếu thiếu gia vị trong món này thì thay bằng gì?'],
    ['🔥', 'Mẹo nấu ngon hơn', 'Cần lưu ý gì để nấu món này không bị lỗi?']
  ];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char];
    });
  }

  function markdown(value) {
    var lines = esc(value).split(/\r?\n/);
    var html = [], listType = '';
    function closeList() { if (listType) { html.push(listType === 'ol' ? '</ol>' : '</ul>'); listType = ''; } }
    lines.forEach(function (line) {
      var trimmed = line.trim();
      var ordered = /^\d+[.)]\s+/.test(trimmed);
      var bullet = /^[-*•]\s+/.test(trimmed);
      if (ordered || bullet) {
        var nextType = ordered ? 'ol' : 'ul';
        if (listType !== nextType) { closeList(); listType = nextType; html.push(nextType === 'ol' ? '<ol>' : '<ul>'); }
        trimmed = trimmed.replace(ordered ? /^\d+[.)]\s+/ : /^[-*•]\s+/, '');
        html.push('<li>' + inline(trimmed) + '</li>');
      } else {
        closeList();
        if (!trimmed) html.push('<div class="cmcb-spacer"></div>');
        else if (/^###\s+/.test(trimmed)) html.push('<h4>' + inline(trimmed.replace(/^###\s+/, '')) + '</h4>');
        else if (/^##\s+/.test(trimmed)) html.push('<h3>' + inline(trimmed.replace(/^##\s+/, '')) + '</h3>');
        else html.push('<p>' + inline(trimmed) + '</p>');
      }
    });
    closeList();
    return html.join('');
  }

  function inline(value) {
    return value
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  }

  function api(path, options) {
    options = options || {};
    var headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    if (state.csrfToken) headers['X-CSRF-Token'] = state.csrfToken;
    return fetch(API_BASE + path, Object.assign({ credentials: 'include', headers: headers }, options))
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (data.csrfToken) state.csrfToken = data.csrfToken;
          if (!response.ok || data.success === false) {
            var err = new Error(data.reply || data.error || 'Không thể kết nối với CookMate.');
            err.payload = data;
            throw err;
          }
          return data;
        });
      });
  }

  function detectRecipeId() {
    var match = window.location.search.match(/[?&](?:id|recipeId)=(\d+)/);
    return match ? Number(match[1]) : null;
  }

  function formatProviderLabel(diag) {
    if (!diag || typeof diag !== 'object') return { cls: 'is-gemini', text: '🟢 Gemini 2.5 Flash · Sẵn sàng' };
    var prov = String(diag.activeProvider || '');
    var model = String(diag.modelUsed || '');
    if (prov === 'gemini') {
      var nice = model === 'gemini-2.5-flash' ? 'Gemini 2.5 Flash'
        : model === 'gemini-2.5-flash-lite' ? 'Gemini 2.5 Flash-Lite'
        : ('Gemini (' + model + ')');
      return { cls: 'is-gemini', text: '🟢 ' + nice };
    }
    if (prov === 'ollama') {
      return { cls: 'is-ollama', text: '🟡 Đang dùng Ollama cục bộ (' + (model || 'qwen3.5:4b') + ')' };
    }
    return { cls: 'is-sql', text: '🟢 Dữ liệu chuẩn MySQL CookMate' };
  }

  function updateStatusBar(diag) {
    var pill = document.getElementById('cmcbStatusPill');
    if (!pill) return;
    var info = formatProviderLabel(diag);
    pill.className = 'cmcb-status-pill ' + info.cls;
    pill.textContent = info.text;
  }

  function styles() {
    if (document.getElementById('cmChefBotStyles')) return;
    var node = document.createElement('style');
    node.id = 'cmChefBotStyles';
    node.textContent = [
      '#cmChefBotLauncher{position:fixed;right:24px;bottom:22px;z-index:9998;border:0;border-radius:999px;background:linear-gradient(135deg,#E85D2A,#D94E1F);color:#fff;padding:13px 20px;font:700 14.5px/1.2 "Be Vietnam Pro",system-ui,sans-serif;box-shadow:0 12px 28px rgba(232,93,42,.34);cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:transform .2s ease,box-shadow .2s ease}',
      '#cmChefBotLauncher:hover{background:linear-gradient(135deg,#D94E1F,#C2410C);transform:translateY(-2px);box-shadow:0 16px 32px rgba(232,93,42,.42)}',
      '#cmChefBotLauncher.is-hidden{display:none}',
      '.cmcb-panel{position:fixed;right:24px;bottom:20px;z-index:9999;width:480px;max-width:calc(100vw - 32px);height:min(740px,calc(100vh - 40px));background:#FFF9F2;border:1px solid #E7E5E4;border-radius:20px;box-shadow:0 24px 64px rgba(41,37,36,.22);display:none;overflow:hidden;flex-direction:column;color:#292524;font:400 15.5px/1.7 "Be Vietnam Pro",system-ui,sans-serif;transition:width .22s ease,height .22s ease}',
      '.cmcb-panel.is-open{display:flex}',
      '.cmcb-panel.is-expanded{width:min(780px,92vw);height:min(840px,88vh)}',
      '.cmcb-header{background:linear-gradient(135deg,#292524,#44403C);color:#FFF9F2;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-shrink:0}',
      '.cmcb-brand{display:flex;align-items:center;gap:11px;min-width:0;flex:1}',
      '.cmcb-avatar{width:42px;height:42px;display:grid;place-items:center;border-radius:13px;background:#E85D2A;font-size:20px;flex:none;box-shadow:0 4px 12px rgba(232,93,42,.35)}',
      '.cmcb-brand-text{min-width:0;flex:1}',
      '.cmcb-title{font-size:16px;font-weight:800;line-height:1.25;color:#FFF9F2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
      '.cmcb-subtitle{font-size:12px;color:#D6D3D1;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
      '.cmcb-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}',
      '.cmcb-icon{width:34px;height:34px;border:1px solid rgba(255,255,255,.16);border-radius:10px;background:rgba(255,255,255,.1);color:#FFFFFF;cursor:pointer;font-size:16px;display:inline-flex;align-items:center;justify-content:center;transition:background-color .18s ease,border-color .18s ease}',
      '.cmcb-icon:hover{background:#E85D2A;border-color:#E85D2A}',
      '.cmcb-statusbar{padding:7px 16px;background:#FFFFFF;border-bottom:1px solid #E7E5E4;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-shrink:0}',
      '.cmcb-status-pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;background:#ECFDF5;color:#2E7D4F;border:1px solid #A7F3D0}',
      '.cmcb-status-pill.is-ollama{background:#FFFBEB;color:#B45309;border-color:#FCD34D}',
      '.cmcb-status-pill.is-sql{background:#FFF7ED;color:#C2410C;border-color:#FED7AA}',
      '.cmcb-status-db{font-size:11.5px;color:#78716C;font-weight:500}',
      '.cmcb-context{padding:8px 16px;background:#FFF1E6;color:#9A3412;font-size:12.5px;font-weight:600;border-bottom:1px solid #FED7AA;flex-shrink:0}',
      '.cmcb-messages{flex:1;min-height:0;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:14px;scroll-behavior:smooth}',
      '.cmcb-row{display:flex;gap:10px;align-items:flex-end;max-width:92%;animation:cmcb-fade-up .18s ease-out}',
      '@keyframes cmcb-fade-up{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}',
      '.cmcb-row.user{align-self:flex-end;flex-direction:row-reverse}',
      '.cmcb-row.bot{align-self:flex-start}',
      '.cmcb-msg-col{min-width:0;max-width:100%}',
      '.cmcb-msg-avatar{width:30px;height:30px;flex:none;border-radius:10px;background:#FFEAD8;display:grid;place-items:center;font-size:15px}',
      '.cmcb-bubble,.cm-chat-bubble{padding:12px 16px;border-radius:16px;background:#FFFFFF;border:1px solid #E7E5E4;box-shadow:0 3px 10px rgba(41,37,36,.05);overflow-wrap:anywhere;font-size:15.5px;line-height:1.7;color:#292524}',
      '.cmcb-row.user .cmcb-bubble,.cm-chat-msg--user .cm-chat-bubble{background:linear-gradient(135deg,#E85D2A,#D94E1F) !important;color:#FFFFFF !important;font-weight:500;border-color:#D94E1F !important;border-bottom-right-radius:4px;box-shadow:0 6px 16px rgba(232,93,42,.24)}',
      '.cmcb-row.user .cmcb-bubble *,.cm-chat-msg--user .cm-chat-bubble *{color:#FFFFFF !important}',
      '.cmcb-row.bot .cmcb-bubble{border-bottom-left-radius:4px}',
      '.cmcb-bubble p{margin:0 0 8px;color:#292524;font-size:15.5px;line-height:1.7}.cmcb-bubble p:last-child{margin-bottom:0}',
      '.cmcb-spacer{height:6px}',
      '.cmcb-bubble h3,.cmcb-bubble h4{margin:8px 0 6px;font-size:16px;font-weight:700;color:#292524;line-height:1.4}',
      '.cmcb-bubble ul,.cmcb-bubble ol{padding-left:22px;margin:8px 0;display:flex;flex-direction:column;gap:6px}',
      '.cmcb-bubble ol li::marker{color:#E85D2A;font-weight:800}',
      '.cmcb-bubble li{color:#292524;line-height:1.7}',
      '.cmcb-bubble code{background:#FFF1E6;border-radius:5px;padding:1px 6px;color:#C2410C;font-size:.9em}',
      '.cmcb-gemini-warning{margin:0 0 8px;padding:11px 13px;border-radius:13px;background:#FFFBEB;border:1px solid #F59E0B;color:#92400E;font-size:13px;line-height:1.55;box-shadow:0 2px 8px rgba(245,158,11,.12)}',
      '.cmcb-gemini-warning strong{display:block;color:#78350F;font-size:13px;margin-bottom:3px}',
      '.cmcb-gemini-warning ul{margin:4px 0 4px 18px;padding:0;font-size:12.5px;color:#92400E}',
      '.cmcb-notice{font-size:12px;color:#78716C;margin:6px 4px 0}',
      '.cmcb-fb{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:7px 2px 0;font-size:12px;color:#78716C}',
      '.cmcb-fb-btn{border:1px solid #E7E5E4;background:#FFFFFF;border-radius:999px;padding:3px 10px;font-size:12px;cursor:pointer;color:#57534E;transition:all .15s}',
      '.cmcb-fb-btn:hover:not(:disabled){border-color:#E85D2A;color:#E85D2A;background:#FFF7ED}',
      '.cmcb-fb-btn.is-voted{background:#E85D2A;border-color:#E85D2A;color:#FFFFFF}',
      '.cmcb-fb-btn:disabled{opacity:.65;cursor:default}',
      '.cmcb-cards{display:grid;gap:8px;margin-top:12px}',
      '.cmcb-card{display:flex;align-items:center;gap:12px;background:#FFF9F2;border:1px solid #FED7AA;border-radius:13px;padding:9px 11px;text-decoration:none;color:#292524;transition:border-color .18s ease,transform .18s ease}',
      '.cmcb-card:hover{border-color:#E85D2A;transform:translateY(-1px)}',
      '.cmcb-card img{width:64px;height:64px;border-radius:10px;object-fit:cover;background:#F5F5F4;flex-shrink:0}',
      '.cmcb-card-info{min-width:0;flex:1}',
      '.cmcb-card-title{display:block;font-weight:700;font-size:14px;color:#292524;line-height:1.35}',
      '.cmcb-card-meta{display:block;font-size:12.5px;color:#78716C;margin-top:2px}',
      '.cmcb-typing{display:flex;gap:5px;padding:6px 4px}.cmcb-typing i{width:7px;height:7px;background:#E85D2A;border-radius:50%;animation:cmcb-bounce .85s infinite alternate}.cmcb-typing i:nth-child(2){animation-delay:.2s}.cmcb-typing i:nth-child(3){animation-delay:.4s}',
      '@keyframes cmcb-bounce{to{transform:translateY(-5px);opacity:.38}}',
      '.cmcb-prompts{display:flex;gap:8px;overflow-x:auto;overflow-y:hidden;padding:10px 16px;background:#FFF5EB;border-top:1px solid #EFE6DE;scrollbar-width:thin;scrollbar-color:#D6D3D1 transparent;scroll-behavior:smooth;flex-shrink:0}',
      '.cmcb-prompts::-webkit-scrollbar{height:4px}.cmcb-prompts::-webkit-scrollbar-thumb{background:#D6D3D1;border-radius:999px}',
      '.cmcb-prompt{flex:0 0 auto;white-space:nowrap;border:1px solid #E7D5C5;border-radius:999px;background:#FFFFFF;color:#44403C;padding:7px 13px;font:600 12.5px/1.2 "Be Vietnam Pro",system-ui,sans-serif;cursor:pointer;transition:border-color .15s ease,color .15s ease,background-color .15s ease}',
      '.cmcb-prompt:hover{border-color:#E85D2A;color:#E85D2A;background:#FFF7ED}',
      '.cmcb-form{display:flex;align-items:flex-end;gap:10px;padding:12px 14px;background:#FFFFFF;border-top:1px solid #E7E5E4;flex-shrink:0}',
      '.cmcb-input{resize:none;min-height:46px;height:46px;max-height:120px;overflow-y:hidden;flex:1;border:1.5px solid #D6D3D1;border-radius:14px;padding:11px 14px;font:400 15px/1.5 "Be Vietnam Pro",system-ui,sans-serif;color:#292524;background:#FFFDFB;outline:0;transition:border-color .15s ease,box-shadow .15s ease}',
      '.cmcb-input:focus{border-color:#E85D2A;background:#FFFFFF;box-shadow:0 0 0 3px rgba(232,93,42,.14)}',
      '.cmcb-send{width:46px;height:46px;border:0;border-radius:14px;background:linear-gradient(135deg,#E85D2A,#D94E1F);color:#FFFFFF;cursor:pointer;font-size:18px;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;transition:opacity .15s ease,transform .15s ease}',
      '.cmcb-send:hover:not(:disabled){transform:translateY(-1px)}.cmcb-send:disabled{opacity:.5;cursor:wait}',
      '.cmcb-empty{color:#44403C;font-size:15px;line-height:1.65;padding:16px 18px;background:#FFFFFF;border:1px solid #E7E5E4;border-radius:16px;max-width:95%;box-shadow:0 2px 8px rgba(41,37,36,.04)}',
      '@media(max-width:639px){#cmChefBotLauncher{right:14px;bottom:14px;padding:12px 15px}.cmcb-launch-label{display:none}.cmcb-panel,.cmcb-panel.is-expanded{left:8px;right:8px;bottom:8px;width:calc(100vw - 16px);max-width:none;height:86dvh;border-radius:18px}#cmcbExpand{display:none}.cmcb-header{padding:12px 14px}.cmcb-messages{padding:12px}.cmcb-status-db{display:none}}',
      '@media(prefers-reduced-motion:reduce){.cmcb-messages,.cmcb-prompts{scroll-behavior:auto}.cmcb-typing i,.cmcb-row{animation:none}.cmcb-panel{transition:none}}'
    ].join('\n');
    document.head.appendChild(node);
  }

  function autoResizeInput(el) {
    if (!el) return;
    el.style.height = '46px';
    var nextH = Math.max(46, Math.min(el.scrollHeight, 120));
    el.style.height = nextH + 'px';
    el.style.overflowY = el.scrollHeight > 120 ? 'auto' : 'hidden';
  }

  function renderQuickPrompts(customSuggestions) {
    var promptBox = document.getElementById('cmcbPrompts');
    if (!promptBox) return;
    if (Array.isArray(customSuggestions) && customSuggestions.length) {
      promptBox.innerHTML = customSuggestions.map(function (txt) {
        return '<button class="cmcb-prompt" type="button" data-prompt="' + esc(txt) + '">✨ ' + esc(txt) + '</button>';
      }).join('');
      promptBox.scrollLeft = 0;
      return;
    }
    var baseList = state.recipeId ? RECIPE_PROMPTS : QUICK_PROMPTS;
    promptBox.innerHTML = baseList.map(function (item) {
      return '<button class="cmcb-prompt" type="button" data-prompt="' + esc(item[2]) + '">' + item[0] + ' ' + esc(item[1]) + '</button>';
    }).join('');
  }

  function toggleExpanded() {
    state.expanded = !state.expanded;
    var panel = document.getElementById('cmChefBotPanel');
    var btn = document.getElementById('cmcbExpand');
    if (panel) panel.classList.toggle('is-expanded', state.expanded);
    if (btn) {
      btn.textContent = state.expanded ? '⤡' : '⤢';
      btn.title = state.expanded ? 'Thu gọn khung chat' : 'Phóng to khung chat';
      btn.setAttribute('aria-label', btn.title);
    }
  }

  function build() {
    if (document.getElementById('cmChefBotLauncher')) return;
    styles();
    state.recipeId = detectRecipeId();
    var launcher = document.createElement('button');
    launcher.id = 'cmChefBotLauncher';
    launcher.type = 'button';
    launcher.setAttribute('aria-label', 'Mở Đầu bếp CookMate AI');
    launcher.innerHTML = '<span aria-hidden="true">🍳</span> <span class="cmcb-launch-label">Đầu bếp AI</span>';

    var panel = document.createElement('section');
    panel.id = 'cmChefBotPanel';
    panel.className = 'cmcb-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Đầu bếp CookMate AI');

    var recipeTitle = '';
    if (state.recipeId && typeof CookMateStorage !== 'undefined' && CookMateStorage.getRecipeById) {
      var foundR = CookMateStorage.getRecipeById(state.recipeId);
      if (foundR && foundR.title) recipeTitle = ' · ' + esc(foundR.title);
    }
    var context = state.recipeId ? '<div class="cmcb-context">🍲 Đang xem công thức #' + state.recipeId + recipeTitle + '</div>' : '';

    panel.innerHTML =
      '<header class="cmcb-header">' +
        '<div class="cmcb-brand">' +
          '<div class="cmcb-avatar" aria-hidden="true">🍳</div>' +
          '<div class="cmcb-brand-text">' +
            '<div class="cmcb-title">Đầu bếp CookMate AI</div>' +
            '<div class="cmcb-subtitle">Trợ lý Ẩm thực &amp; Dinh dưỡng 300 món Việt</div>' +
          '</div>' +
        '</div>' +
        '<div class="cmcb-actions">' +
          '<button class="cmcb-icon" type="button" id="cmcbExpand" title="Phóng to khung chat" aria-label="Phóng to khung chat">⤢</button>' +
          '<button class="cmcb-icon" type="button" id="cmcbReset" title="Làm mới cuộc trò chuyện" aria-label="Làm mới cuộc trò chuyện">↻</button>' +
          '<button class="cmcb-icon" type="button" id="cmcbClose" title="Đóng" aria-label="Đóng">×</button>' +
        '</div>' +
      '</header>' +
      '<div class="cmcb-statusbar" id="cmcbStatusBar">' +
        '<span class="cmcb-status-pill is-gemini" id="cmcbStatusPill">🟢 Gemini 2.5 Flash · Sẵn sàng</span>' +
        '<span class="cmcb-status-db">Kho 300 món MySQL</span>' +
      '</div>' +
      context +
      '<div class="cmcb-messages" id="cmcbMessages" aria-live="polite">' +
        '<div class="cmcb-empty">Xin chào! Mình là <strong>Đầu bếp CookMate AI</strong> — đối chiếu trực tiếp từ kho <strong>300 món ăn chuẩn định lượng &amp; dinh dưỡng</strong>. Hãy hỏi mình về nguyên liệu sẵn có, công thức vùng miền hoặc mẹo đứng bếp nhé!</div>' +
      '</div>' +
      '<div class="cmcb-prompts" id="cmcbPrompts"></div>' +
      '<form class="cmcb-form" id="cmcbForm">' +
        '<textarea class="cmcb-input" id="cmcbInput" maxlength="2000" rows="1" aria-label="Câu hỏi cho Đầu bếp CookMate AI" placeholder="Nhập nguyên liệu hoặc món ăn cần hỏi (Enter gửi, Shift+Enter xuống dòng)..."></textarea>' +
        '<button class="cmcb-send" id="cmcbSend" type="submit" aria-label="Gửi câu hỏi">➤</button>' +
      '</form>';

    document.body.appendChild(launcher);
    document.body.appendChild(panel);

    var promptBox = document.getElementById('cmcbPrompts');
    var inputEl = document.getElementById('cmcbInput');
    renderQuickPrompts();

    launcher.addEventListener('click', function () { setOpen(!state.open); });
    document.getElementById('cmcbExpand').addEventListener('click', toggleExpanded);
    document.getElementById('cmcbClose').addEventListener('click', function () { setOpen(false); });
    document.getElementById('cmcbReset').addEventListener('click', resetConversation);
    document.getElementById('cmcbForm').addEventListener('submit', function (event) { event.preventDefault(); sendCurrent(); });

    inputEl.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendCurrent();
      }
    });
    inputEl.addEventListener('input', function () { autoResizeInput(this); });

    promptBox.addEventListener('click', function (event) {
      var button = event.target.closest('[data-prompt]');
      if (button) sendMessage(button.getAttribute('data-prompt'));
    });
    promptBox.addEventListener('wheel', function (event) {
      if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
        event.preventDefault();
        promptBox.scrollLeft += event.deltaY;
      }
    }, { passive: false });

    window.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && state.open) setOpen(false);
    });
    api('/api/auth/csrf').catch(function () {});
  }

  function setOpen(value) {
    state.open = Boolean(value);
    var panel = document.getElementById('cmChefBotPanel');
    var launcher = document.getElementById('cmChefBotLauncher');
    if (panel) panel.classList.toggle('is-open', state.open);
    if (launcher) launcher.classList.toggle('is-hidden', state.open);
    if (state.open) {
      var inp = document.getElementById('cmcbInput');
      if (inp) inp.focus();
    }
  }

  function buildGeminiWarningHtml(diag) {
    if (!diag || !diag.geminiFailed) return '';
    var attempts = Array.isArray(diag.attemptedModels) ? diag.attemptedModels : [];
    var itemsHtml = attempts.filter(function (a) { return a && a.status === 'failed'; }).map(function (a) {
      var codeTxt = a.httpCode ? ' (HTTP ' + esc(a.httpCode) + ')' : '';
      return '<li><code>' + esc(a.model || 'gemini') + '</code>' + codeTxt + ': ' + esc(a.reasonVi || 'Không khả dụng') + '</li>';
    }).join('');
    var summary = diag.userWarningVi || 'Không gọi được API Gemini, hệ thống đã chuyển sang AI dự phòng cục bộ.';
    return '<div class="cmcb-gemini-warning" role="status">' +
      '<strong>⚠️ Thông báo chuyển đổi mô hình AI dự phòng</strong>' +
      (itemsHtml ? '<ul>' + itemsHtml + '</ul>' : '') +
      '<div>' + esc(summary) + '</div>' +
    '</div>';
  }

  function appendMessage(kind, text, data) {
    var area = document.getElementById('cmcbMessages');
    var empty = area.querySelector('.cmcb-empty');
    if (empty) empty.remove();

    var row = document.createElement('div');
    row.className = 'cmcb-row ' + kind + (kind === 'user' ? ' cm-chat-msg--user' : ' cm-chat-msg--bot');
    var avatar = kind === 'bot' ? '<span class="cmcb-msg-avatar" aria-hidden="true">🍳</span>' : '';

    var diag = data && data.aiDiagnostics ? data.aiDiagnostics : null;
    if (kind === 'bot' && diag) updateStatusBar(diag);

    var warningBanner = kind === 'bot' ? buildGeminiWarningHtml(diag) : '';
    var cards = '';
    if (kind === 'bot' && data && Array.isArray(data.recipes) && data.recipes.length) {
      var basePath = (typeof getBasePath === 'function') ? getBasePath() : './';
      cards = '<div class="cmcb-cards">' + data.recipes.map(function (recipe) {
        var imgSrc = (typeof getImageUrl === 'function') ? getImageUrl(recipe.image) : recipe.image;
        var image = imgSrc
          ? '<img src="' + esc(imgSrc) + '" alt="' + esc(recipe.title || '') + '" onerror="if(typeof handleImageError===\'function\')handleImageError(this)">'
          : '<span class="cmcb-msg-avatar">🍲</span>';
        var nutrition = Number(recipe.calories) > 0 ? esc(recipe.calories) + ' kcal' : 'Chuẩn định lượng';
        var timeMins = Number(recipe.totalTime || recipe.cookTime || 0);
        var timeTxt = timeMins > 0 ? ' · ' + esc(timeMins) + ' phút' : '';
        return '<a class="cmcb-card" href="' + esc(basePath) + 'pages/recipe-detail.html?id=' + encodeURIComponent(recipe.id) + '">' +
          image +
          '<span class="cmcb-card-info"><span class="cmcb-card-title">' + esc(recipe.title) + '</span>' +
          '<span class="cmcb-card-meta">' + esc(recipe.servings || 4) + ' người · ' + nutrition + timeTxt + '</span></span></a>';
      }).join('') + '</div>';
    }

    var notice = (kind === 'bot' && data && data.notice && !(diag && diag.geminiFailed))
      ? '<div class="cmcb-notice">' + esc(data.notice) + '</div>'
      : '';
    var feedback = '';
    if (kind === 'bot' && data && data.qa_id) {
      feedback = '<div class="cmcb-fb" data-qa-id="' + esc(data.qa_id) + '"><span>Đánh giá câu trả lời:</span>' +
        '<button type="button" class="cmcb-fb-btn" data-rating="1" aria-label="Câu trả lời hữu ích">👍 Hữu ích</button>' +
        '<button type="button" class="cmcb-fb-btn" data-rating="-1" aria-label="Câu trả lời chưa đạt">👎 Chưa đạt</button></div>';
    }

    var bodyHtml = kind === 'bot' ? markdown(text) : '<p>' + esc(text).replace(/\n/g, '<br>') + '</p>';
    row.innerHTML = avatar + '<div class="cmcb-msg-col">' + warningBanner + '<div class="cmcb-bubble cm-chat-bubble">' + bodyHtml + cards + '</div>' + notice + feedback + '</div>';

    if (kind === 'bot' && data && data.qa_id) {
      var fbWrap = row.querySelector('.cmcb-fb');
      if (fbWrap) {
        fbWrap.addEventListener('click', function (ev) {
          var btn = ev.target.closest('.cmcb-fb-btn');
          if (!btn || btn.disabled) return;
          var rating = Number(btn.getAttribute('data-rating'));
          var qaId = Number(fbWrap.getAttribute('data-qa-id'));
          fbWrap.querySelectorAll('.cmcb-fb-btn').forEach(function (b) { b.disabled = true; });
          btn.classList.add('is-voted');
          api('/api/chatbot/feedback', { method: 'POST', body: JSON.stringify({ qa_id: qaId, rating: rating, session_id: state.sessionId }) })
            .then(function () {
              var note = document.createElement('span');
              note.textContent = rating > 0 ? 'Cảm ơn bạn!' : 'Đã ghi nhận góp ý.';
              fbWrap.appendChild(note);
            })
            .catch(function () {});
        });
      }
    }

    area.appendChild(row);
    area.scrollTop = area.scrollHeight;
    return row;
  }

  function typing(show) {
    var existing = document.getElementById('cmcbTyping');
    if (show && !existing) {
      var area = document.getElementById('cmcbMessages');
      var row = document.createElement('div');
      row.id = 'cmcbTyping';
      row.className = 'cmcb-row bot';
      row.innerHTML = '<span class="cmcb-msg-avatar" aria-hidden="true">🍳</span><div class="cmcb-bubble"><span class="cmcb-typing" aria-label="ChefBot đang trả lời"><i></i><i></i><i></i></span></div>';
      area.appendChild(row);
      area.scrollTop = area.scrollHeight;
    }
    if (!show && existing) existing.remove();
  }

  function setBusy(value) {
    state.busy = Boolean(value);
    var button = document.getElementById('cmcbSend');
    var input = document.getElementById('cmcbInput');
    if (button) button.disabled = state.busy;
    if (input) input.disabled = state.busy;
    typing(state.busy);
  }

  function ensureSession() {
    if (state.sessionId) return Promise.resolve(state.sessionId);
    return api('/api/auth/csrf').catch(function () { return {}; }).then(function () {
      return api('/api/chatbot/sessions', { method: 'POST', body: JSON.stringify({ recipe_id: state.recipeId }) });
    }).then(function (data) {
      state.sessionId = data.session_id;
      return state.sessionId;
    });
  }

  function sendCurrent() {
    var input = document.getElementById('cmcbInput');
    var text = input.value.trim();
    if (!text || state.busy) return;
    input.value = '';
    autoResizeInput(input);
    sendMessage(text);
  }

  function sendMessage(text) {
    if (!text || state.busy) return;
    appendMessage('user', text);
    setBusy(true);
    ensureSession().then(function (sessionId) {
      return api('/api/chatbot', { method: 'POST', body: JSON.stringify({ message: text, session_id: sessionId, recipe_id: state.recipeId }) });
    }).then(function (data) {
      appendMessage('bot', data.reply || 'Mình chưa có câu trả lời phù hợp.', data);
      if (Array.isArray(data.suggestions) && data.suggestions.length) renderQuickPrompts(data.suggestions);
    }).catch(function (error) {
      appendMessage('bot', error.message || 'Không kết nối được tới CookMate. Hãy kiểm tra Backend rồi thử lại.', error.payload || null);
    }).finally(function () {
      setBusy(false);
      var inp = document.getElementById('cmcbInput');
      if (inp) inp.focus();
    });
  }

  function resetConversation() {
    var old = state.sessionId;
    state.sessionId = '';
    var area = document.getElementById('cmcbMessages');
    if (area) {
      area.innerHTML = '<div class="cmcb-empty">Đã làm mới cuộc trò chuyện. Hãy hỏi Đầu bếp CookMate AI về món ăn, nguyên liệu hoặc dinh dưỡng nhé!</div>';
    }
    updateStatusBar(null);
    renderQuickPrompts();
    if (old) api('/api/chatbot/sessions/' + encodeURIComponent(old), { method: 'DELETE' }).catch(function () {});
  }

  window.CookMateChefBot = {
    open: function () { setOpen(true); },
    close: function () { setOpen(false); },
    toggleExpand: toggleExpanded,
    renderDiagnosticMessage: function (replyText, diagObj) {
      return appendMessage('bot', replyText, { aiDiagnostics: diagObj });
    }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
