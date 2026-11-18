// ===================================================================
// CookMate - Utility Functions
// ===================================================================

// ===== DOM Utilities =====
function $(selector, parent = document) {
  return parent.querySelector(selector);
}

function $$(selector, parent = document) {
  return [...parent.querySelectorAll(selector)];
}

function createElement(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  Object.entries(attrs).forEach(([key, val]) => {
    if (key === 'className') el.className = val;
    else if (key === 'innerHTML') el.innerHTML = val;
    else if (key === 'textContent') el.textContent = val;
    else if (key.startsWith('data')) el.setAttribute(key.replace(/([A-Z])/g, '-$1').toLowerCase(), val);
    else if (key === 'style' && typeof val === 'object') Object.assign(el.style, val);
    else el.setAttribute(key, val);
  });
  children.forEach(function (child) {
    if (typeof child === 'string') el.appendChild(document.createTextNode(child));
    else if (child) el.appendChild(child);
  });
  return el;
}

// ===== String Utilities =====
function slugify(str) {
  return str
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  if (typeof document !== 'undefined' && document.createElement) {
    try {
      var div = document.createElement('div');
      div.textContent = str;
      if (div.innerHTML) return div.innerHTML;
    } catch (e) {
      // Fallback to regex
    }
  }
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function truncateText(text, maxLength) {
  if (maxLength === undefined) maxLength = 100;
  if (!text || text.length <= maxLength) return text || '';
  return text.substring(0, maxLength).trim() + '...';
}

function formatNumber(num) {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
  return num.toString();
}

function formatDate(dateStr) {
  var d = new Date(dateStr);
  return d.toLocaleDateString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });
}

function timeAgo(dateStr) {
  var now = new Date();
  var date = new Date(dateStr);
  var diff = Math.floor((now - date) / 1000);
  if (diff < 60) return 'Vừa xong';
  if (diff < 3600) return Math.floor(diff / 60) + ' phút trước';
  if (diff < 86400) return Math.floor(diff / 3600) + ' giờ trước';
  if (diff < 2592000) return Math.floor(diff / 86400) + ' ngày trước';
  return formatDate(dateStr);
}

// ===== Number Utilities =====
function roundSmart(num) {
  if (num === 0) return 0;
  if (num < 0.1) return Math.round(num * 100) / 100;
  if (num < 10) return Math.round(num * 4) / 4; // Round to nearest 0.25
  return Math.round(num);
}

function formatFraction(num) {
  if (num === 0) return '0';
  var rounded = roundSmart(num);
  if (rounded === 0.25) return '¼';
  if (rounded === 0.5) return '½';
  if (rounded === 0.75) return '¾';
  if (rounded === 0.33) return '⅓';
  if (rounded === 0.67) return '⅔';
  var whole = Math.floor(rounded);
  var frac = Math.round((rounded - whole) * 100) / 100;
  if (frac === 0) return whole.toString();
  if (frac === 0.25) return whole > 0 ? whole + ' ¼' : '¼';
  if (frac === 0.5) return whole > 0 ? whole + ' ½' : '½';
  if (frac === 0.75) return whole > 0 ? whole + ' ¾' : '¾';
  return rounded.toString();
}

// ===== Validation Utilities =====
function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function isNotEmpty(value) {
  return value !== null && value !== undefined && value.toString().trim() !== '';
}

function validateRequired(value, fieldName) {
  if (!isNotEmpty(value)) return fieldName + ' không được để trống';
  return null;
}

function validateEmail(email) {
  if (!isNotEmpty(email)) return 'Email không được để trống';
  if (!isValidEmail(email)) return 'Email không đúng định dạng';
  return null;
}

function validatePassword(password) {
  if (!isNotEmpty(password)) return 'Mật khẩu không được để trống';
  if (password.length < 8) return 'Mật khẩu phải có ít nhất 8 ký tự';
  return null;
}

function validatePasswordMatch(password, confirm) {
  if (password !== confirm) return 'Mật khẩu xác nhận không khớp';
  return null;
}

