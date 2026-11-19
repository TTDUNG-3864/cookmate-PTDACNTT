// ===================================================================
// CookMate - Shared UI Components
// ===================================================================

var CookMateUI = {
  // Toast notifications
  toastContainer: null,
  _activeEscHandler: null,

  initToast: function () {
    var existing = document.getElementById('toastContainer');
    if (existing) {
      this.toastContainer = existing;
      return;
    }
    this.toastContainer = createElement('div', {
      className: 'toast-container',
      id: 'toastContainer'
    });
    document.body.appendChild(this.toastContainer);
  },

  showToast: function (message, type, duration) {
    if (!type) type = 'success';
    if (!duration) duration = 3000;

    this.initToast();

    var icons = {
      success: 'fa-circle-check',
      error: 'fa-circle-xmark',
      warning: 'fa-triangle-exclamation',
      info: 'fa-circle-info'
    };

    var safeMsg = escapeHtml(String(message == null ? '' : message));
    var toast = createElement('div', { className: 'toast toast--' + type + ' toast-' + type });
    toast.innerHTML =
      '<i class="fa-solid ' + (icons[type] || icons.info) + ' toast__icon toast-icon"></i>' +
      '<div class="toast__content"><span class="toast__message toast-message">' + safeMsg + '</span></div>' +
      '<button type="button" class="toast__close toast-close" aria-label="Đóng thông báo">' +
      '<i class="fa-solid fa-xmark"></i>' +
      '</button>';

    var closeBtn = toast.querySelector('.toast__close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        toast.remove();
      });
    }

    this.toastContainer.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(function () {
      toast.classList.add('toast-show');
    });

    setTimeout(function () {
      if (!toast.parentElement) return;
      toast.classList.remove('toast-show');
      toast.classList.add('toast-exit', 'toast-hide');
      setTimeout(function () {
        if (toast.parentElement) toast.remove();
      }, 250);
    }, duration);
  },

  // ---------------------------------------------------------------
  // Modal
  // ---------------------------------------------------------------
  showModal: function (options) {
    if (!options) options = {};
    var title = options.title || '';
    var subtitle = options.subtitle || '';
    var content = options.content || '';
    var footer = options.footer || '';
    var size = options.size || 'medium';
    var onClose = options.onClose || null;

    if (this._activeEscHandler) {
      document.removeEventListener('keydown', this._activeEscHandler);
      this._activeEscHandler = null;
    }

    // Remove existing modal
    var existing = document.getElementById('cookmate-modal');
    if (existing) existing.remove();

    var modal = createElement('div', {
      className: 'modal active modal-show',
      id: 'cookmate-modal',
      role: 'dialog',
      'aria-modal': 'true'
    });
    modal.innerHTML =
      '<div class="modal__backdrop modal-backdrop"></div>' +
      '<div class="modal__content modal-dialog modal-' + size + '">' +
      '<div class="modal__header modal-header">' +
      '<div class="modal__header-titles">' +
      '<h3 class="modal__title modal-title">' + title + '</h3>' +
      (subtitle ? '<p class="modal__subtitle">' + escapeHtml(subtitle) + '</p>' : '') +
      '</div>' +
      '<button type="button" class="modal__close modal-close" id="modalCloseBtn" aria-label="Đóng">' +
      '<i class="fa-solid fa-xmark"></i>' +
      '</button>' +
      '</div>' +
      '<div class="modal__body modal-body">' + content + '</div>' +
      (footer ? '<div class="modal__footer modal-footer">' + footer + '</div>' : '') +
      '</div>';

    document.body.appendChild(modal);

    var self = this;
    var closed = false;
    var closeModal = function () {
      if (closed) return;
      closed = true;
      if (self._activeEscHandler) {
        document.removeEventListener('keydown', self._activeEscHandler);
        self._activeEscHandler = null;
      }
      modal.classList.remove('active', 'modal-show');
      if (modal.parentElement) modal.remove();
      if (onClose) onClose();
    };

    var backdrop = modal.querySelector('.modal__backdrop');
    if (backdrop) backdrop.addEventListener('click', closeModal);
    var closeBtn = modal.querySelector('#modalCloseBtn');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);

    var escHandler = function (e) {
      if (e.key === 'Escape') {
        closeModal();
      }
    };
    this._activeEscHandler = escHandler;
    document.addEventListener('keydown', escHandler);

    return { modal: modal, close: closeModal };
  },

  // ---------------------------------------------------------------
  // Confirm dialog
  // ---------------------------------------------------------------
  showConfirm: function (message, onConfirm, onCancel) {
    var result = this.showModal({
      title: 'Xác nhận',
      content: '<p style="margin: 0; font-size: 15px;">' + escapeHtml(message) + '</p>',
      footer:
        '<button class="btn btn-secondary" id="confirmCancel">Hủy</button>' +
        '<button class="btn btn-danger" id="confirmOk">Xác nhận</button>',
      size: 'small',
      onClose: onCancel
    });

    var modalEl = result.modal;

    var okBtn = modalEl.querySelector('#confirmOk');
    if (okBtn) {
      okBtn.addEventListener('click', function () {
        var m = document.getElementById('cookmate-modal');
        if (m) m.remove();
        if (onConfirm) onConfirm();
      });
    }

    var cancelBtn = modalEl.querySelector('#confirmCancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        var m = document.getElementById('cookmate-modal');
        if (m) m.remove();
        if (onCancel) onCancel();
      });
    }

    return result;
  },

  // ---------------------------------------------------------------
  // Recipe card HTML generator
  // ---------------------------------------------------------------
  createRecipeCard: function (recipe, options) {
    if (!options) options = {};
    var showAuthor = options.showAuthor || false;
    var showActions = options.showActions !== undefined ? options.showActions : true;
    var linkBase = options.linkBase || '';
    var isFeatured = recipe.isFeatured || options.showFeaturedBadge;
    var isNew = recipe.isNew || options.showNewBadge;

    var isFav = CookMateStorage.isFavorite(recipe.id);
    var category = null;
    if (typeof CookMateStorage !== 'undefined' && typeof CookMateStorage.getCategoryById === 'function') {
      category = CookMateStorage.getCategoryById(recipe.categoryId);
    }
    if (!category && typeof CATEGORIES !== 'undefined') {
      category = CATEGORIES.find(function (c) { return String(c.id) === String(recipe.categoryId); });
    }
    var catName = (category && category.name) || recipe.categoryName || '';
    var catHint = escapeHtml(String(recipe.categoryId || (category && category.slug) || ''));
    var imgSrc = getImageUrl(recipe.image, getCategoryFallbackImage(catHint));

    var detailUrl = (linkBase || getBasePath()) + 'pages/recipe-detail.html?id=' + recipe.id;
    var totalTime = (recipe.prepTime || 0) + (recipe.cookTime || 0);
    var ratingVal = Number(recipe.rating || 4.8).toFixed(1);
    var viewsText = formatNumber(recipe.views || 0) + ' lượt xem';

    var html = '';
    html += '<article class="recipe-card" data-recipe-id="' + recipe.id + '">';

    // 1. Ảnh món ăn
    html += '<a href="' + detailUrl + '" class="recipe-card__image-link">';
    html += '<div class="recipe-card__image">';
    html += '<img src="' + escapeHtml(imgSrc) + '" alt="' + escapeHtml(recipe.title) + '" data-category-id="' + catHint + '" onerror="handleImageError(this, \'' + catHint + '\')" loading="lazy">';
    if (isFeatured) {
      html += '<span class="recipe-card__badge badge-featured"><i class="fa-solid fa-fire"></i> Nổi bật</span>';
    }
    if (isNew) {
      html += '<span class="recipe-card__badge badge-new">Mới</span>';
    }
    html += '</div></a>';

    // 2. Nội dung món ăn
    html += '<div class="recipe-card__content">';
    if (catName) {
      html += '<span class="recipe-card__category">' + escapeHtml(catName) + '</span>';
    }
    html += '<h3 class="recipe-card__title"><a href="' + detailUrl + '">' + escapeHtml(recipe.title) + '</a></h3>';
    html += '<p class="recipe-card__desc">' + escapeHtml(truncateText(recipe.description, 80)) + '</p>';

    // 3. Dòng sao đánh giá nằm ngay dưới mô tả ngắn
    html += '<div class="recipe-card__rating-line">';
    html += '  <span class="rating-stars-wrap">' + renderStars(recipe.rating || 4.8) + '</span>';
    html += '  <span class="rating-score-group"><strong class="rating-score">' + ratingVal + '</strong><span class="rating-max">/5</span></span>';
    html += '  <span class="rating-dot">•</span>';
    html += '  <span class="rating-count">' + viewsText + '</span>';
    html += '</div>';

    // Tác giả nếu có yêu cầu hiển thị
    if (showAuthor && recipe.authorName) {
      html += '<div class="recipe-card__author">';
      html += '<i class="fa-solid fa-user-circle"></i> ';
      html += '<span>' + escapeHtml(recipe.authorName) + '</span>';
      html += '</div>';
    }

    // 4. Footer chân thẻ: Meta info bên trái + Nút Favorite bên phải
    html += '<div class="recipe-card__footer">';
    html += '<div class="recipe-card__meta">';
    if (totalTime > 0) {
      html += '<span class="recipe-card__meta-item" title="Tổng thời gian"><i class="fa-regular fa-clock"></i> ' + totalTime + 'p</span>';
    }
    if (recipe.difficulty) {
      html += '<span class="recipe-card__meta-item" title="Độ khó"><i class="fa-solid fa-signal"></i> ' + escapeHtml(recipe.difficulty) + '</span>';
    }
    if (recipe.servings) {
      html += '<span class="recipe-card__meta-item" title="Khẩu phần"><i class="fa-solid fa-users"></i> ' + recipe.servings + ' người</span>';
    }
    html += '</div>';

    if (showActions) {
      html += '<button class="btn-favorite ' + (isFav ? 'is-favorite' : '') + '" ';
      html += 'onclick="event.preventDefault(); event.stopPropagation(); toggleFavoriteFromCard(' + recipe.id + ', this)" ';
      html += 'title="' + (isFav ? 'Bỏ yêu thích' : 'Thêm yêu thích') + '" ';
      html += 'aria-label="' + (isFav ? 'Bỏ yêu thích' : 'Thêm yêu thích') + '">';
      html += '<i class="fa-' + (isFav ? 'solid' : 'regular') + ' fa-heart"></i>';
      html += '</button>';
    }
    html += '</div>'; // .recipe-card__footer

    html += '</div>'; // .recipe-card__content
    html += '</article>';

    return html;
  },

  // ---------------------------------------------------------------
  // Category card
  // ---------------------------------------------------------------
  createCategoryCard: function (category, linkBase) {
    var url = (linkBase || getBasePath()) + 'pages/categories.html?id=' + category.id;
    var catImg = getImageUrl(category.image, getCategoryFallbackImage(category.id || category.slug));
    var html = '';
    html += '<a href="' + url + '" class="category-card">';
    html += '<div class="category-card__image">';
    html += '<img src="' + escapeHtml(catImg) + '" alt="' + escapeHtml(category.name) + '" data-category-id="' + escapeHtml(String(category.id || '')) + '" onerror="handleImageError(this, \'' + escapeHtml(String(category.id || '')) + '\')" loading="lazy">';
    html += '<span class="category-card__badge"><i class="fa-solid ' + (category.icon || 'fa-utensils') + '"></i></span>';
    html += '</div>';
    html += '<div class="category-card__content">';
    html += '<h3 class="category-card__name">' + escapeHtml(category.name) + '</h3>';
    html += '<span class="category-card__count"><i class="fa-solid fa-book-open"></i> ' + (category.recipeCount || 0) + ' công thức</span>';
    html += '</div>';
    html += '</a>';
    return html;
  },

  // Star rating (proxy to global)
  renderStars: function (rating) {
    return renderStars(rating);
  },

  // ---------------------------------------------------------------
  // Empty state
  // ---------------------------------------------------------------
  createEmptyState: function (icon, title, description, actionHtml) {
    if (!actionHtml) actionHtml = '';
    var html = '';
    html += '<div class="empty-state">';
    html += '<div class="empty-state__icon"><i class="fa-solid ' + icon + '"></i></div>';
    html += '<h3 class="empty-state__title">' + escapeHtml(title) + '</h3>';
    html += '<p class="empty-state__desc">' + escapeHtml(description) + '</p>';
    html += actionHtml;
    html += '</div>';
    return html;
  },

  // ---------------------------------------------------------------
  // Skeleton loading shimmer cards
  // ---------------------------------------------------------------
  createSkeletonCards: function (count) {
    var total = Math.max(1, Number(count) || 6);
    var html = '';
    for (var i = 0; i < total; i++) {
      html += '<div class="recipe-card recipe-card--skeleton" aria-hidden="true">';
      html += '<div class="skeleton skeleton--image"></div>';
      html += '<div class="recipe-card__content">';
      html += '<div class="skeleton skeleton--text" style="width:38%"></div>';
      html += '<div class="skeleton skeleton--title" style="width:86%"></div>';
      html += '<div class="skeleton skeleton--text" style="width:94%"></div>';
      html += '<div class="skeleton skeleton--text" style="width:62%"></div>';
      html += '</div></div>';
    }
    return html;
  },

  // ---------------------------------------------------------------
  // Windowed Pagination with Ellipsis (mobile-safe 0px overflow)
  // ---------------------------------------------------------------
  createPagination: function (currentPage, totalPages, onPageChange) {
    totalPages = Number(totalPages) || 1;
    currentPage = Math.max(1, Math.min(totalPages, Number(currentPage) || 1));
    if (totalPages <= 1) return '';

    var html = '<nav class="pagination" aria-label="Phân trang">';

    // Previous button
    html += '<button type="button" class="pagination__item pagination__prev ' + (currentPage === 1 ? 'disabled' : '') + '" ';
    if (currentPage > 1) {
      html += 'onclick="' + onPageChange + '(' + (currentPage - 1) + ')"';
    } else {
      html += 'disabled aria-disabled="true"';
    }
    html += ' aria-label="Trang trước"><i class="fa-solid fa-chevron-left"></i><span class="pagination__label"> Trước</span></button>';

    // Compute compact sliding window of visible page numbers
    var pages = [];
    if (totalPages <= 7) {
      for (var p = 1; p <= totalPages; p++) pages.push(p);
    } else {
      pages.push(1);
      var winStart = Math.max(2, currentPage - 1);
      var winEnd = Math.min(totalPages - 1, currentPage + 1);
      if (currentPage <= 3) {
        winStart = 2;
        winEnd = 4;
      } else if (currentPage >= totalPages - 2) {
        winStart = totalPages - 3;
        winEnd = totalPages - 1;
      }
      if (winStart > 2) pages.push('...');
      for (var k = winStart; k <= winEnd; k++) pages.push(k);
      if (winEnd < totalPages - 1) pages.push('...');
      pages.push(totalPages);
    }

    pages.forEach(function (entry) {
      if (entry === '...') {
        html += '<span class="pagination__ellipsis" aria-hidden="true">…</span>';
      } else {
        var active = entry === currentPage;
        html += '<button type="button" class="pagination__item ' + (active ? 'active' : '') + '" '
          + (active ? 'aria-current="page" ' : '')
          + 'onclick="' + onPageChange + '(' + entry + ')">' + entry + '</button>';
      }
    });

    // Next button
    html += '<button type="button" class="pagination__item pagination__next ' + (currentPage === totalPages ? 'disabled' : '') + '" ';
    if (currentPage < totalPages) {
      html += 'onclick="' + onPageChange + '(' + (currentPage + 1) + ')"';
    } else {
      html += 'disabled aria-disabled="true"';
    }
    html += ' aria-label="Trang sau"><span class="pagination__label">Sau </span><i class="fa-solid fa-chevron-right"></i></button>';

    html += '</nav>';
    return html;
  }
};

