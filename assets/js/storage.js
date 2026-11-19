// MySQL-backed API store. Browser storage is reserved for visual preferences only.
var CookMateStorage = (function () {
  'use strict';

  var API_BASE = String(window.COOKMATE_API_BASE_URL || '').replace(/\/$/, '');
  var state = {
    online: false, user: null, csrfToken: '', recipes: [], myRecipes: [], pendingRecipes: [], adminRecipes: [],
    categories: [], ingredients: [], comments: [], users: [], favorites: [], statistics: {}
  };
  var UI_KEYS = { THEME: 'cookmate_theme' };

  function isMustChangePassword(user) {
    return Boolean(user && (user.must_change_password || user.mustChangePassword));
  }

  function escapeText(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function isHttpMode() {
    return typeof window !== 'undefined' && /^(https?:)$/.test(window.location.protocol);
  }

  function notify(name, detail) {
    try { window.dispatchEvent(new CustomEvent(name, { detail: detail || {} })); } catch (e) {}
  }

  function request(method, path, body) {
    if (!isHttpMode()) return Promise.reject(new Error('CookMate requires the Flask backend for account and data changes.'));
    var tokenPromise = state.csrfToken ? Promise.resolve(state.csrfToken) : fetch(API_BASE + '/api/auth/csrf', { credentials: 'include' })
      .then(function (res) { if (!res.ok) throw new Error('Backend unavailable.'); return res.json(); })
      .then(function (data) { state.csrfToken = data.csrfToken || ''; return state.csrfToken; });
    return tokenPromise.then(function (token) {
      var isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
      var headers = isFormData ? {} : { 'Content-Type': 'application/json' };
      if (token) headers['X-CSRF-Token'] = token;
      return fetch(API_BASE + path, {
        method: method, headers: headers, credentials: 'include',
        body: body == null || method === 'GET' ? undefined : (isFormData ? body : JSON.stringify(body)),
        signal: AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined
      });
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (data.csrfToken) state.csrfToken = data.csrfToken;
        if (!response.ok) {
          var err = new Error(data.message || data.error || 'Không thể hoàn tất thao tác.');
          err.code = data.error || '';
          throw err;
        }
        state.online = true;
        return data;
      });
    }).catch(function (error) {
      if (/Failed to fetch|NetworkError|Backend unavailable|timed out/i.test(error.message || '')) {
        state.online = false;
        notify('cookmate:backend-unavailable', { message: 'Không kết nối được Backend. Các thay đổi chưa được lưu.' });
      }
      throw error;
    });
  }

  function buildRecipeRequestBody(recipe) {
    if (typeof FormData !== 'undefined' && recipe instanceof FormData) return recipe;
    if (recipe && recipe.imageFile) {
      var fd = new FormData();
      fd.append('image_file', recipe.imageFile);
      var copy = Object.assign({}, recipe);
      delete copy.imageFile;
      copy.image = '';
      copy.imageUrl = '';
      copy.image_url = '';
      fd.append('payload', JSON.stringify(copy));
      return fd;
    }
    return recipe;
  }

  function loadAdminData() {
    if (!state.user || state.user.role !== 'admin') return Promise.resolve();
    return Promise.all([
      request('GET', '/api/admin/pending-recipes').then(function (data) { state.pendingRecipes = data.recipes || []; }),
      request('GET', '/api/admin/recipes').then(function (data) { state.adminRecipes = data.recipes || []; }),
      request('GET', '/api/admin/users').then(function (data) { state.users = data.users || []; })
    ]).catch(function (error) {
      notify('cookmate:backend-unavailable', { message: error.message || 'Không thể tải dữ liệu quản trị.' });
    });
  }

  function mountMandatoryPasswordChangeOverlay() {
    if (typeof document === 'undefined') return;
    var mount = function () {
      if (!document.body || !isMustChangePassword(state.user)) return;
      document.documentElement.style.visibility = '';
      document.body.style.overflow = 'hidden';

      var existing = document.getElementById('mandatoryPasswordChangeOverlay');
      if (existing) return;

      var overlay = document.createElement('div');
      overlay.id = 'mandatoryPasswordChangeOverlay';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-labelledby', 'forceChangePwTitle');
      overlay.style.cssText =
        'position:fixed;inset:0;z-index:20050;display:flex;align-items:center;justify-content:center;' +
        'padding:20px;background:radial-gradient(circle at 50% 25%, #FFF7ED 0%, #FFF9F2 55%, #FAF3EA 100%);' +
        'font-family:"Be Vietnam Pro",system-ui,sans-serif;overflow-y:auto;box-sizing:border-box;';

      overlay.innerHTML =
        '<div style="width:100%;max-width:440px;background:#FFFFFF;border-radius:24px;border:1px solid #E7E5E4;' +
        'box-shadow:0 20px 44px rgba(120,60,20,0.12);padding:28px 30px;position:relative;overflow:hidden;box-sizing:border-box;">' +
          '<div style="position:absolute;top:0;left:0;right:0;height:4px;background:linear-gradient(90deg,#E85D2A,#F97316,#2E7D4F);"></div>' +
          '<div style="width:52px;height:52px;border-radius:50%;background:#FFF7ED;border:1.5px solid #FED7AA;color:#E85D2A;' +
          'display:flex;align-items:center;justify-content:center;font-size:22px;margin:0 auto 12px;">' +
            '<i class="fa-solid fa-shield-halved"></i>' +
          '</div>' +
          '<h2 id="forceChangePwTitle" style="font-size:21px;font-weight:800;color:#1F2937;text-align:center;margin:0 0 6px;">Đổi mật khẩu để tiếp tục</h2>' +
          '<p style="font-size:13.5px;color:#78716C;text-align:center;margin:0 0 18px;line-height:1.5;">' +
            'Bạn đang sử dụng mật khẩu tạm thời được cấp khi khôi phục tài khoản. Vui lòng thiết lập mật khẩu mới để bảo vệ tài khoản.' +
          '</p>' +
          '<form id="forceChangePasswordForm" novalidate>' +
            '<div style="margin-bottom:14px;">' +
              '<label for="forceNewPassword" style="display:block;font-size:12px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px;">' +
                '<i class="fa-solid fa-lock"></i> Mật khẩu mới' +
              '</label>' +
              '<div style="position:relative;display:flex;align-items:center;">' +
                '<input type="password" id="forceNewPassword" class="form-input" placeholder="Nhập mật khẩu mới (tối thiểu 8 ký tự)" autocomplete="new-password" required ' +
                'style="width:100%;padding:11px 40px 11px 14px;border:1.5px solid #E7E5E4;border-radius:10px;background:#FAFAFA;font-size:14px;color:#1F2937;outline:none;box-sizing:border-box;">' +
                '<button type="button" id="toggleForceNewPw" aria-label="Hiện mật khẩu" ' +
                'style="position:absolute;right:8px;width:32px;height:32px;border-radius:50%;border:none;background:transparent;color:#78716C;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">' +
                  '<i class="fa-regular fa-eye"></i>' +
                '</button>' +
              '</div>' +
            '</div>' +
            '<div style="margin-bottom:12px;">' +
              '<label for="forceConfirmPassword" style="display:block;font-size:12px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:0.04em;margin-bottom:6px;">' +
                '<i class="fa-solid fa-check-double"></i> Xác nhận mật khẩu mới' +
              '</label>' +
              '<div style="position:relative;display:flex;align-items:center;">' +
                '<input type="password" id="forceConfirmPassword" class="form-input" placeholder="Nhập lại mật khẩu mới" autocomplete="new-password" required ' +
                'style="width:100%;padding:11px 40px 11px 14px;border:1.5px solid #E7E5E4;border-radius:10px;background:#FAFAFA;font-size:14px;color:#1F2937;outline:none;box-sizing:border-box;">' +
                '<button type="button" id="toggleForceConfirmPw" aria-label="Hiện mật khẩu" ' +
                'style="position:absolute;right:8px;width:32px;height:32px;border-radius:50%;border:none;background:transparent;color:#78716C;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;">' +
                  '<i class="fa-regular fa-eye"></i>' +
                '</button>' +
              '</div>' +
            '</div>' +
            '<div id="forcePasswordConditions" style="margin-bottom:14px;padding:10px 12px;border-radius:10px;background:#FFF7ED;border:1px solid #FED7AA;font-size:12.5px;color:#78716C;display:flex;flex-direction:column;gap:5px;">' +
              '<div id="forceCondLength" style="display:flex;align-items:center;gap:7px;"><i class="fa-regular fa-circle"></i> <span>Tối thiểu 8 ký tự</span></div>' +
              '<div id="forceCondMix" style="display:flex;align-items:center;gap:7px;"><i class="fa-regular fa-circle"></i> <span>Nên kết hợp chữ cái và chữ số / ký tự đặc biệt</span></div>' +
              '<div id="forceCondMatch" style="display:flex;align-items:center;gap:7px;"><i class="fa-regular fa-circle"></i> <span>Mật khẩu xác nhận trùng khớp</span></div>' +
            '</div>' +
            '<div id="forceChangePasswordError" class="auth-error-msg form-error" role="alert" ' +
            'style="display:none;margin-bottom:12px;padding:10px 12px;border-radius:8px;background:#FEF2F2;border:1px solid #FECACA;color:#DC2626;font-size:13px;font-weight:500;"></div>' +
            '<button type="submit" id="forceChangePasswordSubmitBtn" class="auth-action-btn" ' +
            'style="width:100%;padding:12px 18px;border-radius:10px;background:linear-gradient(135deg,#E85D2A,#F97316);color:#FFFFFF;border:none;font-size:14.5px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:0 4px 12px rgba(232,93,42,0.28);">' +
              '<i class="fa-solid fa-key"></i> <span>Xác nhận đổi mật khẩu</span>' +
            '</button>' +
            '<div style="margin-top:14px;text-align:center;">' +
              '<button type="button" id="forceChangeLogoutBtn" style="background:none;border:none;color:#78716C;font-size:12.5px;font-weight:600;cursor:pointer;text-decoration:underline;">' +
                'Đăng xuất khỏi tài khoản này' +
              '</button>' +
            '</div>' +
          '</form>' +
        '</div>';

      document.body.appendChild(overlay);

      var newInp = overlay.querySelector('#forceNewPassword');
      var confInp = overlay.querySelector('#forceConfirmPassword');
      var toggleNew = overlay.querySelector('#toggleForceNewPw');
      var toggleConf = overlay.querySelector('#toggleForceConfirmPw');
      var condLen = overlay.querySelector('#forceCondLength');
      var condMix = overlay.querySelector('#forceCondMix');
      var condMatch = overlay.querySelector('#forceCondMatch');
      var errEl = overlay.querySelector('#forceChangePasswordError');
      var submitBtn = overlay.querySelector('#forceChangePasswordSubmitBtn');
      var logoutBtn = overlay.querySelector('#forceChangeLogoutBtn');
      var form = overlay.querySelector('#forceChangePasswordForm');

      function wireToggle(btn, inp) {
        if (!btn || !inp) return;
        btn.addEventListener('click', function (ev) {
          ev.preventDefault();
          var isPw = inp.type === 'password';
          inp.type = isPw ? 'text' : 'password';
          var icon = btn.querySelector('i');
          if (icon) icon.className = isPw ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye';
          btn.setAttribute('aria-label', isPw ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
        });
      }

      wireToggle(toggleNew, newInp);
      wireToggle(toggleConf, confInp);

      function updateConditionRow(el, ok) {
        if (!el) return;
        var icon = el.querySelector('i');
        el.style.color = ok ? '#16A34A' : '#78716C';
        el.style.fontWeight = ok ? '600' : '400';
        if (icon) icon.className = ok ? 'fa-solid fa-circle-check' : 'fa-regular fa-circle';
      }

      function refreshConditions() {
        var v1 = newInp ? newInp.value : '';
        var v2 = confInp ? confInp.value : '';
        var lenOk = v1.trim().length >= 8;
        var mixOk = /[A-Za-z]/.test(v1) && (/[0-9]/.test(v1) || /[^A-Za-z0-9]/.test(v1));
        var matchOk = lenOk && v2.length > 0 && v1 === v2;
        updateConditionRow(condLen, lenOk);
        updateConditionRow(condMix, mixOk);
        updateConditionRow(condMatch, matchOk);
      }

      if (newInp) newInp.addEventListener('input', refreshConditions);
      if (confInp) confInp.addEventListener('input', refreshConditions);

      function showErr(msg) {
        if (errEl) {
          errEl.textContent = msg;
          errEl.classList.add('is-visible');
          errEl.style.display = 'block';
        }
      }

      function clearErr() {
        if (errEl) {
          errEl.textContent = '';
          errEl.classList.remove('is-visible');
          errEl.style.display = 'none';
        }
      }

      if (logoutBtn) {
        logoutBtn.addEventListener('click', function (ev) {
          ev.preventDefault();
          store.logout().catch(function () {}).finally(function () {
            var base = typeof getBasePath === 'function' ? getBasePath() : '/';
            window.location.href = base + 'pages/auth/login.html';
          });
        });
      }

      if (form) {
        form.addEventListener('submit', function (ev) {
          ev.preventDefault();
          clearErr();
          var v1 = newInp ? newInp.value : '';
          var v2 = confInp ? confInp.value : '';

          if (!v1 || !v1.trim()) {
            showErr('Vui lòng nhập mật khẩu mới.');
            return;
          }
          if (!v2 || !v2.trim()) {
            showErr('Vui lòng xác nhận mật khẩu mới.');
            return;
          }
          if (v1.length < 8) {
            showErr('Mật khẩu mới phải có ít nhất 8 ký tự.');
            return;
          }
          if (v1 !== v2) {
            showErr('Mật khẩu xác nhận không khớp.');
            return;
          }

          if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Đang cập nhật mật khẩu...</span>';
          }

          store.forceChangePassword(v1, v2).then(function (data) {
            if (overlay.parentElement) overlay.remove();
            document.body.style.overflow = '';
            try {
              sessionStorage.setItem('cookmate_flash_toast', (data && data.message) || 'Mật khẩu đã được cập nhật thành công');
            } catch (e) {}
            if (typeof CookMateUI !== 'undefined' && typeof CookMateUI.showToast === 'function') {
              CookMateUI.showToast((data && data.message) || 'Mật khẩu đã được cập nhật thành công', 'success', 4000);
            }
            var base = typeof getBasePath === 'function' ? getBasePath() : '../../';
            var targetUrl = (state.user && state.user.role === 'admin')
              ? base + 'pages/admin/index.html'
              : base + 'index.html';
            setTimeout(function () {
              window.location.href = targetUrl;
            }, 350);
          }).catch(function (err) {
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.innerHTML = '<i class="fa-solid fa-key"></i> <span>Xác nhận đổi mật khẩu</span>';
            }
            var msg = (err && err.message) || 'Không thể cập nhật mật khẩu. Vui lòng thử lại.';
            showErr(msg);
            if (typeof CookMateUI !== 'undefined' && typeof CookMateUI.showToast === 'function') {
              CookMateUI.showToast(msg, 'error');
            }
          });
        });
      }

      if (newInp) newInp.focus();
    };

    if (document.body) {
      mount();
    } else {
      window.addEventListener('DOMContentLoaded', mount, { once: true });
    }
  }

  function initialize() {
    if (!isHttpMode()) return Promise.resolve(false);
    // Establish the signed session cookie and CSRF token before parallel bootstrap
    // reads, so simultaneous first requests cannot overwrite each other's token.
    return fetch(API_BASE + '/api/auth/csrf', { credentials: 'include', signal: AbortSignal.timeout ? AbortSignal.timeout(10000) : undefined })
      .then(function (response) {
        if (!response.ok) throw new Error('Backend unavailable.');
        return response.json();
      })
      .then(function (csrf) {
        state.csrfToken = csrf.csrfToken || '';
        return request('GET', '/api/auth/me');
      })
      .then(function (auth) {
        auth = auth || {};
        state.online = true;
        state.user = auth.user || null;
        state.csrfToken = auth.csrfToken || state.csrfToken;

        if (isMustChangePassword(state.user)) {
          mountMandatoryPasswordChangeOverlay();
          return true;
        }

        return request('GET', '/api/bootstrap').then(function (payload) {
          payload = payload || {};
          state.recipes = payload.recipes || [];
          state.categories = payload.categories || [];
          state.ingredients = payload.ingredients || [];
          state.comments = payload.comments || [];
          state.favorites = payload.favorites || [];
          state.statistics = payload.statistics || {};
          var privateLoad = state.user ? request('GET', '/api/recipes/my').then(function (data) { state.myRecipes = data.recipes || []; }) : Promise.resolve();
          return privateLoad.then(loadAdminData).then(function () {
            notify('cookmate:data-ready', {});
            return true;
          });
        });
      }).catch(function (error) {
      state.online = false;
      state.user = null;
      state.recipes = []; state.myRecipes = []; state.pendingRecipes = []; state.adminRecipes = []; state.categories = []; state.ingredients = [];
      state.comments = []; state.users = []; state.favorites = [];
      notify('cookmate:backend-unavailable', { message: 'CookMate Backend/MySQL is unavailable. No changes will be saved.' });
      return false;
    });
  }

  var ready = initialize();

  // Existing pages use synchronous DOMContentLoaded setup. Hold those initializers until
  // the first MySQL bootstrap finishes so the data getters read the remote snapshot.
  if (typeof document !== 'undefined') {
    var nativeDocumentAdd = document.addEventListener.bind(document);
    document.addEventListener = function (type, listener, options) {
      if (type === 'DOMContentLoaded' && typeof listener === 'function') {
        var deferred = function (event) {
          ready.then(function () {
            if (isMustChangePassword(state.user)) {
              mountMandatoryPasswordChangeOverlay();
              var path = (window.location && window.location.pathname) || '';
              if (path.indexOf('login.html') === -1) {
                return;
              }
            }
            listener.call(document, event);
            try {
              var flashMsg = sessionStorage.getItem('cookmate_flash_toast');
              if (flashMsg && typeof CookMateUI !== 'undefined' && typeof CookMateUI.showToast === 'function') {
                sessionStorage.removeItem('cookmate_flash_toast');
                CookMateUI.showToast(flashMsg, 'success', 4000);
              }
            } catch (e) {}
          });
        };
        return nativeDocumentAdd(type, deferred, options);
      }
      return nativeDocumentAdd(type, listener, options);
    };
  }

  function refreshMyRecipes() {
    if (!state.user) return Promise.resolve([]);
    return request('GET', '/api/recipes/my').then(function (data) { state.myRecipes=data.recipes||[]; notify('cookmate:data-ready',{}); return state.myRecipes; });
  }
  function refreshFavorites() {
    if (!state.user) { state.favorites=[]; return Promise.resolve([]); }
    return request('GET','/api/favorites').then(function(data){state.favorites=data.favorites||[];return state.favorites;});
  }

  var store = {
    KEYS: { USER:'cookmate_current_user',ADMIN_SESSION:'cookmate_admin_session',FAVORITES:'cookmate_favorites',USER_RECIPES:'cookmate_user_recipes',DELETED_RECIPES:'cookmate_deleted_recipes',USER_COMMENTS:'cookmate_user_comments',DELETED_COMMENTS:'cookmate_deleted_comments',REGISTERED_USERS:'cookmate_registered_users',USER_STATUS_OVERRIDES:'cookmate_user_status_overrides',ADMIN_CATEGORIES:'cookmate_admin_categories',ADMIN_INGREDIENTS:'cookmate_admin_ingredients',THEME:UI_KEYS.THEME },
    ready: ready,
    isHttpMode: isHttpMode,
    isBackendOnline: function(){return state.online;},
    _apiRequest: request,
    get: function (key) {
      if (!UI_KEYS[key] && key !== UI_KEYS.THEME) return null;
      try { var value=localStorage.getItem(key);return value?JSON.parse(value):null; } catch(e){return null;}
    },
    set: function (key, value) {
      if (key !== UI_KEYS.THEME) return false;
      try { localStorage.setItem(key,JSON.stringify(value));return true; } catch(e){return false;}
    },
    remove: function (key) {
      if (key !== UI_KEYS.THEME) return;
      try { localStorage.removeItem(key); } catch(e) {}
    },
    getCurrentUser: function(){return state.user;},
    setCurrentUser: function(user){state.user=user||null;notify('cookmate:auth-changed',{});return true;},
    clearCurrentUser: function(){state.user=null;state.favorites=[];request('POST','/api/auth/logout',{}).catch(function(){});notify('cookmate:auth-changed',{});},
    getAdminSession: function(){return state.user&&state.user.role==='admin'?state.user:null;},
    setAdminSession: function(){return false;},
    clearAdminSession: function(){},
    isAdminSessionValid: function(){return Boolean(state.user&&state.user.role==='admin');},
    isLoggedIn: function(){return Boolean(state.user);},
    isAdmin: function(){return Boolean(state.user&&state.user.role==='admin');},
    mustChangePassword: function(){return isMustChangePassword(state.user);},
    enforceMandatoryPasswordChange: mountMandatoryPasswordChangeOverlay,
    login: function(email,password){
      return request('POST','/api/auth/login',{email:email,password:password}).then(function(data){
        state.user=data.user;
        state.csrfToken=data.csrfToken||state.csrfToken;
        notify('cookmate:auth-changed',{});
        if(isMustChangePassword(state.user)){
          mountMandatoryPasswordChangeOverlay();
        }
        return data;
      });
    },
    logout: function(){return request('POST','/api/auth/logout',{}).then(function(data){state.user=null;state.favorites=[];notify('cookmate:auth-changed',{});return data;});},
    requestPasswordResetOtp: function(email){return request('POST','/api/auth/forgot-password',{email:email});},
    verifyPasswordResetOtp: function(email,otp){return request('POST','/api/auth/verify-otp',{email:email,otp:otp});},
    resendPasswordResetOtp: function(email){return request('POST','/api/auth/resend-otp',{email:email});},
    changePassword: function(currentPassword,newPassword,confirmPassword){
      return request('POST','/api/auth/change-password',{
        current_password:currentPassword,
        new_password:newPassword,
        confirm_password:confirmPassword
      }).then(function(data){
        if(data&&data.user)state.user=data.user;
        else if(state.user){state.user.must_change_password=false;state.user.mustChangePassword=false;}
        return data;
      });
    },
    forceChangePassword: function(newPassword,confirmPassword){
      return request('POST','/api/auth/force-change-password',{
        new_password:newPassword,
        confirm_password:confirmPassword
      }).then(function(data){
        if(data&&data.user)state.user=data.user;
        else if(state.user){state.user.must_change_password=false;state.user.mustChangePassword=false;}
        notify('cookmate:auth-changed',{});
        return data;
      });
    },
    getFavorites: function(){return state.favorites.slice();},
    toggleFavorite: function(recipeId){
      if(!state.user)return Promise.reject(new Error('Vui lòng đăng nhập để lưu yêu thích.'));
      return request('POST','/api/favorites/toggle',{recipeId:Number(recipeId)}).then(function(result){return refreshFavorites().then(function(){return result;});});
    },
    isFavorite: function(recipeId){return state.favorites.some(function(id){return String(id)===String(recipeId);});},
    getUserRecipes: function(){return state.myRecipes.slice();},
    getDeletedRecipeIds: function(){return [];},
    addUserRecipe: function(recipe){
      if(!state.user)return Promise.reject(new Error('Vui lòng đăng nhập trước khi đăng công thức.'));
      return request('POST','/api/recipes',buildRecipeRequestBody(recipe)).then(function(data){
        if(data.recipe){
          state.myRecipes.unshift(data.recipe);
          if(data.recipe.status==='approved'){
            state.recipes.unshift(data.recipe);
            state.adminRecipes.unshift(data.recipe);
          }else if(data.recipe.status==='pending'){
            state.pendingRecipes.unshift(data.recipe);
          }
        }
        notify('cookmate:data-ready',{});return data.recipe;
      });
    },
    updateUserRecipe: function(id,recipe){
      return request('PUT','/api/recipes/'+encodeURIComponent(id),buildRecipeRequestBody(recipe)).then(function(data){
        if(data.recipe){
          state.myRecipes=state.myRecipes.map(function(item){return String(item.id)===String(id)?data.recipe:item;});
          if(data.recipe.status==='approved'){
            var exists=state.recipes.some(function(item){return String(item.id)===String(id);});
            state.recipes=exists?state.recipes.map(function(item){return String(item.id)===String(id)?data.recipe:item;}):[data.recipe].concat(state.recipes);
            var existsAdm=state.adminRecipes.some(function(item){return String(item.id)===String(id);});
            state.adminRecipes=existsAdm?state.adminRecipes.map(function(item){return String(item.id)===String(id)?data.recipe:item;}):[data.recipe].concat(state.adminRecipes);
          }else{
            state.recipes=state.recipes.filter(function(item){return String(item.id)!==String(id);});
            state.adminRecipes=state.adminRecipes.filter(function(item){return String(item.id)!==String(id);});
          }
        }
        notify('cookmate:data-ready',{});return data.recipe;
      });
    },
    deleteUserRecipe: function(id){
      return request('DELETE','/api/recipes/'+encodeURIComponent(id),{}).then(function(data){
        state.myRecipes=state.myRecipes.filter(function(item){return String(item.id)!==String(id);});
        state.recipes=state.recipes.filter(function(item){return String(item.id)!==String(id);});
        state.pendingRecipes=state.pendingRecipes.filter(function(item){return String(item.id)!==String(id);});
        state.adminRecipes=state.adminRecipes.filter(function(item){return String(item.id)!==String(id);});
        notify('cookmate:data-ready',{});return data;
      });
    },
    adminDeleteRecipe: function(id){
      return request('DELETE','/api/admin/recipes/'+encodeURIComponent(id),{}).then(function(data){
        state.myRecipes=state.myRecipes.filter(function(item){return String(item.id)!==String(id);});
        state.recipes=state.recipes.filter(function(item){return String(item.id)!==String(id);});
        state.pendingRecipes=state.pendingRecipes.filter(function(item){return String(item.id)!==String(id);});
        state.adminRecipes=state.adminRecipes.filter(function(item){return String(item.id)!==String(id);});
        if(state.statistics&&typeof state.statistics.totalRecipes==='number'&&state.statistics.totalRecipes>0){
          state.statistics.totalRecipes-=1;
        }
        notify('cookmate:data-ready',{});return data;
      });
    },
    addRecipe: function(recipe){return this.addUserRecipe(recipe);},
    updateRecipe: function(id,updates){return this.updateUserRecipe(id,updates);},
    deleteRecipe: function(id){return state.user&&state.user.role==='admin'?this.adminDeleteRecipe(id):this.deleteUserRecipe(id);},
    getPendingRecipes: function(){return state.pendingRecipes.slice();},
    getManagedRecipes: function(){return (state.adminRecipes||[]).filter(function(r){return r&&r.status!=='pending';});},
    getRejectedRecipes: function(){return state.myRecipes.filter(function(r){return r.status==='rejected';});},
    getApprovedRecipes: function(){return this.getAllRecipes();},
    approveRecipe: function(id){
      return request('POST','/api/admin/recipes/'+encodeURIComponent(id)+'/approve',{}).then(function(data){
        state.pendingRecipes=state.pendingRecipes.filter(function(r){return String(r.id)!==String(id);});
        if(data.recipe){
          state.recipes.unshift(data.recipe);
          var existsAdm=state.adminRecipes.some(function(r){return String(r.id)===String(id);});
          state.adminRecipes=existsAdm?state.adminRecipes.map(function(r){return String(r.id)===String(id)?data.recipe:r;}):[data.recipe].concat(state.adminRecipes);
        }
        return data.recipe;
      });
    },
    rejectRecipe: function(id,reason){
      return request('POST','/api/admin/recipes/'+encodeURIComponent(id)+'/reject',{reason:reason||''}).then(function(data){
        state.pendingRecipes=state.pendingRecipes.filter(function(r){return String(r.id)!==String(id);});
        state.recipes=state.recipes.filter(function(r){return String(r.id)!==String(id);});
        if(data.recipe){
          var existsAdm=state.adminRecipes.some(function(r){return String(r.id)===String(id);});
          state.adminRecipes=existsAdm?state.adminRecipes.map(function(r){return String(r.id)===String(id)?data.recipe:r;}):[data.recipe].concat(state.adminRecipes);
        }
        return data.recipe;
      });
    },
    fetchAdminRecipeReview: function(id){
      return request('GET','/api/admin/recipes/'+encodeURIComponent(id)+'/review');
    },
    getRecipeById: function(id,includeUnapproved){
      var all=this.getAllRecipesRaw();var found=all.find(function(r){return String(r.id)===String(id);});
      if(found&&(includeUnapproved||found.status==='approved'||!found.status))return found;
      return null;
    },
    fetchRecipeDetail: function(id,incrementView,includePrivate){
      var qs=[];
      if(incrementView) qs.push('incrementView=1');
      var path=(includePrivate?'/api/admin/recipes/':'/api/recipes/')+encodeURIComponent(id)+(qs.length?'?'+qs.join('&'):'');
      return request('GET',path).then(function(recipe){
        if(recipe&&recipe.id){
          var idx=state.recipes.findIndex(function(r){return String(r.id)===String(recipe.id);});
          if(idx>=0) state.recipes[idx]=recipe;
          else if(recipe.status==='approved') state.recipes.push(recipe);
          state.myRecipes=state.myRecipes.map(function(r){return String(r.id)===String(recipe.id)?recipe:r;});
        }
        return recipe;
      });
    },
    getStatistics: function(){return Object.assign({},state.statistics);},
    submitChatbotFeedback: function(qaId,rating,sessionId){
      return request('POST','/api/chatbot/feedback',{qa_id:Number(qaId),rating:Number(rating),session_id:sessionId||''});
    },
    getCategoryById: function(id){return this.getAllCategories().find(function(c){return String(c.id)===String(id)||c.slug===id;});},
    updateUser: function(updatedUser){return request('PUT','/api/users/profile',updatedUser).then(function(data){state.user=data.user;notify('cookmate:auth-changed',{});return data.user;});},
    setUserStatus: function(userId,status){return request('PUT','/api/admin/users/'+encodeURIComponent(userId)+'/status',{status:status}).then(function(data){state.users=state.users.map(function(u){return String(u.id)===String(userId)?data.user:u;});return data.user;});},
    getUserComments: function(){return state.comments.filter(function(c){return state.user&&String(c.userId)===String(state.user.id);});},
    getDeletedCommentIds: function(){return [];},
    addComment: function(recipeId,content,rating){return request('POST','/api/recipes/'+encodeURIComponent(recipeId)+'/comments',{comment:content,rating:rating||5}).then(function(data){state.comments.unshift(data.comment);return data.comment;});},
    deleteComment: function(commentId){return request('DELETE','/api/comments/'+encodeURIComponent(commentId),{}).then(function(data){state.comments=state.comments.filter(function(c){return String(c.id)!==String(commentId);});return data;});},
    getCommentsForRecipe: function(recipeId){return state.comments.filter(function(c){return String(c.recipeId)===String(recipeId);});},
    getRegisteredUsers: function(){return state.users.slice();},
    getAllUsers: function(){return state.user&&state.user.role==='admin'?state.users.slice():[];},
    registerUser: function(userData){
      return request('POST','/api/auth/register',{name:userData.name,email:userData.email,password:userData.password}).then(function(data){state.user=data.user;state.csrfToken=data.csrfToken||state.csrfToken;notify('cookmate:auth-changed',{});return {user:data.user};});
    },
    getCategories: function(){return state.categories.slice();},
    setCategories: function(cats){return request('PUT','/api/categories/sync',{categories:cats}).then(function(data){state.categories=data.categories||[];notify('cookmate:data-ready',{});return state.categories;});},
    getIngredients: function(){return state.ingredients.slice();},
    setIngredients: function(items){return request('PUT','/api/ingredients/sync',{ingredients:items}).then(function(data){state.ingredients=data.ingredients||[];notify('cookmate:data-ready',{});return state.ingredients;});},
    getAllRecipesRaw: function(){
      if(isHttpMode()&&!state.online)return [];
      var values=(state.adminRecipes&&state.adminRecipes.length?state.adminRecipes:[]).concat(state.recipes,state.myRecipes,state.pendingRecipes);var seen={};
      return values.filter(function(r){if(!r||seen[r.id])return false;seen[r.id]=true;return true;});
    },
    getAllRecipes: function(includeAll){var rows=this.getAllRecipesRaw();return includeAll?rows:rows.filter(function(r){return r.status==='approved'||!r.status;});},
    getAllCategories: function(){return isHttpMode()?state.categories.slice():((typeof CATEGORIES!=='undefined')?CATEGORIES.slice():[]);},
    getAllIngredients: function(){return isHttpMode()?state.ingredients.slice():((typeof INGREDIENTS!=='undefined')?INGREDIENTS.slice():[]);},
    getAllComments: function(){return state.comments.slice();},
    resetAll: function(){return Promise.reject(new Error('Reset dữ liệu đã bị tắt để bảo vệ database.'));},
    estimateNutrition: function(ingredients,servings){
      var list=Array.isArray(ingredients)?ingredients:[];
      return request('POST','/api/nutrition/estimate',{ingredients:list,servings:servings||2}).then(function(data){return data.nutrition;});
    }
  };

  // Load MySQL-backed public and session data before existing page initializers run.
  if (isHttpMode()) {
    document.addEventListener('cookmate:backend-unavailable', function(event) {
      var show=function(){
        if(document.getElementById('cookmateBackendNotice'))return;
        var notice=document.createElement('div');notice.id='cookmateBackendNotice';
        notice.setAttribute('role','status');
        notice.textContent=(event.detail&&event.detail.message)||'Backend MySQL tạm thời không khả dụng. Vui lòng kiểm tra kết nối máy chủ.';
        notice.style.cssText='position:fixed;left:12px;bottom:12px;z-index:9997;max-width:min(460px,calc(100vw - 24px));padding:10px 14px;border-radius:10px;background:#fff3cd;color:#664d03;border:1px solid #ffecb5;font:13px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px #0002';
        document.body.appendChild(notice);
      };
      if(document.body)show();else window.addEventListener('load',show,{once:true});
    });
  }

  return store;
})();