// ===== Image Utilities (Real High-Resolution Food Photography, 0 SVG Category Fallbacks) =====
var CATEGORY_PHOTO_MAP = {
  '1': 'https://www.cet.edu.vn/wp-content/uploads/2018/03/thit-kho-tau-trung-cut.jpg',
  'mon-chinh': 'https://www.cet.edu.vn/wp-content/uploads/2018/03/thit-kho-tau-trung-cut.jpg',
  'mon-chinh.svg': 'https://www.cet.edu.vn/wp-content/uploads/2018/03/thit-kho-tau-trung-cut.jpg',
  '2': 'https://cdn2.fptshop.com.vn/unsafe/2024_3_23_638467922672032197_batch_cach-nau-canh-chua-ca-loc.jpg',
  'mon-canh-sup': 'https://cdn2.fptshop.com.vn/unsafe/2024_3_23_638467922672032197_batch_cach-nau-canh-chua-ca-loc.jpg',
  'canh-sup': 'https://cdn2.fptshop.com.vn/unsafe/2024_3_23_638467922672032197_batch_cach-nau-canh-chua-ca-loc.jpg',
  'canh-sup.svg': 'https://cdn2.fptshop.com.vn/unsafe/2024_3_23_638467922672032197_batch_cach-nau-canh-chua-ca-loc.jpg',
  '3': 'https://cdn2.fptshop.com.vn/unsafe/thit_bo_xao_thap_cam_2_7bb704dd0b.png',
  'mon-xao': 'https://cdn2.fptshop.com.vn/unsafe/thit_bo_xao_thap_cam_2_7bb704dd0b.png',
  'mon-xao.svg': 'https://cdn2.fptshop.com.vn/unsafe/thit_bo_xao_thap_cam_2_7bb704dd0b.png',
  '4': 'https://www.huongnghiepaau.com/wp-content/uploads/2018/06/ga-nuong-mat-ong.jpg',
  'mon-nuong-chien': 'https://www.huongnghiepaau.com/wp-content/uploads/2018/06/ga-nuong-mat-ong.jpg',
  'mon-nuong-chien.svg': 'https://www.huongnghiepaau.com/wp-content/uploads/2018/06/ga-nuong-mat-ong.jpg',
  '5': 'https://cdn.tgdd.vn/2024/01/CookRecipe/GalleryStep/thanh-pham-44.jpg',
  'mon-chay': 'https://cdn.tgdd.vn/2024/01/CookRecipe/GalleryStep/thanh-pham-44.jpg',
  'mon-chay.svg': 'https://cdn.tgdd.vn/2024/01/CookRecipe/GalleryStep/thanh-pham-44.jpg',
  '6': 'https://www.lorca.vn/wp-content/uploads/2022/11/maxresdefault-8.jpg',
  'mon-trang-mieng': 'https://www.lorca.vn/wp-content/uploads/2022/11/maxresdefault-8.jpg',
  'trang-mieng-banh': 'https://www.lorca.vn/wp-content/uploads/2022/11/maxresdefault-8.jpg',
  'trang-mieng-banh.svg': 'https://www.lorca.vn/wp-content/uploads/2022/11/maxresdefault-8.jpg',
  '7': 'https://cdn2.fptshop.com.vn/unsafe/640x0/filters:format(webp):quality(75)/cach_lam_tra_dao_cam_sa_2313d177e5.jpg',
  'do-uong': 'https://cdn2.fptshop.com.vn/unsafe/640x0/filters:format(webp):quality(75)/cach_lam_tra_dao_cam_sa_2313d177e5.jpg',
  'do-uong-sinh-to': 'https://cdn2.fptshop.com.vn/unsafe/640x0/filters:format(webp):quality(75)/cach_lam_tra_dao_cam_sa_2313d177e5.jpg',
  'do-uong-sinh-to.svg': 'https://cdn2.fptshop.com.vn/unsafe/640x0/filters:format(webp):quality(75)/cach_lam_tra_dao_cam_sa_2313d177e5.jpg',
  '8': 'https://www.cet.edu.vn/wp-content/uploads/2018/11/goi-cuon-tom-thit.jpg',
  'mon-khai-vi': 'https://www.cet.edu.vn/wp-content/uploads/2018/11/goi-cuon-tom-thit.jpg',
  'khai-vi-goi-cuon': 'https://www.cet.edu.vn/wp-content/uploads/2018/11/goi-cuon-tom-thit.jpg',
  'khai-vi-goi-cuon.svg': 'https://www.cet.edu.vn/wp-content/uploads/2018/11/goi-cuon-tom-thit.jpg'
};