// ===================================================================
// Global helper functions
// ===================================================================

function renderStars(rating) {
  var stars = '';
  var num = Number(rating) || 0;
  for (var i = 1; i <= 5; i++) {
    if (i <= Math.floor(num)) {
      stars += '<i class="fa-solid fa-star star-filled"></i>';
    } else if (i - 0.5 <= num) {
      stars += '<i class="fa-solid fa-star-half-stroke star-filled"></i>';
    } else {
      stars += '<i class="fa-regular fa-star star-empty"></i>';
    }
  }
  return '<span class="stars" title="' + num.toFixed(1) + '/5 sao">' + stars + '</span>';
}

function toggleFavoriteFromCard(recipeId, btn) {
  if (!CookMateStorage.isLoggedIn()) {
    CookMateUI.showToast('Vui lòng đăng nhập để thêm yêu thích', 'warning');
    return;
  }
  btn.disabled = true;
  CookMateStorage.toggleFavorite(recipeId).then(function (result) {
    var icon = btn.querySelector('i');
    if (result.added) {
      btn.classList.add('is-favorite');
      if (icon) icon.className = 'fa-solid fa-heart';
      CookMateUI.showToast('Đã thêm vào yêu thích', 'success');
    } else {
      btn.classList.remove('is-favorite');
      if (icon) icon.className = 'fa-regular fa-heart';
      CookMateUI.showToast('Đã xóa khỏi yêu thích', 'info');
    }
    updateFavoriteBadge();
  }).catch(function (error) {
    CookMateUI.showToast(error.message || 'Không thể cập nhật yêu thích.', 'error');
  }).finally(function () { btn.disabled = false; });
}

function updateFavoriteBadge() {
  var count = CookMateStorage.getFavorites().length;
  var badge = document.getElementById('favCountBadge');
  if (badge) {
    badge.textContent = count;
    badge.style.display = count > 0 ? 'flex' : 'none';
  }
  var mobileBadge = document.getElementById('mobileFavBadge');
  if (mobileBadge) {
    mobileBadge.textContent = count;
    mobileBadge.style.display = count > 0 ? 'inline-flex' : 'none';
  }
}

// ===================================================================
// Form validation helpers
// ===================================================================

function showFieldError(input, message) {
  input.classList.add('input-error');
  var errorEl = input.parentElement.querySelector('.form-error');
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.style.display = 'block';
  }
}

function clearFieldError(input) {
  input.classList.remove('input-error');
  var errorEl = input.parentElement.querySelector('.form-error');
  if (errorEl) {
    errorEl.textContent = '';
    errorEl.style.display = 'none';
  }
}

function clearAllErrors(form) {
  form.querySelectorAll('.input-error').forEach(function (el) {
    el.classList.remove('input-error');
  });
  form.querySelectorAll('.form-error').forEach(function (el) {
    el.textContent = '';
    el.style.display = 'none';
  });
}
