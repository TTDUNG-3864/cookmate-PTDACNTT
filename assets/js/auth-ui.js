/**
 * CookMate Authentication UI & Bát Phở Hà Nội Interactive Controller
 * Version 2.0 - Phở Hà Nội Sâu Lòng, Gắp Phở Tự Nhiên, Tách Độc Lập Login & Register
 */

var CookMateAuthUI = (function () {
  'use strict';

  var state = {
    isPhoLifted: false,
    resetEmail: '',
    otpTimerId: null,
    otpRemainingSeconds: 300
  };

  /**
   * Tạo hiệu ứng gợn sóng (Ripple effect) khi nhấn nút
   */
  function createRipple(event, button) {
    var rect = button.getBoundingClientRect();
    var ripple = document.createElement('span');
    ripple.className = 'auth-ripple';
    var size = Math.max(rect.width, rect.height);
    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = (event.clientX - rect.left - size / 2) + 'px';
    ripple.style.top = (event.clientY - rect.top - size / 2) + 'px';
    button.appendChild(ripple);
    setTimeout(function () {
      ripple.remove();
    }, 600);
  }

  /**
   * Kích hoạt chuyển động Bát phở nhấc đũa kéo sợi phở
   */
  function triggerPho(forceState) {
    var stage = document.getElementById('phoStage');
    var cta = document.getElementById('phoCta');

    if (!stage) return;

    if (typeof forceState === 'boolean') {
      state.isPhoLifted = forceState;
    } else {
      state.isPhoLifted = !state.isPhoLifted;
    }

    if (state.isPhoLifted) {
      stage.classList.add('is-lifted');
      if (cta) {
        cta.innerHTML = '<i class="fa-solid fa-utensils"></i> <span>Mời bạn thưởng thức hương vị CookMate!</span>';
      }
    } else {
      stage.classList.remove('is-lifted');
      if (cta) {
        cta.innerHTML = '<i class="fa-solid fa-hand-pointer"></i> <span>Chạm vào đôi đũa để gắp phở Hà Nội</span>';
      }
    }
  }

  /**
   * Thiết lập tính năng ẩn/hiện mật khẩu cho tất cả các nút eye icon
   */
  function setupPasswordToggles() {
    var toggleBtns = document.querySelectorAll('.password-toggle-btn');
    toggleBtns.forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        var targetId = btn.getAttribute('data-target');
        var input = targetId ? document.getElementById(targetId) : btn.parentElement.querySelector('input');
        if (!input) return;

        var isPw = input.type === 'password';
        input.type = isPw ? 'text' : 'password';

        var icon = btn.querySelector('i');
        if (icon) {
          if (isPw) {
            icon.className = 'fa-regular fa-eye-slash';
            btn.setAttribute('aria-label', 'Ẩn mật khẩu');
          } else {
            icon.className = 'fa-regular fa-eye';
            btn.setAttribute('aria-label', 'Hiện mật khẩu');
          }
        }
      });
    });
  }

  /**
   * Đo lường độ mạnh mật khẩu và cập nhật 4 vạch chỉ báo
   */
  function setupPasswordStrength() {
    var regPassword = document.getElementById('regPassword');
    var segs = [
      document.getElementById('seg1'),
      document.getElementById('seg2'),
      document.getElementById('seg3'),
      document.getElementById('seg4')
    ];
    var strengthText = document.getElementById('strengthText');

    if (!regPassword || !segs[0]) return;

    var labels = ['', 'Yếu', 'Trung bình', 'Khá', 'Rất mạnh'];
    var colors = ['', '#EF4444', '#F59E0B', '#16A34A', '#2E7D4F'];

    function evaluate(pw) {
      if (!pw || pw.length === 0) return 0;
      var score = 0;
      if (pw.length >= 8) score++;
      if (pw.length >= 10) score++;
      if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
      if (/[0-9]/.test(pw) || /[^A-Za-z0-9]/.test(pw)) score++;
      return Math.min(score, 4);
    }

    regPassword.addEventListener('input', function () {
      var val = regPassword.value;
      var score = evaluate(val);

      segs.forEach(function (seg, index) {
        seg.className = 'auth-strength-seg';
        if (index < score) {
          var cls = score === 1 ? 'active-weak' : score === 2 ? 'active-fair' : score === 3 ? 'active-good' : 'active-strong';
          seg.classList.add(cls);
        }
      });

      if (strengthText) {
        if (!val) {
          strengthText.textContent = 'Tối thiểu 8 ký tự';
          strengthText.style.color = '#78716C';
        } else {
          strengthText.textContent = labels[score] || 'Quá ngắn';
          strengthText.style.color = colors[score] || '#78716C';
        }
      }
    });
  }

  /**
   * Xử lý gửi Form Đăng nhập
   */
  function setupLoginForm() {
    var form = document.getElementById('loginForm');
    var submitBtn = document.getElementById('loginSubmitBtn');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();

      var emailInput = document.getElementById('loginEmail');
      var passInput = document.getElementById('loginPassword');
      var emailErr = document.getElementById('loginEmailError');
      var passErr = document.getElementById('loginPasswordError');

      // Reset errors
      if (emailInput) emailInput.classList.remove('input-error');
      if (passInput) passInput.classList.remove('input-error');
      if (emailErr) emailErr.classList.remove('is-visible');
      if (passErr) passErr.classList.remove('is-visible');

      var email = emailInput ? emailInput.value.trim() : '';
      var password = passInput ? passInput.value : '';
      var hasError = false;

      // Validation
      if (!email) {
        if (emailInput) emailInput.classList.add('input-error');
        if (emailErr) {
          emailErr.textContent = 'Email không được để trống';
          emailErr.classList.add('is-visible');
        }
        hasError = true;
      } else if (typeof isValidEmail === 'function' && !isValidEmail(email)) {
        if (emailInput) emailInput.classList.add('input-error');
        if (emailErr) {
          emailErr.textContent = 'Định dạng email không hợp lệ';
          emailErr.classList.add('is-visible');
        }
        hasError = true;
      }

      if (!password) {
        if (passInput) passInput.classList.add('input-error');
        if (passErr) {
          passErr.textContent = 'Mật khẩu không được để trống';
          passErr.classList.add('is-visible');
        }
        hasError = true;
      }

      if (hasError) return;

      // Loading state
      if (submitBtn) {
        submitBtn.classList.add('is-loading');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Đang xác thực...</span>';
      }

      CookMateStorage.login(email, password).then(function (data) {
        var user = data.user;
        if (user && (user.must_change_password || user.mustChangePassword)) {
          if (submitBtn) {
            submitBtn.classList.remove('is-loading');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> <span>Đăng nhập</span>';
          }
          if (typeof CookMateStorage.enforceMandatoryPasswordChange === 'function') {
            CookMateStorage.enforceMandatoryPasswordChange();
          }
          return;
        }
        if (typeof CookMateUI !== 'undefined') CookMateUI.showToast('Đăng nhập thành công! Chào mừng ' + user.name, 'success');
        if (typeof Navigation !== 'undefined') Navigation.updateAuthArea();
        if (typeof updateFavoriteBadge === 'function') updateFavoriteBadge();
        if (submitBtn) submitBtn.innerHTML = '<i class="fa-solid fa-circle-check"></i> <span>Thành công!</span>';
        triggerPho(true);
        setTimeout(function () {
          var redirectUrl = new URLSearchParams(window.location.search).get('redirect');
          if (user.role === 'admin') {
            if (redirectUrl && redirectUrl.indexOf('admin/') !== -1 && !/^https?:/i.test(redirectUrl)) {
              window.location.href = redirectUrl.indexOf('pages/') === 0 ? '../../' + redirectUrl : redirectUrl;
            } else window.location.href = '../../pages/admin/index.html';
            return;
          }
          if (redirectUrl && redirectUrl.indexOf('admin/') === -1 && !/^https?:/i.test(redirectUrl)) {
            window.location.href = redirectUrl.indexOf('pages/') === 0 ? '../../' + redirectUrl : redirectUrl;
          } else window.location.href = '../../index.html';
        }, 300);
      }).catch(function (error) {
        if (submitBtn) { submitBtn.classList.remove('is-loading'); submitBtn.disabled = false; submitBtn.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> <span>Đăng nhập</span>'; }
        if (passInput) passInput.classList.add('input-error');
        if (passErr) { passErr.textContent = error.message || 'Không thể đăng nhập. Vui lòng thử lại.'; passErr.classList.add('is-visible'); }
        if (typeof CookMateUI !== 'undefined') CookMateUI.showToast(error.message || 'Không thể kết nối Backend.', 'error');
      });
    });
  }

  /**
   * Xử lý gửi Form Đăng ký
   */
  function setupRegisterForm() {
    var form = document.getElementById('registerForm');
    var submitBtn = document.getElementById('regSubmitBtn');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();

      var nameInput = document.getElementById('regName');
      var emailInput = document.getElementById('regEmail');
      var passInput = document.getElementById('regPassword');
      var confirmInput = document.getElementById('regConfirm');
      var termsCheck = document.getElementById('regTerms');

      var nameErr = document.getElementById('regNameError');
      var emailErr = document.getElementById('regEmailError');
      var passErr = document.getElementById('regPasswordError');
      var confirmErr = document.getElementById('regConfirmError');

      // Clear errors
      [nameInput, emailInput, passInput, confirmInput].forEach(function (inp) {
        if (inp) inp.classList.remove('input-error');
      });
      [nameErr, emailErr, passErr, confirmErr].forEach(function (err) {
        if (err) err.classList.remove('is-visible');
      });

      var name = nameInput ? nameInput.value.trim() : '';
      var email = emailInput ? emailInput.value.trim() : '';
      var password = passInput ? passInput.value : '';
      var confirm = confirmInput ? confirmInput.value : '';
      var hasError = false;

      // 1. Validate Họ tên
      if (!name) {
        if (nameInput) nameInput.classList.add('input-error');
        if (nameErr) {
          nameErr.textContent = 'Họ và tên không được để trống';
          nameErr.classList.add('is-visible');
        }
        hasError = true;
      }

      // 2. Validate Email
      if (!email) {
        if (emailInput) emailInput.classList.add('input-error');
        if (emailErr) {
          emailErr.textContent = 'Email không được để trống';
          emailErr.classList.add('is-visible');
        }
        hasError = true;
      } else if (typeof isValidEmail === 'function' && !isValidEmail(email)) {
        if (emailInput) emailInput.classList.add('input-error');
        if (emailErr) {
          emailErr.textContent = 'Định dạng email không hợp lệ';
          emailErr.classList.add('is-visible');
        }
        hasError = true;
      }

      // 3. Validate Mật khẩu
      if (!password) {
        if (passInput) passInput.classList.add('input-error');
        if (passErr) {
          passErr.textContent = 'Mật khẩu không được để trống';
          passErr.classList.add('is-visible');
        }
        hasError = true;
      } else if (password.length < 8) {
        if (passInput) passInput.classList.add('input-error');
        if (passErr) {
          passErr.textContent = 'Mật khẩu phải có ít nhất 8 ký tự';
          passErr.classList.add('is-visible');
        }
        hasError = true;
      }

      // 4. Validate Xác nhận mật khẩu
      if (!confirm) {
        if (confirmInput) confirmInput.classList.add('input-error');
        if (confirmErr) {
          confirmErr.textContent = 'Vui lòng xác nhận mật khẩu';
          confirmErr.classList.add('is-visible');
        }
        hasError = true;
      } else if (password !== confirm) {
        if (confirmInput) confirmInput.classList.add('input-error');
        if (confirmErr) {
          confirmErr.textContent = 'Mật khẩu xác nhận không khớp';
          confirmErr.classList.add('is-visible');
        }
        hasError = true;
      }

      // 5. Check điều khoản
      if (termsCheck && !termsCheck.checked) {
        if (typeof CookMateUI !== 'undefined') {
          CookMateUI.showToast('Vui lòng đồng ý với Điều khoản dịch vụ & Chính sách của CookMate', 'warning');
        }
        hasError = true;
      }

      if (hasError) return;

      // Loading
      if (submitBtn) {
        submitBtn.classList.add('is-loading');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Đang khởi tạo tài khoản...</span>';
      }

      CookMateStorage.registerUser({ name:name, email:email, password:password }).then(function () {
        if (typeof CookMateUI !== 'undefined') CookMateUI.showToast('Đăng ký thành công!', 'success');
        triggerPho(true);
        setTimeout(function () { window.location.href = '../../index.html'; }, 700);
      }).catch(function (error) {
        if (submitBtn) { submitBtn.classList.remove('is-loading'); submitBtn.disabled = false; submitBtn.innerHTML = '<i class="fa-solid fa-user-plus"></i> <span>Đăng ký tài khoản</span>'; }
        var message=error.message||'Có lỗi khi đăng ký.';
        if (emailErr && /email|sử dụng/i.test(message)) { emailErr.textContent=message; emailErr.classList.add('is-visible'); }
        if (typeof CookMateUI !== 'undefined') CookMateUI.showToast(message, 'error');
      });
    });
  }

  /**
   * Luồng Quên mật khẩu 3 bước bằng OTP Terminal (DEMO_MODE)
   * Render động từng bước vào #forgotPasswordWrap để bước chưa tới không tồn tại trong DOM
   */
  function setupForgotPasswordFlow() {
    var loginViewWrap = document.getElementById('loginViewWrap');
    var forgotWrap = document.getElementById('forgotPasswordWrap');
    var forgotLink = document.getElementById('forgotPasswordLink');

    if (!loginViewWrap || !forgotWrap || !forgotLink) return;

    function stopOtpTimer() {
      if (state.otpTimerId) {
        clearInterval(state.otpTimerId);
        state.otpTimerId = null;
      }
    }

    function formatTimer(sec) {
      var s = Math.max(0, Number(sec) || 0);
      var mins = Math.floor(s / 60);
      var rem = s % 60;
      return String(mins) + ':' + (rem < 10 ? '0' + rem : String(rem));
    }

    function clearFieldErr(inp, errEl) {
      if (inp) inp.classList.remove('input-error');
      if (errEl) {
        errEl.textContent = '';
        errEl.classList.remove('is-visible');
        errEl.style.display = 'none';
      }
    }

    function showFieldErr(inp, errEl, message) {
      if (inp) inp.classList.add('input-error');
      if (errEl) {
        errEl.textContent = message;
        errEl.classList.add('is-visible');
        errEl.style.display = 'block';
      }
    }

    function backToLogin(e) {
      if (e) e.preventDefault();
      stopOtpTimer();
      state.resetEmail = '';
      forgotWrap.innerHTML = '';
      forgotWrap.style.display = 'none';
      loginViewWrap.style.display = 'block';
    }

    function renderStep1() {
      stopOtpTimer();
      loginViewWrap.style.display = 'none';
      forgotWrap.style.display = 'block';
      forgotWrap.innerHTML = '' +
        '<div id="forgotStep1" class="forgot-step">' +
          '<div class="forgot-step__badge" aria-hidden="true">' +
            '<i class="fa-solid fa-key"></i>' +
          '</div>' +
          '<h2 class="auth-title">Khôi phục mật khẩu</h2>' +
          '<p class="auth-subtitle">Nhập địa chỉ email đã đăng ký để nhận mã xác minh.</p>' +
          '<form id="forgotEmailForm" novalidate>' +
            '<div class="auth-field">' +
              '<label for="forgotEmailInput" class="auth-label">' +
                '<span><i class="fa-regular fa-envelope"></i> Email đăng ký</span>' +
              '</label>' +
              '<div class="auth-input-wrap">' +
                '<i class="fa-regular fa-envelope auth-field-icon"></i>' +
                '<input type="email" id="forgotEmailInput" name="forgotEmail" class="auth-input" placeholder="Nhập địa chỉ email đã đăng ký" autocomplete="email" required>' +
              '</div>' +
              '<div class="auth-error-msg form-error" id="forgotEmailError" role="alert"></div>' +
            '</div>' +
            '<div class="auth-btn-stack">' +
              '<button type="submit" class="auth-action-btn" id="forgotSendOtpBtn">' +
                '<i class="fa-solid fa-paper-plane"></i>' +
                '<span>Gửi mã xác minh</span>' +
              '</button>' +
              '<button type="button" class="auth-back-btn" id="forgotStep1BackBtn">' +
                '<i class="fa-solid fa-arrow-left"></i>' +
                '<span>Quay lại đăng nhập</span>' +
              '</button>' +
            '</div>' +
          '</form>' +
        '</div>';

      var emailForm = document.getElementById('forgotEmailForm');
      var emailInput = document.getElementById('forgotEmailInput');
      var emailErr = document.getElementById('forgotEmailError');
      var sendOtpBtn = document.getElementById('forgotSendOtpBtn');
      var step1BackBtn = document.getElementById('forgotStep1BackBtn');

      if (step1BackBtn) step1BackBtn.addEventListener('click', backToLogin);
      if (emailInput) emailInput.focus();

      if (emailForm) {
        emailForm.addEventListener('submit', function (e) {
          e.preventDefault();
          clearFieldErr(emailInput, emailErr);

          var email = emailInput ? emailInput.value.trim() : '';
          var strictEmailRe = /^[A-Za-z0-9](?:[A-Za-z0-9._%+-]*[A-Za-z0-9])?@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/;

          if (!email) {
            showFieldErr(emailInput, emailErr, 'Vui lòng nhập địa chỉ email đã đăng ký.');
            return;
          }
          if (email.length > 150 || email.indexOf('..') !== -1 || !strictEmailRe.test(email)) {
            showFieldErr(emailInput, emailErr, 'Định dạng email không hợp lệ.');
            return;
          }

          if (sendOtpBtn) {
            sendOtpBtn.disabled = true;
            sendOtpBtn.classList.add('is-loading');
            sendOtpBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Đang gửi mã xác minh...</span>';
          }

          CookMateStorage.requestPasswordResetOtp(email).then(function (data) {
            state.resetEmail = email;
            renderStep2();
            if (typeof CookMateUI !== 'undefined') {
              CookMateUI.showToast((data && data.message) || 'Nếu email tồn tại trong hệ thống, mã xác minh đã được cấp.', 'info');
            }
          }).catch(function (err) {
            var msg = (err && err.message) || 'Không thể gửi mã xác minh. Vui lòng thử lại.';
            showFieldErr(emailInput, emailErr, msg);
            if (typeof CookMateUI !== 'undefined') CookMateUI.showToast(msg, 'error');
          }).finally(function () {
            if (sendOtpBtn && document.body.contains(sendOtpBtn)) {
              sendOtpBtn.disabled = false;
              sendOtpBtn.classList.remove('is-loading');
              sendOtpBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> <span>Gửi mã xác minh</span>';
            }
          });
        });
      }
    }

    function renderStep2() {
      stopOtpTimer();
      loginViewWrap.style.display = 'none';
      forgotWrap.style.display = 'block';
      forgotWrap.innerHTML = '' +
        '<div id="forgotStep2" class="forgot-step">' +
          '<div class="forgot-step__badge" aria-hidden="true">' +
            '<i class="fa-solid fa-shield-halved"></i>' +
          '</div>' +
          '<h2 class="auth-title">Xác minh tài khoản</h2>' +
          '<p class="auth-subtitle">Nhập mã xác minh 6 chữ số được cấp trong Terminal.</p>' +
          '<div class="otp-timer-row">' +
            '<i class="fa-regular fa-clock"></i>' +
            '<span>Thời gian còn lại:</span>' +
            '<span class="otp-timer-value" id="otpCountdownTimer">5:00</span>' +
          '</div>' +
          '<form id="forgotVerifyOtpForm" novalidate>' +
            '<div class="auth-field">' +
              '<label for="forgotOtpInput" class="auth-label">' +
                '<span><i class="fa-solid fa-hashtag"></i> Mã xác minh (6 chữ số)</span>' +
              '</label>' +
              '<div class="auth-input-wrap">' +
                '<input type="text" id="forgotOtpInput" name="otp" class="auth-input otp-single-input" placeholder="000000" maxlength="6" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" aria-label="Mã xác minh 6 chữ số" required>' +
              '</div>' +
              '<div class="auth-error-msg form-error" id="forgotOtpError" role="alert"></div>' +
            '</div>' +
            '<div class="auth-btn-stack">' +
              '<button type="submit" class="auth-action-btn" id="forgotVerifyOtpBtn">' +
                '<i class="fa-solid fa-circle-check"></i>' +
                '<span>Xác minh</span>' +
              '</button>' +
              '<button type="button" class="auth-secondary-btn" id="forgotResendOtpBtn">' +
                '<i class="fa-solid fa-rotate-right"></i>' +
                '<span>Gửi lại mã</span>' +
              '</button>' +
              '<button type="button" class="auth-back-btn" id="forgotStep2BackBtn">' +
                '<i class="fa-solid fa-arrow-left"></i>' +
                '<span>Quay lại đăng nhập</span>' +
              '</button>' +
            '</div>' +
          '</form>' +
        '</div>';

      var otpForm = document.getElementById('forgotVerifyOtpForm');
      var otpInput = document.getElementById('forgotOtpInput');
      var otpErr = document.getElementById('forgotOtpError');
      var verifyOtpBtn = document.getElementById('forgotVerifyOtpBtn');
      var resendOtpBtn = document.getElementById('forgotResendOtpBtn');
      var step2BackBtn = document.getElementById('forgotStep2BackBtn');
      var timerEl = document.getElementById('otpCountdownTimer');

      function startOtpTimer(seconds) {
        stopOtpTimer();
        state.otpRemainingSeconds = typeof seconds === 'number' ? seconds : 300;
        if (timerEl) timerEl.textContent = formatTimer(state.otpRemainingSeconds);

        state.otpTimerId = setInterval(function () {
          state.otpRemainingSeconds -= 1;
          if (timerEl) timerEl.textContent = formatTimer(state.otpRemainingSeconds);
          if (state.otpRemainingSeconds <= 0) {
            stopOtpTimer();
            showFieldErr(otpInput, otpErr, 'Mã xác minh đã hết hạn. Vui lòng gửi lại mã.');
          }
        }, 1000);
      }

      startOtpTimer(300);
      if (step2BackBtn) step2BackBtn.addEventListener('click', backToLogin);
      if (otpInput) otpInput.focus();

      if (otpForm) {
        otpForm.addEventListener('submit', function (e) {
          e.preventDefault();
          clearFieldErr(otpInput, otpErr);

          var otp = otpInput ? otpInput.value.trim() : '';
          if (!/^[0-9]{6}$/.test(otp)) {
            var fmtMsg = 'Mã xác minh phải gồm đúng 6 chữ số.';
            showFieldErr(otpInput, otpErr, fmtMsg);
            if (typeof CookMateUI !== 'undefined') CookMateUI.showToast(fmtMsg, 'warning');
            return;
          }

          if (verifyOtpBtn) {
            verifyOtpBtn.disabled = true;
            verifyOtpBtn.classList.add('is-loading');
            verifyOtpBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> <span>Đang xác minh...</span>';
          }

          CookMateStorage.verifyPasswordResetOtp(state.resetEmail, otp).then(function (data) {
            stopOtpTimer();
            var tempPw = (data && data.temporary_password) || '';
            renderStep3(tempPw);
            triggerPho(true);
            if (typeof CookMateUI !== 'undefined') {
              CookMateUI.showToast((data && data.message) || 'Khôi phục mật khẩu thành công!', 'success');
            }
          }).catch(function (err) {
            var msg = (err && err.message) || 'Mã xác minh không hợp lệ.';
            showFieldErr(otpInput, otpErr, msg);
            if (typeof CookMateUI !== 'undefined') CookMateUI.showToast(msg, 'error');
          }).finally(function () {
            if (verifyOtpBtn && document.body.contains(verifyOtpBtn)) {
              verifyOtpBtn.disabled = false;
              verifyOtpBtn.classList.remove('is-loading');
              verifyOtpBtn.innerHTML = '<i class="fa-solid fa-circle-check"></i> <span>Xác minh</span>';
            }
          });
        });
      }

      if (resendOtpBtn) {
        resendOtpBtn.addEventListener('click', function (e) {
          e.preventDefault();
          clearFieldErr(otpInput, otpErr);
          if (!state.resetEmail) return;

          resendOtpBtn.disabled = true;
          CookMateStorage.resendPasswordResetOtp(state.resetEmail).then(function (data) {
            if (otpInput) otpInput.value = '';
            clearFieldErr(otpInput, otpErr);
            startOtpTimer(300);
            if (typeof CookMateUI !== 'undefined') {
              CookMateUI.showToast((data && data.message) || 'Đã gửi lại mã xác minh mới vào Terminal.', 'info');
            }
          }).catch(function (err) {
            var msg = (err && err.message) || 'Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút.';
            showFieldErr(otpInput, otpErr, msg);
            if (typeof CookMateUI !== 'undefined') CookMateUI.showToast(msg, 'warning');
          }).finally(function () {
            if (resendOtpBtn && document.body.contains(resendOtpBtn)) {
              resendOtpBtn.disabled = false;
            }
          });
        });
      }
    }

    function renderStep3(tempPassword) {
      stopOtpTimer();
      loginViewWrap.style.display = 'none';
      forgotWrap.style.display = 'block';
      forgotWrap.innerHTML = '' +
        '<div id="forgotStep3" class="forgot-step">' +
          '<div class="forgot-step__badge forgot-step__badge--success" aria-hidden="true">' +
            '<i class="fa-solid fa-check"></i>' +
          '</div>' +
          '<h2 class="auth-title">Khôi phục mật khẩu thành công!</h2>' +
          '<p class="auth-subtitle">CookMate đã cấp cho bạn một mật khẩu mới.</p>' +
          '<div class="auth-field">' +
            '<label for="tempPasswordDisplay" class="auth-label">' +
              '<span><i class="fa-solid fa-key"></i> Mật khẩu mới</span>' +
            '</label>' +
            '<div class="auth-input-wrap">' +
              '<i class="fa-solid fa-lock auth-field-icon"></i>' +
              '<input type="password" id="tempPasswordDisplay" class="auth-input temp-password-input" readonly value="" aria-label="Mật khẩu mới">' +
              '<button type="button" class="password-toggle-btn" id="toggleTempPasswordBtn" data-target="tempPasswordDisplay" aria-label="Hiện mật khẩu">' +
                '<i class="fa-regular fa-eye"></i>' +
              '</button>' +
            '</div>' +
          '</div>' +
          '<div class="temp-password-warning" role="alert">' +
            '<i class="fa-solid fa-triangle-exclamation"></i>' +
            '<span>Vui lòng lưu mật khẩu này. Mật khẩu chỉ được hiển thị một lần. Sau khi đăng nhập, bạn nên đổi sang mật khẩu riêng của mình.</span>' +
          '</div>' +
          '<div class="auth-btn-stack">' +
            '<button type="button" class="auth-secondary-btn" id="copyTempPasswordBtn">' +
              '<i class="fa-regular fa-copy"></i>' +
              '<span>Sao chép mật khẩu</span>' +
            '</button>' +
            '<button type="button" class="auth-action-btn" id="forgotSuccessBackToLoginBtn">' +
              '<i class="fa-solid fa-right-to-bracket"></i>' +
              '<span>Về trang đăng nhập</span>' +
            '</button>' +
          '</div>' +
        '</div>';

      var tempPwInput = document.getElementById('tempPasswordDisplay');
      var toggleTempPwBtn = document.getElementById('toggleTempPasswordBtn');
      var copyTempPwBtn = document.getElementById('copyTempPasswordBtn');
      var successBackBtn = document.getElementById('forgotSuccessBackToLoginBtn');

      if (tempPwInput) {
        tempPwInput.type = 'password';
        tempPwInput.value = tempPassword || '';
      }

      if (toggleTempPwBtn && tempPwInput) {
        toggleTempPwBtn.addEventListener('click', function (e) {
          e.preventDefault();
          var isPw = tempPwInput.type === 'password';
          tempPwInput.type = isPw ? 'text' : 'password';
          var icon = toggleTempPwBtn.querySelector('i');
          if (icon) {
            icon.className = isPw ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye';
          }
          toggleTempPwBtn.setAttribute('aria-label', isPw ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
        });
      }

      if (copyTempPwBtn) {
        copyTempPwBtn.addEventListener('click', function (e) {
          e.preventDefault();
          var secret = tempPwInput ? tempPwInput.value : '';
          if (!secret) return;

          function onCopied() {
            if (typeof CookMateUI !== 'undefined') {
              CookMateUI.showToast('Đã sao chép mật khẩu mới!', 'success');
            }
          }

          if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            navigator.clipboard.writeText(secret).then(onCopied).catch(function () {
              fallbackCopy(secret);
              onCopied();
            });
          } else {
            fallbackCopy(secret);
            onCopied();
          }
        });
      }

      if (successBackBtn) {
        successBackBtn.addEventListener('click', backToLogin);
      }
    }

    function fallbackCopy(text) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (e) {}
      ta.remove();
    }

    forgotLink.addEventListener('click', function (e) {
      e.preventDefault();
      renderStep1();
    });
  }

  /**
   * Phương thức tiếp tục với Google & Facebook (Lỗi 5)
   */
  function setupSocialAuth() {
    var btnGoogle = document.getElementById('btnGoogleAuth');
    var btnFacebook = document.getElementById('btnFacebookAuth');

    if (btnGoogle) {
      btnGoogle.addEventListener('click', function (e) {
        e.preventDefault();
        if (typeof CookMateUI !== 'undefined') {
          CookMateUI.showToast('Phương thức tiếp tục với Google đang được phát triển và sẽ sớm ra mắt!', 'info');
        }
      });
    }

    if (btnFacebook) {
      btnFacebook.addEventListener('click', function (e) {
        e.preventDefault();
        if (typeof CookMateUI !== 'undefined') {
          CookMateUI.showToast('Phương thức tiếp tục với Facebook đang được phát triển và sẽ sớm ra mắt!', 'info');
        }
      });
    }
  }

  /**
   * Khởi tạo toàn bộ tương tác Auth
   */
  function init() {
    // 1. Kiểm tra session hiện tại - Nếu đã đăng nhập, kiểm tra bắt buộc đổi mật khẩu hoặc chuyển hướng theo vai trò
    if (typeof CookMateStorage !== 'undefined' && CookMateStorage.isLoggedIn()) {
      var currentUser = CookMateStorage.getCurrentUser();
      if (currentUser && (currentUser.must_change_password || currentUser.mustChangePassword)) {
        if (typeof CookMateStorage.enforceMandatoryPasswordChange === 'function') {
          CookMateStorage.enforceMandatoryPasswordChange();
        }
        return;
      }
      if (currentUser && currentUser.role === 'admin') {
        window.location.href = '../../pages/admin/index.html';
      } else {
        window.location.href = '../../index.html';
      }
      return;
    }

    // 2. Tương tác Bát phở Hà Nội
    var stage = document.getElementById('phoStage');
    if (stage) {
      stage.addEventListener('click', function () {
        triggerPho();
      });
      stage.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          triggerPho();
        }
      });
    }

    // 3. Hiệu ứng Ripple trên các nút hành động
    document.querySelectorAll('.auth-action-btn').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        createRipple(e, btn);
      });
    });

    // 4. Cài đặt các tính năng con
    setupPasswordToggles();
    setupPasswordStrength();
    setupLoginForm();
    setupRegisterForm();
    setupForgotPasswordFlow();
    setupSocialAuth();

    console.log('🍜 CookMate Pho Auth UI V2 initialized successfully');
  }

  return {
    init: init,
    triggerPho: triggerPho
  };
})();