function getCategoryFallbackImage(categoryHint) {
  var key = String(categoryHint || '').trim().toLowerCase();
  if (CATEGORY_PHOTO_MAP[key]) return CATEGORY_PHOTO_MAP[key];
  return CATEGORY_PHOTO_MAP['1'];
}

function getImageUrl(url, fallback) {
  if (!url) return fallback || getCategoryFallbackImage('1');
  if (typeof url === 'string') {
    var trimmed = url.trim();
    if (trimmed.toLowerCase().indexOf('categories/') !== -1 && trimmed.toLowerCase().slice(-4) === '.svg') {
      var baseName = trimmed.split('/').pop().toLowerCase();
      return CATEGORY_PHOTO_MAP[baseName] || fallback || getCategoryFallbackImage('1');
    }
    if (trimmed.indexOf('assets/') === 0) return getBasePath() + trimmed;
  }
  return url;
}

function handleImageError(img, categoryHint) {
  if (!img) return;
  if (img.dataset && img.dataset.fallbackApplied === '1') {
    img.onerror = null;
    img.src = getPlaceholderUrl(img.alt || 'Món ăn CookMate');
    return;
  }
  if (img.dataset) img.dataset.fallbackApplied = '1';
  var hint = categoryHint || img.getAttribute('data-category-id') || '';
  img.onerror = function () {
    img.onerror = null;
    img.src = getPlaceholderUrl(img.alt || 'Món ăn CookMate');
  };
  img.src = getCategoryFallbackImage(hint);
}

function getPlaceholderUrl(text) {
  try {
    var canvas = document.createElement('canvas');
    if (!canvas || !canvas.getContext) {
      return getBasePath() + 'assets/images/placeholders/recipe-placeholder.svg';
    }
    canvas.width = 600;
    canvas.height = 400;
    var ctx = canvas.getContext('2d');
    if (!ctx) return getBasePath() + 'assets/images/placeholders/recipe-placeholder.svg';

    // Warm appetizing gradient background
    var grad = ctx.createLinearGradient(0, 0, 600, 400);
    grad.addColorStop(0, '#FFF7ED');
    grad.addColorStop(0.5, '#FFEDD5');
    grad.addColorStop(1, '#FED7AA');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 600, 400);

    // Decorative circles
    ctx.fillStyle = 'rgba(232, 93, 42, 0.05)';
    ctx.beginPath();
    ctx.arc(60, 60, 100, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(540, 340, 130, 0, Math.PI * 2);
    ctx.fill();

    // Central circular badge
    ctx.shadowColor = 'rgba(232, 93, 42, 0.2)';
    ctx.shadowBlur = 16;
    ctx.shadowOffsetY = 6;
    ctx.fillStyle = '#FFFFFF';
    ctx.beginPath();
    ctx.arc(300, 160, 52, 0, Math.PI * 2);
    ctx.fill();

    var iconGrad = ctx.createLinearGradient(250, 110, 350, 210);
    iconGrad.addColorStop(0, '#E85D2A');
    iconGrad.addColorStop(1, '#C74E22');
    ctx.fillStyle = iconGrad;
    ctx.beginPath();
    ctx.arc(300, 160, 44, 0, Math.PI * 2);
    ctx.fill();

    // Reset shadow
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;
    ctx.shadowOffsetY = 0;

    // Utensil icon
    ctx.font = '36px "Segoe UI Emoji", "Apple Color Emoji", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('🍳', 300, 160);

    // Title / dish name
    var dishName = (text || 'Món ăn ngon').trim();
    if (dishName.length > 28) dishName = dishName.substring(0, 28) + '...';
    ctx.fillStyle = '#292524';
    ctx.font = 'bold 20px "Be Vietnam Pro", -apple-system, sans-serif';
    ctx.fillText(dishName, 300, 250);

    // Brand tagline
    ctx.fillStyle = '#C74E22';
    ctx.font = '600 13px "Be Vietnam Pro", -apple-system, sans-serif';
    ctx.fillText('CookMate • Chuẩn định lượng', 300, 280);

    return canvas.toDataURL('image/jpeg', 0.9);
  } catch (e) {
    return getBasePath() + 'assets/images/placeholders/recipe-placeholder.svg';
  }
}

// ===== URL/Navigation Utilities =====
function getQueryParam(name) {
  var params = new URLSearchParams(window.location.search);
  return params.get(name);
}

function getBasePath() {
  if (typeof window === 'undefined' || !window.location) return './';
  var path = (window.location.pathname || '').replace(/\\/g, '/');
  if (path.includes('/pages/admin/')) return '../../';
  if (path.includes('/pages/auth/') || path.includes('/pages/account/')) return '../../';
  if (path.includes('/pages/')) return '../';
  return './';
}

// ===== Debounce =====
function debounce(fn, delay) {
  if (delay === undefined) delay = 300;
  var timer;
  return function () {
    var context = this;
    var args = arguments;
    clearTimeout(timer);
    timer = setTimeout(function () {
      fn.apply(context, args);
    }, delay);
  };
}

// ===== Exact Vietnamese Diacritic-Aware & Whole-Word Recipe Search Scorer =====
var _VN_WORD_CHAR_SRC = '0-9a-zA-ZÀ-ỹ';

var _ANIMAL_TERMS_NFC_JS = [
  'ức gà', 'đùi gà', 'cánh gà', 'chân gà', 'thịt gà', 'lòng gà', 'phở gà', 'cơm gà', 'miến gà', 'cháo gà', 'súp gà',
  'thịt bò', 'bắp bò', 'gầu bò', 'bún bò', 'phở bò', 'bò kho', 'bò xào', 'bò né', 'bò lúc lắc',
  'thịt heo', 'thịt lợn', 'ba chỉ', 'ba rọi', 'nạc vai', 'sườn', 'giò heo', 'chân giò', 'móng giò', 'chả lụa', 'giò sống', 'bún chả', 'nem rán', 'chả giò', 'thịt kho',
  'cá lóc', 'cá quả', 'cá chuối', 'cá tràu', 'cá trắm', 'cá lăng', 'cá ngừ', 'cá thu', 'cá hồi', 'cá hú', 'cá basa', 'cá nục', 'cá bống', 'cá chép', 'cá điêu hồng', 'cá trê', 'cá kèo', 'cá kho', 'chả cá',
  'tôm', 'mực', 'bạch tuộc', 'cua', 'ghẹ', 'ốc', 'nghêu', 'ngao', 'hến', 'sò', 'hàu', 'lươn', 'ếch', 'sứa', 'trâu',
  'vịt', 'ngan', 'chim cút', 'trứng gà', 'trứng vịt', 'trứng cút', 'mắm tôm', 'mắm nêm', 'mắm tép', 'nước mắm',
  'gà', 'bò', 'heo', 'lợn', 'cá'
];

var _ANIMAL_TERMS_ASCII_JS = [
  'uc ga', 'dui ga', 'canh ga', 'chan ga', 'thit ga', 'long ga', 'pho ga', 'com ga', 'mien ga', 'chao ga', 'sup ga',
  'thit bo', 'bap bo', 'gau bo', 'bun bo', 'pho bo', 'bo kho', 'bo xao', 'bo ne', 'bo luc lac',
  'thit heo', 'thit lon', 'ba chi', 'ba roi', 'nac vai', 'suon', 'gio heo', 'chan gio', 'cha lua', 'gio song', 'bun cha', 'nem ran', 'cha gio', 'thit kho',
  'ca loc', 'ca qua', 'ca chuoi', 'ca trau', 'ca tram', 'ca lang', 'ca ngu', 'ca thu', 'ca hoi', 'ca hu', 'ca basa', 'ca nuc', 'ca bong', 'ca chep', 'ca dieu hong', 'ca kho', 'cha ca',
  'tom', 'muc', 'bach tuoc', 'cua', 'ghe', 'oc', 'ngheu', 'ngao', 'hen', 'hau', 'luon', 'ech', 'trau',
  'vit', 'ngan', 'chim cut', 'trung ga', 'trung vit', 'trung cut', 'mam tom', 'mam nem', 'nuoc mam',
  'ga', 'bo', 'heo', 'lon', 'ca'
];

var _CONTIGUOUS_PHRASES_ASCII_JS = {
  'uc ga': 1, 'dui ga': 1, 'chan ga': 1, 'thit ga': 1, 'nam dui ga': 1,
  'trung ga': 1, 'trung vit': 1, 'trung cut': 1,
  'thit bo': 1, 'bap bo': 1, 'bun bo': 1, 'pho bo': 1, 'pho ga': 1, 'bo kho': 1,
  'thit heo': 1, 'thit lon': 1, 'ba chi': 1, 'ba roi': 1, 'nac vai': 1,
  'ca loc': 1, 'ca thu': 1, 'ca hoi': 1, 'ca hu': 1, 'ca basa': 1, 'ca nuc': 1, 'ca bong': 1, 'ca chep': 1, 'ca dieu hong': 1,
  'ca chua': 1, 'ca tim': 1, 'ca rot': 1, 'ca phe': 1, 'ca ri': 1,
  'dau hu': 1, 'dau phu': 1, 'tau hu': 1, 'sua chua': 1, 'banh flan': 1, 'goi cuon': 1, 'cha gio': 1
};

function _escapeRegExpSearch(str) {
  return String(str || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function _normNfcWords(text) {
  var s = String(text || '');
  if (s.normalize) s = s.normalize('NFC');
  s = s.toLowerCase().trim();
  var reNonWord = new RegExp('[^' + _VN_WORD_CHAR_SRC + ']+', 'g');
  return s.replace(reNonWord, ' ').replace(/\s+/g, ' ').trim();
}

function _normAsciiWords(text) {
  var s = String(text || '');
  if (s.normalize) s = s.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  s = s.toLowerCase().replace(/đ/g, 'd').replace(/[^a-z0-9]+/g, ' ');
  return s.replace(/\s+/g, ' ').trim();
}

function _hasWholePhraseJS(haystack, needle, isAscii) {
  if (!haystack || !needle) return false;
  var cls = isAscii ? 'a-z0-9' : _VN_WORD_CHAR_SRC;
  var re = new RegExp('(^|[^' + cls + '])' + _escapeRegExpSearch(needle) + '($|[^' + cls + '])');
  return re.test(haystack);
}

function _replaceWholePhraseJS(text, needle, replacement, isAscii) {
  if (!text || !needle) return text || '';
  var cls = isAscii ? 'a-z0-9' : _VN_WORD_CHAR_SRC;
  var re = new RegExp('(^|[^' + cls + '])' + _escapeRegExpSearch(needle) + '(?=$|[^' + cls + '])', 'g');
  return text.replace(re, '$1' + replacement);
}

function _expandIngredientAliasesJS(rawName) {
  var n = _normNfcWords(rawName);
  if (!n) return [];
  var out = [n];
  var rawLow = String(rawName || '');
  if (rawLow.normalize) rawLow = rawLow.normalize('NFC');
  rawLow = rawLow.toLowerCase().trim();

  var mGa = rawLow.match(/^thịt\s+gà\s*\(\s*([^)]+)\s*\)$/);
  if (mGa && mGa[1]) {
    var cut = _normNfcWords(mGa[1]);
    if (cut) {
      out.push(cut + ' gà');
      out.push('thịt ' + cut + ' gà');
      out.push('thịt gà');
    }
  } else if (n === 'cánh gà' || n === 'chân gà' || n === 'đùi gà' || n === 'ức gà') {
    out.push('thịt gà');
  }

  var mHeo = rawLow.match(/^thịt\s+heo\s*\(\s*([^)]+)\s*\)$/);
  if (mHeo && mHeo[1]) {
    var cutH = _normNfcWords(mHeo[1]);
    if (cutH) {
      out.push(cutH);
      out.push('thịt ' + cutH);
      out.push('thịt heo');
      out.push('thịt lợn');
    }
  } else if (n.indexOf('thịt ba chỉ') !== -1 || n === 'ba chỉ') {
    out.push('ba chỉ', 'ba rọi', 'thịt ba chỉ', 'thịt heo', 'thịt lợn');
  } else if (n.indexOf('thịt heo xay') !== -1) {
    out.push('thịt băm', 'thịt bằm', 'thịt xay', 'thịt heo', 'thịt lợn');
  } else if (n.indexOf('sườn') !== -1 && n.indexOf('chay') === -1) {
    out.push('sườn', 'sườn heo', 'thịt heo');
  }

  if (n === 'bắp bò' || n === 'gầu bò' || n === 'thăn bò' || n === 'nạm bò') {
    out.push('thịt bò');
  }
  if (n.indexOf('đậu hũ') !== -1) {
    out.push(n.replace(/đậu hũ/g, 'đậu phụ'));
  } else if (n.indexOf('đậu phụ') !== -1) {
    out.push(n.replace(/đậu phụ/g, 'đậu hũ'));
  }
  if (n === 'tôm sú' || n === 'tôm tươi' || n === 'tôm thẻ' || n === 'tôm đất') {
    out.push('tôm');
  }

  var seen = {};
  return out.filter(function (x) {
    if (!x || seen[x]) return false;
    seen[x] = true;
    return true;
  });
}

function _queryRequestsAnimalWithoutVeganJS(qNfc, qAscii, hasDiacritics) {
  if (_hasWholePhraseJS(qNfc, 'chay', false) || _hasWholePhraseJS(qAscii, 'chay', true) || qAscii.indexOf('vegan') !== -1) {
    return false;
  }
  if (hasDiacritics) {
    return _ANIMAL_TERMS_NFC_JS.some(function (t) {
      return _hasWholePhraseJS(qNfc, t, false);
    });
  }
  var masked = qAscii;
  ['ca chua', 'ca tim', 'ca rot', 'ca phe', 'ca ri', 'cacao', 'sinh to bo', 'qua bo', 'trai bo', 'bo lat'].forEach(function (nf) {
    masked = _replaceWholePhraseJS(masked, nf, ' ', true);
  });
  masked = masked.replace(/\s+/g, ' ').trim();
  return _ANIMAL_TERMS_ASCII_JS.some(function (t) {
    return _hasWholePhraseJS(masked, t, true);
  });
}

function _maskCandidateFalseFriendsJS(text, qAscii, isAscii) {
  if (!text) return '';
  var out = text;
  var wantsMushroom = _hasWholePhraseJS(qAscii, 'nam', true);
  var wantsEgg = _hasWholePhraseJS(qAscii, 'trung', true);
  var wantsBroth = _hasWholePhraseJS(qAscii, 'nuoc dung', true);

  if (!wantsMushroom) {
    out = isAscii ? _replaceWholePhraseJS(out, 'nam dui ga', 'nam', true) : _replaceWholePhraseJS(out, 'nấm đùi gà', 'nấm', false);
  }
  if (!wantsEgg) {
    out = isAscii ? _replaceWholePhraseJS(out, 'trung ga', 'trung', true) : _replaceWholePhraseJS(out, 'trứng gà', 'trứng', false);
  }
  if (!wantsBroth) {
    out = isAscii ? _replaceWholePhraseJS(out, 'nuoc dung ga', 'nuoc dung', true) : _replaceWholePhraseJS(out, 'nước dùng gà', 'nước dùng', false);
  }

  if (isAscii) {
    if (_hasWholePhraseJS(qAscii, 'ca', true) && !['ca chua', 'ca tim', 'ca rot', 'ca phe', 'ca ri'].some(function (p) { return _hasWholePhraseJS(qAscii, p, true); })) {
      ['ca chua', 'ca tim', 'ca rot', 'ca phe', 'ca ri'].forEach(function (nf) {
        out = _replaceWholePhraseJS(out, nf, 'rau', true);
      });
    }
    if (_hasWholePhraseJS(qAscii, 'bo', true) && !['bo lat', 'qua bo', 'trai bo', 'sinh to bo', 'banh bo'].some(function (p) { return _hasWholePhraseJS(qAscii, p, true); })) {
      ['bo lat', 'qua bo', 'trai bo', 'sinh to bo', 'hanh boaro', 'banh bo'].forEach(function (nb) {
        out = _replaceWholePhraseJS(out, nb, 'thucpham', true);
      });
    }
  }
  return out.replace(/\s+/g, ' ').trim();
}

function scoreRecipeSearch(recipe, keyword) {
  if (!keyword || !String(keyword).trim()) return 1;
  if (!recipe) return 0;

  var qNfc = _normNfcWords(keyword);
  var qAscii = _normAsciiWords(keyword);
  if (!qNfc || !qAscii) return 1;

  var hasDiacritics = (qNfc !== qAscii);
  var qPhrase = hasDiacritics ? qNfc : qAscii;
  var qTokens = qPhrase.split(' ');
  var isAsc = !hasDiacritics;
  var normFn = hasDiacritics ? _normNfcWords : _normAsciiWords;

  var catId = parseInt(recipe.categoryId || recipe.category_id || 0, 10) || 0;
  var catNameAsc = _normAsciiWords(recipe.categoryName || recipe.category_name || '');
  var titleRaw = String(recipe.title || '');
  var titleAscRaw = _normAsciiWords(titleRaw);
  var isVeganRecipe = (catId === 5) || (catNameAsc.indexOf('chay') !== -1) || _hasWholePhraseJS(titleAscRaw, 'chay', true);

  if (isVeganRecipe && _queryRequestsAnimalWithoutVeganJS(qNfc, qAscii, hasDiacritics)) {
    return 0;
  }

  var titleNorm = _maskCandidateFalseFriendsJS(normFn(titleRaw), qAscii, isAsc);
  var ingAliases = [];
  if (Array.isArray(recipe.ingredients)) {
    recipe.ingredients.forEach(function (ing) {
      var iname = typeof ing === 'string' ? ing : (ing && (ing.name || ing.ingredient_name) || '');
      _expandIngredientAliasesJS(iname).forEach(function (aliasNfc) {
        if (aliasNfc === 'nước dùng gà' && (qAscii === 'ga' || qAscii === 'thit ga' || qAscii === 'uc ga' || qAscii === 'dui ga' || qAscii === 'canh ga')) {
          return;
        }
        var cand = hasDiacritics ? aliasNfc : normFn(aliasNfc);
        var maskedCand = _maskCandidateFalseFriendsJS(cand, qAscii, isAsc);
        if (maskedCand) ingAliases.push(maskedCand);
      });
    });
  }

  var tagsStr = Array.isArray(recipe.tags) ? recipe.tags.join(' ') : '';
  var tagsNorm = _maskCandidateFalseFriendsJS(normFn(tagsStr), qAscii, isAsc);

  var _REGIONAL_DISH_SYN_JS_NFC = {
    'bún chả quạt': ['bún chả hà nội', 'bún chả nướng'],
    'bún chả nướng than': ['bún chả hà nội', 'bún chả nướng'],
    'thịt kho hột vịt': ['thịt kho tàu', 'thịt kho trứng'],
    'thịt kho riệu': ['thịt kho tàu'],
    'thịt kho trứng': ['thịt kho tàu', 'thịt kho hột vịt'],
    'thịt kho tàu': ['thịt kho hột vịt', 'thịt kho trứng'],
    'nem rán': ['chả giò', 'nem cua bể', 'chả ram'],
    'chả giò': ['nem rán', 'chả ram'],
    'cá quả': ['cá lóc'],
    'cá chuối': ['cá lóc'],
    'cá tràu': ['cá lóc'],
    'tào phớ': ['tàu hũ nước đường', 'tàu hũ', 'đậu hũ non'],
    'tàu hũ nước đường': ['tào phớ', 'tàu hũ'],
    'phở hai tô': ['phở khô gia lai'],
    'bánh xèo huế': ['bánh khoái'],
    'bánh xèo miền trung': ['bánh khoái'],
    'bánh cuốn nghệ an': ['bánh mướt'],
    'củ nén': ['hành tăm'],
    'mộc nhĩ': ['nấm mèo'],
    'nấm mèo': ['mộc nhĩ'],
    'ba rọi': ['ba chỉ', 'thịt ba chỉ'],
    'thịt ba rọi': ['thịt ba chỉ', 'ba chỉ'],
    'thịt lợn': ['thịt heo'],
    'bột ngô': ['bột bắp']
  };
  var _REGIONAL_DISH_SYN_JS_ASC = {
    'bun cha quat': ['bun cha ha noi', 'bun cha nuong'],
    'bun cha nuong than': ['bun cha ha noi', 'bun cha nuong'],
    'thit kho hot vit': ['thit kho tau', 'thit kho trung'],
    'thit kho rieu': ['thit kho tau'],
    'thit kho trung': ['thit kho tau', 'thit kho hot vit'],
    'thit kho tau': ['thit kho hot vit', 'thit kho trung'],
    'nem ran': ['cha gio', 'nem cua be', 'cha ram'],
    'cha gio': ['nem ran', 'cha ram'],
    'ca qua': ['ca loc'],
    'ca chuoi': ['ca loc'],
    'ca trau': ['ca loc'],
    'tao pho': ['tau hu nuoc duong', 'tau hu', 'dau hu non'],
    'tau hu nuoc duong': ['tao pho', 'tau hu'],
    'pho hai to': ['pho kho gia lai'],
    'banh xeo hue': ['banh khoai'],
    'banh xeo mien trung': ['banh khoai'],
    'banh cuon nghe an': ['banh muot'],
    'cu nen': ['hanh tam'],
    'moc nhi': ['nam meo'],
    'nam meo': ['moc nhi'],
    'ba roi': ['ba chi', 'thit ba chi'],
    'thit ba roi': ['thit ba chi', 'ba chi'],
    'thit lon': ['thit heo'],
    'bot ngo': ['bot bap']
  };

  var altPhrases = [qPhrase];
  if (qPhrase.indexOf('đậu hũ') !== -1) altPhrases.push(qPhrase.replace(/đậu hũ/g, 'đậu phụ'));
  else if (qPhrase.indexOf('đậu phụ') !== -1) altPhrases.push(qPhrase.replace(/đậu phụ/g, 'đậu hũ'));
  else if (qPhrase.indexOf('dau hu') !== -1) altPhrases.push(qPhrase.replace(/dau hu/g, 'dau phu'));
  else if (qPhrase.indexOf('dau phu') !== -1) altPhrases.push(qPhrase.replace(/dau phu/g, 'dau hu'));

  var synMapJS = hasDiacritics ? _REGIONAL_DISH_SYN_JS_NFC : _REGIONAL_DISH_SYN_JS_ASC;
  Object.keys(synMapJS).forEach(function (srcTerm) {
    if (_hasWholePhraseJS(qPhrase, srcTerm, isAsc)) {
      synMapJS[srcTerm].forEach(function (tgt) {
        var repl = _replaceWholePhraseJS(qPhrase, srcTerm, tgt, isAsc).trim();
        if (repl && altPhrases.indexOf(repl) === -1) altPhrases.push(repl);
        if (qPhrase === srcTerm && altPhrases.indexOf(tgt) === -1) altPhrases.push(tgt);
      });
    }
  });

  // Rank 1 (100): Exact whole-word phrase in title
  for (var i = 0; i < altPhrases.length; i++) {
    if (_hasWholePhraseJS(titleNorm, altPhrases[i], isAsc)) return 100;
  }

  // Rank 2 (85): Exact whole-word phrase (or all tokens of species) inside an ingredient alias
  for (var j = 0; j < ingAliases.length; j++) {
    var alias = ingAliases[j];
    for (var k = 0; k < altPhrases.length; k++) {
      if (_hasWholePhraseJS(alias, altPhrases[k], isAsc)) return 85;
    }
    if (qTokens.length >= 2 && !(qAscii === 'uc ga' || qAscii === 'dui ga' || qAscii === 'canh ga' || qAscii === 'chan ga')) {
      var allInAlias = qTokens.every(function (tok) { return _hasWholePhraseJS(alias, tok, isAsc); });
      if (allInAlias) return 85;
    }
  }

  if (_CONTIGUOUS_PHRASES_ASCII_JS[qAscii]) {
    for (var m = 0; m < altPhrases.length; m++) {
      if (_hasWholePhraseJS(tagsNorm, altPhrases[m], isAsc)) return 60;
    }
    return 0;
  }

  var cpKeys = Object.keys(_CONTIGUOUS_PHRASES_ASCII_JS);
  for (var cIdx = 0; cIdx < cpKeys.length; cIdx++) {
    var cp = cpKeys[cIdx];
    if (_hasWholePhraseJS(qAscii, cp, true)) {
      var cpCheck = cp;
      if (hasDiacritics) {
        var idxToks = qAscii.split(' ');
        var cpToks = cp.split(' ');
        for (var pIdx = 0; pIdx <= idxToks.length - cpToks.length; pIdx++) {
          if (idxToks.slice(pIdx, pIdx + cpToks.length).join(' ') === cp) {
            cpCheck = qTokens.slice(pIdx, pIdx + cpToks.length).join(' ');
            break;
          }
        }
      }
      var hasSubPhrase = _hasWholePhraseJS(titleNorm, cpCheck, isAsc) || ingAliases.some(function (a) {
        return _hasWholePhraseJS(a, cpCheck, isAsc);
      });
      if (!hasSubPhrase) return 0;
    }
  }

  // Rank 3 (60): Strict AND across title + ingredients + tags
  var combined = (titleNorm + ' ' + ingAliases.join(' ') + ' ' + tagsNorm).trim();
  var allMatched = qTokens.every(function (tok) {
    return _hasWholePhraseJS(combined, tok, isAsc);
  });
  return allMatched ? 60 : 0;
}

function matchesRecipeSearch(recipe, keyword) {
  return scoreRecipeSearch(recipe, keyword) > 0;
}
