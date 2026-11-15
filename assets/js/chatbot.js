// ===================================================================
// CookMate ChefBot — Trợ Lý Đầu Bếp AI (Dual-Mode Frontend + Backend)
// Tích hợp trọn vẹn 3 Nhóm Chức Năng:
//   Nhóm 1: Tủ lạnh có gì? • Thực đơn Calo/Dinh dưỡng • Quy đổi khẩu phần
//   Nhóm 2: Hỏi đáp theo món đang xem • Thay thế nguyên liệu • Cấp cứu món ăn
//   Nhóm 3: Món theo thời tiết/dịp lễ • Giỏ đi chợ gộp định lượng • Tạo nháp công thức AI
// ===================================================================

var CookMateChefBot = (function () {
  'use strict';

  var STORAGE_CHAT_KEY = 'cookmate_chefbot_history_v1';
  var STORAGE_SHOPPING_KEY = 'cookmate_chefbot_shopping_v1';
  var STORAGE_AI_DRAFT_KEY = 'cookmate_ai_recipe_draft';

  var state = {
    isOpen: false,
    activeTab: 'chat', // 'chat' | 'shopping'
    isTyping: false,
    currentRecipe: null,
    lastDraft: null
  };

  function _getBase() {
    if (typeof getBasePath === 'function') return getBasePath();
    var p = window.location.pathname.replace(/\\/g, '/');
    if (p.indexOf('/pages/admin/') !== -1 || p.indexOf('/pages/auth/') !== -1 || p.indexOf('/pages/account/') !== -1) {
      return '../../';
    }
    if (p.indexOf('/pages/') !== -1) {
      return '../';
    }
    return './';
  }

  function _escape(str) {
    if (typeof escapeHtml === 'function') return escapeHtml(String(str || ''));
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _normalizeVi(str) {
    return String(str || '')
      .toLowerCase()
      .replace(/[àáạảãâầấậẩẫăằắặẳẵ]/g, 'a')
      .replace(/[èéẹẻẽêềếệểễ]/g, 'e')
      .replace(/[ìíịỉĩ]/g, 'i')
      .replace(/[òóọỏõôồốộổỗơờớợởỡ]/g, 'o')
      .replace(/[ùúụủũưừứựửữ]/g, 'u')
      .replace(/[ỳýỵỷỹ]/g, 'y')
      .replace(/đ/g, 'd')
      .replace(/[^a-z0-9\s]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function _detectCurrentRecipe() {
    if (typeof currentRecipe !== 'undefined' && currentRecipe && currentRecipe.id) {
      return currentRecipe;
    }
    var params = new URLSearchParams(window.location.search);
    var rid = params.get('id');
    if (rid && typeof CookMateStorage !== 'undefined' && CookMateStorage.getRecipeById) {
      var r = CookMateStorage.getRecipeById(rid, true);
      if (r) return r;
    }
    return null;
  }

  // ---------------------------------------------------------------
  // Shopping List Management (Nhóm 3 - #8)
  // ---------------------------------------------------------------
  function getShoppingList() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_SHOPPING_KEY) || '[]');
    } catch (e) {
      return [];
    }
  }

  function saveShoppingList(list) {
    try {
      localStorage.setItem(STORAGE_SHOPPING_KEY, JSON.stringify(list));
    } catch (e) {}
    _updateShoppingBadge();
  }

  function addIngredientsToShoppingList(ingredients, recipeTitle) {
    var list = getShoppingList();
    var addedCount = 0;
    (ingredients || []).forEach(function (ing) {
      if (!ing || !ing.name) return;
      var normName = _normalizeVi(ing.name);
      var unit = String(ing.unit || '').trim();
      var amt = parseFloat(String(ing.amount || 0).replace(',', '.')) || 0;

      var existing = list.find(function (item) {
        return _normalizeVi(item.name) === normName && String(item.unit || '').toLowerCase() === unit.toLowerCase();
      });

      if (existing) {
        existing.amount = Math.round((existing.amount + amt) * 10) / 10;
        if (recipeTitle && existing.note.indexOf(recipeTitle) === -1) {
          existing.note += ', ' + recipeTitle;
        }
      } else {
        list.push({
          id: Date.now() + Math.floor(Math.random() * 10000),
          name: ing.name,
          amount: amt,
          unit: unit,
          checked: false,
          note: recipeTitle || 'ChefBot gợi ý'
        });
      }
      addedCount++;
    });
    saveShoppingList(list);
    if (typeof CookMateUI !== 'undefined' && CookMateUI.showToast) {
      CookMateUI.showToast('Đã gộp ' + addedCount + ' nguyên liệu vào Giỏ đi chợ ChefBot!', 'success');
    }
    if (state.activeTab === 'shopping') {
      renderShoppingTab();
    }
  }

  // ---------------------------------------------------------------
  // Local Fallback AI Engine (Works 100% offline / file:// mode)
  // ---------------------------------------------------------------
  function _localFallbackEngine(message) {
    var raw = String(message || '').trim();
    var norm = _normalizeVi(raw);
    var allRecipes = (typeof CookMateStorage !== 'undefined' && CookMateStorage.getAllRecipes)
      ? CookMateStorage.getAllRecipes()
      : [];
    var allIngs = (typeof CookMateStorage !== 'undefined' && CookMateStorage.getAllIngredients)
      ? CookMateStorage.getAllIngredients()
      : [];
    var activeRec = _detectCurrentRecipe();

    function toCard(r) {
      var nut = r.nutrition || {};
      return {
        id: r.id,
        title: r.title,
        image: r.image,
        totalTime: (parseInt(r.prepTime, 10) || 15) + (parseInt(r.cookTime, 10) || 20),
        servings: r.servings || 4,
        calories: nut.calories || r.calories || 350,
        protein: (nut.protein || 15) + (String(nut.protein || '').endsWith('g') ? '' : 'g'),
        difficulty: r.difficulty || 'Dễ',
        ingredients: r.ingredients || []
      };
    }

    // 1. AI Recipe Draft (Nhóm 3 - #9)
    if (norm.indexOf('tao nhap') !== -1 || norm.indexOf('viet cong thuc') !== -1 || norm.indexOf('tao cong thuc') !== -1) {
      var draft = {
        title: norm.indexOf('ga nuong') !== -1 ? 'Đùi Gà Nướng Mật Ong Tỏi Thơm Lừng' : 'Sườn Xào Chua Ngọt Chuẩn Vị Bắc',
        description: 'Món ngon đậm đà chuẩn định lượng do CookMate ChefBot khởi tạo tự động.',
        categoryId: 3,
        occasion: 'tiecgiadinh',
        difficulty: 'Dễ',
        prepTime: 15,
        cookTime: 25,
        servings: 4,
        image: 'https://images.unsplash.com/photo-1544025162-d76694265947?w=800&auto=format&fit=crop&q=80',
        ingredients: [
          { name: 'Sườn non heo', amount: 500, unit: 'g' },
          { name: 'Hành tím, tỏi băm', amount: 30, unit: 'g' },
          { name: 'Giấm gạo', amount: 3, unit: 'muỗng canh' },
          { name: 'Đường cát', amount: 3, unit: 'muỗng canh' },
          { name: 'Nước mắm ngon', amount: 2, unit: 'muỗng canh' },
          { name: 'Cà chua', amount: 100, unit: 'g' }
        ],
        steps: [
          { step: 1, description: 'Sườn non chặt miếng vừa ăn, chần qua nước sôi có pha chút muối và gừng để khử mùi, rửa sạch để ráo.' },
          { step: 2, description: 'Áp chảo sườn cho vàng sém 2 mặt. Pha sốt chua ngọt gồm: 3 muỗng nước, 3 muỗng đường, 3 muỗng giấm, 2 muỗng nước mắm.' },
          { step: 3, description: 'Phi thơm hành tỏi và cà chua, đổ nước sốt vào rim lửa nhỏ 15 phút đến khi sốt sánh bóng bám đều quanh miếng sườn.' }
        ]
      };
      return {
        intent: 'recipe_draft',
        reply: '✨ **ChefBot đã khởi tạo bản nháp công thức chuẩn định lượng: "' + draft.title + '"**\n\n' +
          '- **Độ khó:** ' + draft.difficulty + ' | **Chuẩn bị:** ' + draft.prepTime + 'p | **Nấu:** ' + draft.cookTime + 'p | **Khẩu phần:** ' + draft.servings + ' người\n' +
          '- **Nguyên liệu:** Sườn non heo (500g), Hành tỏi (30g), Giấm (3 muỗng), Đường (3 muỗng), Nước mắm (2 muỗng), Cà chua (100g).\n\n' +
          '👉 Nhấn nút **"Điền tự động vào Form Đăng Công Thức"** bên dưới để mở trang đăng bài với dữ liệu đã điền sẵn!',
        recipeDraft: draft,
        recipes: [],
        suggestions: ['Thực đơn 3 bữa 1500 kcal', 'Tủ lạnh có thịt bò, trứng gà', 'Canh bị mặn quá chữa sao?']
      };
    }

    // 2. Kitchen Rescue (Nhóm 2 - #6)
    if (norm.indexOf('bi man') !== -1 || norm.indexOf('man qua') !== -1 || norm.indexOf('chua man') !== -1 || norm.indexOf('com nhao') !== -1 || norm.indexOf('bi nhao') !== -1 || norm.indexOf('com khe') !== -1 || norm.indexOf('bi duc') !== -1 || norm.indexOf('bi tanh') !== -1 || norm.indexOf('cap cuu') !== -1) {
      if (norm.indexOf('nhao') !== -1 || norm.indexOf('khe') !== -1) {
        return {
          intent: 'kitchen_rescue',
          reply: '🆘 **Cấp cứu nhà bếp — Xử lý Cơm bị nhão hoặc bị khê:**\n\n' +
            '- **Cơm bị nhão:** Đặt 1–2 lát bánh mì sandwich lên mặt cơm, đậy nắp bật nút Warm 10 phút để bánh mì hút sạch hơi nước thừa.\n' +
            '- **Cơm bị khê:** Đặt ngay 1 bát nhỏ nước lạnh hoặc vài gốc hành lá tươi vào nồi cơm, đậy nắp 5 phút — mùi khê sẽ biến mất!',
          recipes: [],
          suggestions: ['Canh bị mặn quá chữa sao?', 'Hết nước cốt dừa thay bằng gì?', 'Gợi ý món dưới 400 kcal']
        };
      }
      return {
        intent: 'kitchen_rescue',
        reply: '🆘 **Cấp cứu nhà bếp — Chữa món canh/kho bị mặn & nước dùng bị đục:**\n\n' +
          '- **Món bị mặn:** Thả 2–3 lát **khoai tây sống** đã gọt vỏ vào nồi đun 10 phút rồi vớt ra (khoai tây hút muối thừa cực nhanh), hoặc thêm cà chua/nước sôi.\n' +
          '- **Nước phở/canh bị đục:** Khuấy 1 lòng trắng trứng gà vào nồi nước dùng ấm; khi sôi lòng trắng kết tủa sẽ cuốn sạch cặn đục.\n' +
          '- **Cá/Hải sản tanh:** Sơ chế với nước vo gạo hoặc gừng đập dập + chút rượu trắng.',
        recipes: [],
        suggestions: ['Cơm bị nhão làm thế nào?', 'Thay thế nước cốt dừa bằng gì?', 'Tủ lạnh có trứng, cà chua']
      };
    }

    // 3. Ingredient Substitution (Nhóm 2 - #5)
    if (norm.indexOf('thay the') !== -1 || norm.indexOf('thay bang') !== -1 || norm.indexOf('cot dua') !== -1 || norm.indexOf('mam chay') !== -1 || norm.indexOf('bot nang') !== -1) {
      return {
        intent: 'ingredient_substitution',
        reply: '🔄 **Bí quyết thay thế nguyên liệu chuẩn đầu bếp CookMate:**\n\n' +
          '- **Thay Nước cốt dừa:** Pha `200ml sữa tươi không đường + 15g bơ lạt` đun chảy (giữ được 85% độ béo thơm).\n' +
          '- **Thay Nước mắm (khi ăn chay):** Dùng `Nước tương + 1/4 muỗng muối` hoặc nước mắm chay nấu từ dứa.\n' +
          '- **Thay Bột năng ↔ Bột bắp:** Thay thế trực tiếp tỷ lệ `1:1` để tạo độ sánh cho súp/chè.\n' +
          '- **Thay Rượu nấu ăn:** Dùng `Gừng đập dập + Giấm gạo` hoặc nước cốt chanh để khử mùi tanh.',
        recipes: [],
        suggestions: ['Canh bị mặn quá chữa sao?', 'Món chay thanh đạm', 'Thực đơn 3 bữa 1500 kcal']
      };
    }

    // 4. Portion Scaling (Nhóm 1 - #3)
    var srvMatch = norm.match(/(\d+)\s*(?:nguoi|khau phan|suat)/);
    if (srvMatch || norm.indexOf('quy doi') !== -1) {
      var targetSrv = srvMatch ? Math.max(1, Math.min(50, parseInt(srvMatch[1], 10))) : 6;
      var rec = activeRec || allRecipes.find(function (r) {
        return norm.indexOf(_normalizeVi(r.title).split(' ').slice(0, 2).join(' ')) !== -1;
      }) || allRecipes[0];

      if (rec) {
        var baseSrv = rec.servings || 4;
        var ratio = Math.round((targetSrv / baseSrv) * 100) / 100;
        var ingLines = (rec.ingredients || []).map(function (ing) {
          var scaledAmt = Math.round((parseFloat(ing.amount) || 1) * ratio * 10) / 10;
          return '- **' + ing.name + ':** `' + scaledAmt + ' ' + (ing.unit || '') + '` *(gốc ' + baseSrv + ' người: ' + ing.amount + ' ' + (ing.unit || '') + ')*';
        });
        var baseCal = (rec.nutrition && rec.nutrition.calories) ? rec.nutrition.calories : (rec.calories || 350);
        return {
          intent: 'portion_scale',
          reply: '⚖️ **Bảng định lượng món "' + rec.title + '" quy đổi cho ' + targetSrv + ' người ăn** (Tỷ lệ **×' + ratio + '**):\n\n' +
            ingLines.join('\n') +
            '\n\n🔥 **Năng lượng:** `' + baseCal + ' kcal/người` (Tổng toàn nồi ' + targetSrv + ' người: **' + (baseCal * targetSrv) + ' kcal**).',
          recipes: [toCard(rec)],
          suggestions: ['Lưu nguyên liệu vào Giỏ đi chợ', 'Thực đơn 3 bữa 1500 kcal', 'Tạo nháp công thức AI']
        };
      }
    }

    // 5. Nutrition & Calorie Plan (Nhóm 1 - #2)
    if (norm.indexOf('calo') !== -1 || norm.indexOf('kcal') !== -1 || norm.indexOf('thuc don') !== -1 || norm.indexOf('giam can') !== -1 || norm.indexOf('protein') !== -1) {
      var lowCal = allRecipes.slice().sort(function (a, b) {
        var ca = (a.nutrition && a.nutrition.calories) || a.calories || 350;
        var cb = (b.nutrition && b.nutrition.calories) || b.calories || 350;
        return ca - cb;
      }).slice(0, 3);
      var totalCal = lowCal.reduce(function (s, r) {
        return s + ((r.nutrition && r.nutrition.calories) || r.calories || 300);
      }, 0);
      return {
        intent: 'nutrition_plan',
        reply: '🥗 **Thực đơn gợi ý kiểm soát Calo & cân bằng Dinh dưỡng từ CSDL CookMate:**\n\n' +
          lowCal.map(function (r, idx) {
            var c = (r.nutrition && r.nutrition.calories) || r.calories || 320;
            var p = (r.nutrition && r.nutrition.protein) || 15;
            return (idx + 1) + '. **' + r.title + '** — `' + c + ' kcal/khẩu phần` (Đạm: ' + p + 'g)';
          }).join('\n') +
          '\n\n🔥 **Tổng năng lượng 3 món:** `' + totalCal + ' kcal/người` — Phù hợp chế độ ăn lành mạnh!',
        recipes: lowCal.map(toCard),
        suggestions: ['Gộp nguyên liệu 3 món vào Giỏ đi chợ', 'Phở bò Hà Nội cho 8 người', 'Tủ lạnh có thịt bò, trứng gà']
      };
    }

    // 6. Shopping List Request (Nhóm 3 - #8)
    if (norm.indexOf('di cho') !== -1 || norm.indexOf('shopping') !== -1) {
      var picks = activeRec ? [activeRec] : allRecipes.slice(0, 2);
      var allItems = [];
      picks.forEach(function (r) {
        (r.ingredients || []).forEach(function (i) { allItems.push(i); });
      });
      addIngredientsToShoppingList(allItems, picks.map(function (p) { return p.title; }).join(', '));
      return {
        intent: 'shopping_list',
        reply: '🛒 **ChefBot đã gộp định lượng nguyên liệu của ' + picks.map(function (p) { return '"' + p.title + '"'; }).join(' & ') + ' vào tab Giỏ đi chợ!**\n\n' +
          'Bạn có thể bấm vào tab **"🛒 Giỏ đi chợ"** phía trên khung chat để đánh dấu từng món khi mua sắm hoặc sao chép danh sách.',
        recipes: picks.map(toCard),
        suggestions: ['Thực đơn 3 bữa 1500 kcal', 'Tạo nháp công thức AI', 'Canh bị mặn quá chữa sao?']
      };
    }

    // 7. Context-Aware Active Recipe Question (Nhóm 2 - #4)
    if (activeRec && (norm.indexOf('mon nay') !== -1 || norm.indexOf('buoc') !== -1 || norm.indexOf('dang xem') !== -1 || norm.indexOf('tom tat') !== -1)) {
      var stepsText = (activeRec.steps || []).map(function (s, idx) {
        return '**Bước ' + (s.step || (idx + 1)) + ':** ' + s.description;
      }).join('\n');
      return {
        intent: 'recipe_context',
        reply: '🍲 **Trợ lý Đứng bếp cho món đang mở: "' + activeRec.title + '"**\n\n' +
          '- **Thời gian:** Chuẩn bị ' + (activeRec.prepTime || 15) + 'p + Nấu ' + (activeRec.cookTime || 25) + 'p | **Khẩu phần gốc:** ' + (activeRec.servings || 4) + ' người\n\n' +
          stepsText,
        recipes: [toCard(activeRec)],
        suggestions: [
          'Quy đổi ' + activeRec.title + ' cho 8 người',
          'Hết nước cốt dừa thay bằng gì?',
          'Canh bị mặn quá chữa sao?'
        ]
      };
    }

    // 8. Fridge Ingredient Matching (Nhóm 1 - #1)
    var matchedRecipes = [];
    allRecipes.forEach(function (r) {
      var have = [];
      var miss = [];
      (r.ingredients || []).forEach(function (ing) {
        var inorm = _normalizeVi(ing.name);
        var words = inorm.split(' ').slice(0, 2).join(' ');
        if ((inorm && norm.indexOf(inorm) !== -1) || (words.length >= 4 && norm.indexOf(words) !== -1)) {
          have.push(ing.name);
        } else {
          miss.push(ing.name);
        }
      });
      if (have.length > 0) {
        matchedRecipes.push({ r: r, have: have, miss: miss });
      }
    });

    if (matchedRecipes.length > 0) {
      matchedRecipes.sort(function (a, b) { return b.have.length - a.have.length; });
      var topMatches = matchedRecipes.slice(0, 3);
      return {
        intent: 'fridge_match',
        reply: '🧊 **Từ nguyên liệu trong tủ lạnh của bạn**, ChefBot tìm thấy **' + matchedRecipes.length + ' món ăn** khớp định lượng nhất:\n\n' +
          topMatches.map(function (m, i) {
            return (i + 1) + '. **' + m.r.title + '** — Khớp **' + m.have.length + '/' + (m.r.ingredients || []).length + '** nguyên liệu (' + m.have.join(', ') + ')';
          }).join('\n'),
        recipes: topMatches.map(function (m) { return toCard(m.r); }),
        suggestions: ['Thực đơn 3 bữa 1500 kcal', 'Phở bò Hà Nội cho 8 người', 'Tạo nháp công thức AI']
      };
    }

    // Default recommendation
    var featured = allRecipes.slice(0, 3);
    return {
      intent: 'general_recommend',
      reply: '👨‍🍳 **Xin chào! Mình là CookMate ChefBot — Trợ lý Đầu bếp AI.**\n\n' +
        'Bạn có thể thử ngay 3 nhóm tính năng thông minh:\n' +
        '- 🧊 **Tủ lạnh có gì:** *"Tủ lạnh có thịt bò, trứng gà, cà chua"*\n' +
        '- 🥗 **Dinh dưỡng & Khẩu phần:** *"Thực đơn 3 bữa 1500 kcal"* hoặc *"Phở bò cho 8 người"*\n' +
        '- 🆘 **Đứng bếp & Tiện ích:** *"Canh bị mặn chữa sao?"*, *"Thay thế nước cốt dừa"*, hoặc *"Tạo nháp công thức Sườn xào chua ngọt"*',
      recipes: featured.map(toCard),
      suggestions: [
        'Tủ lạnh có thịt bò, trứng gà, cà chua',
        'Thực đơn 3 bữa 1500 kcal',
        'Phở bò Hà Nội cho 8 người',
        'Tạo nháp công thức Sườn xào chua ngọt'
      ]
    };
  }

  // ---------------------------------------------------------------
  // Inject Scoped Styles for CookMate ChefBot
  // ---------------------------------------------------------------
  function injectStyles() {
    if (document.getElementById('cmChefBotStyles')) return;
    var style = document.createElement('style');
    style.id = 'cmChefBotStyles';
    style.textContent = [
      '.cm-chefbot-launcher {',
      '  position: fixed; right: 22px; bottom: 22px; z-index: 9990;',
      '  display: inline-flex; align-items: center; gap: 10px;',
      '  background: linear-gradient(135deg, #E85D2A 0%, #C94618 100%);',
      '  color: #FFFFFF; border: none; border-radius: 999px;',
      '  padding: 12px 18px; font-family: inherit; font-size: 14px; font-weight: 700;',
      '  box-shadow: 0 10px 28px rgba(232, 93, 42, 0.38); cursor: pointer;',
      '  transition: transform 0.22s ease, box-shadow 0.22s ease;',
      '}',
      '.cm-chefbot-launcher:hover { transform: translateY(-3px); box-shadow: 0 14px 32px rgba(232, 93, 42, 0.48); }',
      '.cm-chefbot-launcher__icon {',
      '  width: 32px; height: 32px; border-radius: 50%; background: rgba(255,255,255,0.2);',
      '  display: inline-flex; align-items: center; justify-content: center; font-size: 16px;',
      '}',
      '.cm-chefbot-launcher__pulse {',
      '  width: 9px; height: 9px; border-radius: 50%; background: #4ADE80;',
      '  box-shadow: 0 0 0 4px rgba(74, 222, 128, 0.25);',
      '}',
      '.cm-chefbot-panel {',
      '  position: fixed; right: 22px; bottom: 84px; z-index: 9992;',
      '  width: 400px; max-width: calc(100vw - 24px); height: 600px; max-height: calc(100vh - 110px);',
      '  background: #FFFDF9; border: 1px solid rgba(232, 93, 42, 0.18); border-radius: 20px;',
      '  box-shadow: 0 20px 50px rgba(28, 25, 23, 0.22);',
      '  display: flex; flex-direction: column; overflow: hidden;',
      '  opacity: 0; pointer-events: none; transform: translateY(16px) scale(0.97);',
      '  transition: opacity 0.24s ease, transform 0.24s ease;',
      '}',
      '.cm-chefbot-panel.is-open { opacity: 1; pointer-events: auto; transform: translateY(0) scale(1); }',
      '.cm-chefbot-header {',
      '  background: linear-gradient(135deg, #292524 0%, #44403C 100%); color: #FFF9F2;',
      '  padding: 14px 16px; display: flex; align-items: center; justify-content: space-between; gap: 10px;',
      '}',
      '.cm-chefbot-brand { display: flex; align-items: center; gap: 10px; }',
      '.cm-chefbot-avatar {',
      '  width: 38px; height: 38px; border-radius: 12px; background: #E85D2A; color: #FFF;',
      '  display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;',
      '}',
      '.cm-chefbot-title { font-size: 15px; font-weight: 800; line-height: 1.2; color: #FFF9F2; }',
      '.cm-chefbot-subtitle { font-size: 11.5px; color: #D6D3D1; display: flex; align-items: center; gap: 5px; margin-top: 2px; }',
      '.cm-chefbot-header-actions { display: flex; align-items: center; gap: 6px; }',
      '.cm-chefbot-icon-btn {',
      '  background: rgba(255,255,255,0.12); color: #FFF9F2; border: none; width: 30px; height: 30px;',
      '  border-radius: 8px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;',
      '  font-size: 13px; transition: background 0.18s;',
      '}',
      '.cm-chefbot-icon-btn:hover { background: rgba(255,255,255,0.24); }',
      '.cm-chefbot-tabs {',
      '  display: flex; background: #F5EFE6; padding: 5px 12px; gap: 6px; border-bottom: 1px solid #E7E0D6;',
      '}',
      '.cm-chefbot-tab {',
      '  flex: 1; border: none; background: transparent; padding: 7px 10px; border-radius: 8px;',
      '  font-size: 12.5px; font-weight: 700; color: #57534E; cursor: pointer; display: flex;',
      '  align-items: center; justify-content: center; gap: 6px; transition: all 0.18s;',
      '}',
      '.cm-chefbot-tab.is-active { background: #FFFFFF; color: #E85D2A; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }',
      '.cm-chefbot-badge {',
      '  background: #E85D2A; color: #FFF; border-radius: 999px; padding: 1px 6px; font-size: 10.5px; font-weight: 800;',
      '}',
      '.cm-chefbot-context-bar {',
      '  background: #FFF7ED; border-bottom: 1px solid #FED7AA; padding: 6px 12px;',
      '  font-size: 11.5px; color: #9A3412; display: flex; align-items: center; justify-content: space-between; gap: 8px;',
      '}',
      '.cm-chefbot-messages {',
      '  flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px;',
      '}',
      '.cm-chefbot-msg { display: flex; flex-direction: column; max-width: 92%; }',
      '.cm-chefbot-msg--user { align-self: flex-end; align-items: flex-end; }',
      '.cm-chefbot-msg--bot { align-self: flex-start; align-items: flex-start; }',
      '.cm-chefbot-bubble {',
      '  padding: 11px 14px; border-radius: 15px; font-size: 13.2px; line-height: 1.55; word-break: break-word;',
      '}',
      '.cm-chefbot-msg--user .cm-chefbot-bubble {',
      '  background: #E85D2A; color: #FFFFFF; border-bottom-right-radius: 4px;',
      '}',
      '.cm-chefbot-msg--bot .cm-chefbot-bubble {',
      '  background: #FFFFFF; color: #292524; border: 1px solid #E7E0D6; border-bottom-left-radius: 4px;',
      '  box-shadow: 0 2px 8px rgba(0,0,0,0.03);',
      '}',
      '.cm-chefbot-cards { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; width: 100%; }',
      '.cm-chefbot-card {',
      '  display: flex; align-items: center; gap: 10px; background: #FFFFFF; border: 1px solid #E7E0D6;',
      '  border-radius: 12px; padding: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.04);',
      '}',
      '.cm-chefbot-card img { width: 58px; height: 58px; border-radius: 9px; object-fit: cover; flex-shrink: 0; }',
      '.cm-chefbot-card__body { flex: 1; min-width: 0; }',
      '.cm-chefbot-card__title {',
      '  font-size: 13px; font-weight: 700; color: #1C1917; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;',
      '}',
      '.cm-chefbot-card__meta { font-size: 11px; color: #78716C; margin-top: 2px; }',
      '.cm-chefbot-card__actions { display: flex; gap: 6px; margin-top: 5px; }',
      '.cm-chefbot-mini-btn {',
      '  font-size: 11px; font-weight: 700; padding: 4px 8px; border-radius: 6px; text-decoration: none;',
      '  border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;',
      '}',
      '.cm-chefbot-mini-btn--primary { background: #FFF0EB; color: #E85D2A; }',
      '.cm-chefbot-mini-btn--green { background: #ECFDF5; color: #2E7D4F; }',
      '.cm-chefbot-draft-btn {',
      '  margin-top: 8px; width: 100%; padding: 10px 12px; border-radius: 10px; border: none;',
      '  background: linear-gradient(135deg, #2E7D4F 0%, #1E5635 100%); color: #FFF;',
      '  font-weight: 700; font-size: 12.8px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;',
      '}',
      '.cm-chefbot-chips {',
      '  display: flex; gap: 6px; overflow-x: auto; padding: 8px 12px; background: #FAF6F0;',
      '  border-top: 1px solid #EFEAE1; scrollbar-width: none;',
      '}',
      '.cm-chefbot-chips::-webkit-scrollbar { display: none; }',
      '.cm-chefbot-chip {',
      '  white-space: nowrap; border: 1px solid #E2D9CC; background: #FFFFFF; color: #44403C;',
      '  border-radius: 999px; padding: 5px 11px; font-size: 11.5px; font-weight: 600; cursor: pointer;',
      '  transition: all 0.15s;',
      '}',
      '.cm-chefbot-chip:hover { border-color: #E85D2A; color: #E85D2A; background: #FFF7ED; }',
      '.cm-chefbot-input-bar {',
      '  display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #FFFFFF; border-top: 1px solid #E7E0D6;',
      '}',
      '.cm-chefbot-input {',
      '  flex: 1; border: 1px solid #D6D3D1; border-radius: 999px; padding: 9px 14px;',
      '  font-size: 13px; font-family: inherit; outline: none;',
      '}',
      '.cm-chefbot-input:focus { border-color: #E85D2A; box-shadow: 0 0 0 3px rgba(232, 93, 42, 0.12); }',
      '.cm-chefbot-send {',
      '  width: 36px; height: 36px; border-radius: 50%; border: none; background: #E85D2A; color: #FFF;',
      '  cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;',
      '}',
      '.cm-chefbot-shopping { flex: 1; overflow-y: auto; padding: 14px; display: none; flex-direction: column; gap: 10px; }',
      '.cm-chefbot-shop-item {',
      '  display: flex; align-items: center; justify-content: space-between; gap: 8px;',
      '  background: #FFF; border: 1px solid #E7E0D6; padding: 9px 12px; border-radius: 10px; font-size: 13px;',
      '}',
      '.cm-chefbot-shop-item.is-checked { opacity: 0.55; text-decoration: line-through; }',
      '@media (max-width: 640px) {',
      '  .cm-chefbot-launcher { right: 14px; bottom: 14px; padding: 10px 14px; }',
      '  .cm-chefbot-launcher__label { display: none; }',
      '  .cm-chefbot-panel { right: 10px; left: 10px; bottom: 72px; width: auto; max-width: none; height: 74vh; }',
      '}'
    ].join('\n');
    document.head.appendChild(style);
  }

  function _formatMarkdown(text) {
    var safe = _escape(text || '');
    safe = safe.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    safe = safe.replace(/\*(.+?)\*/g, '<em>$1</em>');
    safe = safe.replace(/`(.+?)`/g, '<code style="background:#FFF0EB;color:#C94618;padding:1px 5px;border-radius:4px;font-weight:700;">$1</code>');
    safe = safe.replace(/\n/g, '<br>');
    return safe;
  }

  function _updateShoppingBadge() {
    var badge = document.getElementById('cmChefBotShopBadge');
    if (!badge) return;
    var count = getShoppingList().length;
    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline-block' : 'none';
  }

  // ---------------------------------------------------------------
  // Build Widget DOM
  // ---------------------------------------------------------------
  function buildWidget() {
    if (document.getElementById('cmChefBotLauncher')) return;
    injectStyles();

    state.currentRecipe = _detectCurrentRecipe();

    var launcher = document.createElement('button');
    launcher.id = 'cmChefBotLauncher';
    launcher.className = 'cm-chefbot-launcher';
    launcher.type = 'button';
    launcher.setAttribute('aria-label', 'Mở Trợ lý Đầu bếp AI CookMate ChefBot');
    launcher.innerHTML =
      '<span class="cm-chefbot-launcher__icon"><i class="fa-solid fa-robot"></i></span>' +
      '<span class="cm-chefbot-launcher__label">Trợ lý Đầu bếp AI</span>' +
      '<span class="cm-chefbot-launcher__pulse"></span>';

    var panel = document.createElement('section');
    panel.id = 'cmChefBotPanel';
    panel.className = 'cm-chefbot-panel';
    panel.setAttribute('aria-label', 'Cửa sổ Trợ lý Đầu bếp AI CookMate');

    var contextHtml = '';
    if (state.currentRecipe) {
      contextHtml =
        '<div class="cm-chefbot-context-bar" id="cmChefBotContextBar">' +
          '<span><i class="fa-solid fa-bowl-food"></i> Đang xem: <strong>' + _escape(state.currentRecipe.title) + '</strong></span>' +
          '<button type="button" class="cm-chefbot-mini-btn cm-chefbot-mini-btn--primary" id="cmAskCurrentBtn">Hỏi món này</button>' +
        '</div>';
    }

    panel.innerHTML =
      '<div class="cm-chefbot-header">' +
        '<div class="cm-chefbot-brand">' +
          '<div class="cm-chefbot-avatar"><i class="fa-solid fa-utensils"></i></div>' +
          '<div>' +
            '<div class="cm-chefbot-title">CookMate ChefBot AI</div>' +
            '<div class="cm-chefbot-subtitle"><span class="cm-chefbot-launcher__pulse"></span> Trợ lý Định lượng • Dinh dưỡng • Đứng bếp</div>' +
          '</div>' +
        '</div>' +
        '<div class="cm-chefbot-header-actions">' +
          '<button type="button" class="cm-chefbot-icon-btn" id="cmChefBotResetBtn" title="Xóa lịch sử trò chuyện"><i class="fa-solid fa-rotate-right"></i></button>' +
          '<button type="button" class="cm-chefbot-icon-btn" id="cmChefBotCloseBtn" title="Thu gọn"><i class="fa-solid fa-xmark"></i></button>' +
        '</div>' +
      '</div>' +
      '<div class="cm-chefbot-tabs">' +
        '<button type="button" class="cm-chefbot-tab is-active" id="cmTabChat"><i class="fa-solid fa-comments"></i> Trò chuyện AI</button>' +
        '<button type="button" class="cm-chefbot-tab" id="cmTabShopping"><i class="fa-solid fa-basket-shopping"></i> Giỏ đi chợ <span class="cm-chefbot-badge" id="cmChefBotShopBadge" style="display:none">0</span></button>' +
      '</div>' +
      contextHtml +
      '<div class="cm-chefbot-messages" id="cmChefBotMessages"></div>' +
      '<div class="cm-chefbot-shopping" id="cmChefBotShopping"></div>' +
      '<div class="cm-chefbot-chips" id="cmChefBotChips">' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Tủ lạnh có thịt bò, trứng gà, cà chua">🧊 Tủ lạnh có gì?</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Lên thực đơn 3 bữa 1500 kcal">🥗 Thực đơn 1500 kcal</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Phở bò Hà Nội cho 8 người ăn">⚖️ Quy đổi 8 người</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Canh bị mặn quá chữa sao?">🆘 Cấp cứu món mặn</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Hết nước cốt dừa thay bằng gì?">🔄 Nguyên liệu thay thế</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Tạo nháp công thức Sườn xào chua ngọt">✨ Tạo nháp công thức AI</button>' +
      '</div>' +
      '<form class="cm-chefbot-input-bar" id="cmChefBotForm">' +
        '<input type="text" class="cm-chefbot-input" id="cmChefBotInput" placeholder="Nhập nguyên liệu, số người ăn, câu hỏi bếp..." autocomplete="off" />' +
        '<button type="submit" class="cm-chefbot-send" aria-label="Gửi tin nhắn"><i class="fa-solid fa-paper-plane"></i></button>' +
      '</form>';

    document.body.appendChild(launcher);
    document.body.appendChild(panel);

    _bindWidgetEvents(launcher, panel);
    _updateShoppingBadge();

    // Greet user on initial load
    appendBotResponse({
      reply:
        'Xin chào! Mình là **CookMate ChefBot — Trợ lý Đầu bếp AI** 👨‍🍳.\n' +
        'Mình đã tích hợp đầy đủ **3 nhóm tính năng thông minh**:\n' +
        '1. 🧊 **Tủ lạnh & Định lượng:** Tìm món từ nguyên liệu sẵn có, lên thực đơn Calo, quy đổi khẩu phần tức thì.\n' +
        '2. 🆘 **Trợ lý Đứng bếp:** Giải đáp từng bước món đang xem, gợi ý nguyên liệu thay thế, chữa món mặn/nhão/khê.\n' +
        '3. 🛒 **Tiện ích AI:** Gộp danh sách đi chợ tự động & tạo nháp công thức mới điền 1-click vào Form!'
    });
  }

  function _bindWidgetEvents(launcher, panel) {
    launcher.addEventListener('click', function () {
      state.isOpen = !state.isOpen;
      panel.classList.toggle('is-open', state.isOpen);
      if (state.isOpen) {
        var inp = document.getElementById('cmChefBotInput');
        if (inp) setTimeout(function () { inp.focus(); }, 150);
      }
    });

    document.getElementById('cmChefBotCloseBtn').addEventListener('click', function () {
      state.isOpen = false;
      panel.classList.remove('is-open');
    });

    document.getElementById('cmChefBotResetBtn').addEventListener('click', function () {
      var msgBox = document.getElementById('cmChefBotMessages');
      if (msgBox) msgBox.innerHTML = '';
      sendPrompt('');
    });

    document.getElementById('cmTabChat').addEventListener('click', function () {
      switchTab('chat');
    });

    document.getElementById('cmTabShopping').addEventListener('click', function () {
      switchTab('shopping');
    });

    var askCurrentBtn = document.getElementById('cmAskCurrentBtn');
    if (askCurrentBtn && state.currentRecipe) {
      askCurrentBtn.addEventListener('click', function () {
        switchTab('chat');
        sendPrompt('Tóm tắt các bước nấu và dinh dưỡng món ' + state.currentRecipe.title);
      });
    }

    document.getElementById('cmChefBotChips').addEventListener('click', function (e) {
      var chip = e.target.closest('.cm-chefbot-chip');
      if (!chip) return;
      var promptText = chip.getAttribute('data-prompt');
      if (promptText) {
        switchTab('chat');
        sendPrompt(promptText);
      }
    });

    document.getElementById('cmChefBotForm').addEventListener('submit', function (e) {
      e.preventDefault();
      var inp = document.getElementById('cmChefBotInput');
      if (!inp) return;
      var val = inp.value.trim();
      if (!val) return;
      inp.value = '';
      switchTab('chat');
      sendPrompt(val);
    });
  }

  function switchTab(tab) {
    state.activeTab = tab;
    var tabChat = document.getElementById('cmTabChat');
    var tabShop = document.getElementById('cmTabShopping');
    var msgBox = document.getElementById('cmChefBotMessages');
    var shopBox = document.getElementById('cmChefBotShopping');
    var chipsBar = document.getElementById('cmChefBotChips');
    var formBar = document.getElementById('cmChefBotForm');

    if (tab === 'shopping') {
      tabChat.classList.remove('is-active');
      tabShop.classList.add('is-active');
      msgBox.style.display = 'none';
      chipsBar.style.display = 'none';
      formBar.style.display = 'none';
      shopBox.style.display = 'flex';
      renderShoppingTab();
    } else {
      tabChat.classList.add('is-active');
      tabShop.classList.remove('is-active');
      msgBox.style.display = 'flex';
      chipsBar.style.display = 'flex';
      formBar.style.display = 'flex';
      shopBox.style.display = 'none';
    }
  }

  function renderShoppingTab() {
    var shopBox = document.getElementById('cmChefBotShopping');
    if (!shopBox) return;
    var list = getShoppingList();

    if (list.length === 0) {
      shopBox.innerHTML =
        '<div style="text-align:center;padding:36px 16px;color:#78716C;">' +
          '<i class="fa-solid fa-basket-shopping" style="font-size:36px;color:#E85D2A;margin-bottom:10px;"></i>' +
          '<p style="font-weight:700;color:#292524;margin-bottom:4px;">Giỏ đi chợ của bạn đang trống</p>' +
          '<p style="font-size:12px;">Hãy nhấn nút <strong>"+ Đi chợ"</strong> trên thẻ món ăn trong cuộc trò chuyện hoặc nhắn <em>"Lập danh sách đi chợ"</em> cho ChefBot nhé!</p>' +
        '</div>';
      return;
    }

    var itemsHtml = list.map(function (item) {
      return (
        '<div class="cm-chefbot-shop-item ' + (item.checked ? 'is-checked' : '') + '" data-id="' + item.id + '">' +
          '<label style="display:flex;align-items:center;gap:8px;cursor:pointer;flex:1;">' +
            '<input type="checkbox" class="cm-shop-check" data-id="' + item.id + '" ' + (item.checked ? 'checked' : '') + ' />' +
            '<span><strong>' + _escape(item.name) + '</strong> — <code style="color:#E85D2A;font-weight:700;">' + _escape(item.amount) + ' ' + _escape(item.unit) + '</code></span>' +
          '</label>' +
          '<button type="button" class="cm-shop-del" data-id="' + item.id + '" style="background:none;border:none;color:#EF4444;cursor:pointer;"><i class="fa-solid fa-trash"></i></button>' +
        '</div>'
      );
    }).join('');

    shopBox.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
        '<strong style="font-size:13px;color:#292524;">Tổng cộng: ' + list.length + ' nguyên liệu cần mua</strong>' +
        '<div style="display:flex;gap:6px;">' +
          '<button type="button" id="cmCopyShopBtn" class="cm-chefbot-mini-btn cm-chefbot-mini-btn--green"><i class="fa-regular fa-copy"></i> Sao chép</button>' +
          '<button type="button" id="cmClearShopBtn" class="cm-chefbot-mini-btn cm-chefbot-mini-btn--primary"><i class="fa-solid fa-trash-can"></i> Xóa hết</button>' +
        '</div>' +
      '</div>' +
      itemsHtml;

    shopBox.querySelectorAll('.cm-shop-check').forEach(function (chk) {
      chk.addEventListener('change', function () {
        var id = Number(chk.getAttribute('data-id'));
        var current = getShoppingList();
        current.forEach(function (it) {
          if (it.id === id) it.checked = chk.checked;
        });
        saveShoppingList(current);
        renderShoppingTab();
      });
    });

    shopBox.querySelectorAll('.cm-shop-del').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = Number(btn.getAttribute('data-id'));
        var filtered = getShoppingList().filter(function (it) { return it.id !== id; });
        saveShoppingList(filtered);
        renderShoppingTab();
      });
    });

    var copyBtn = document.getElementById('cmCopyShopBtn');
    if (copyBtn) {
      copyBtn.addEventListener('click', function () {
        var text = getShoppingList().map(function (i) {
          return '- ' + i.name + ': ' + i.amount + ' ' + i.unit;
        }).join('\n');
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text);
        }
        if (typeof CookMateUI !== 'undefined' && CookMateUI.showToast) {
          CookMateUI.showToast('Đã sao chép danh sách đi chợ vào bộ nhớ tạm!', 'success');
        }
      });
    }

    var clearBtn = document.getElementById('cmClearShopBtn');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        saveShoppingList([]);
        renderShoppingTab();
      });
    }
  }

  function appendUserMessage(text) {
    var msgBox = document.getElementById('cmChefBotMessages');
    if (!msgBox || !text) return;
    var el = document.createElement('div');
    el.className = 'cm-chefbot-msg cm-chefbot-msg--user';
    el.innerHTML = '<div class="cm-chefbot-bubble">' + _escape(text) + '</div>';
    msgBox.appendChild(el);
    msgBox.scrollTop = msgBox.scrollHeight;
  }

  function appendBotResponse(data) {
    var msgBox = document.getElementById('cmChefBotMessages');
    if (!msgBox || !data) return;

    var base = _getBase();
    var wrapper = document.createElement('div');
    wrapper.className = 'cm-chefbot-msg cm-chefbot-msg--bot';

    var html = '<div class="cm-chefbot-bubble">' + _formatMarkdown(data.reply || '') + '</div>';

    // Render Mini Recipe Cards if any
    if (Array.isArray(data.recipes) && data.recipes.length > 0) {
      html += '<div class="cm-chefbot-cards">';
      data.recipes.forEach(function (r, idx) {
        var detailUrl = base + 'pages/recipe-detail.html?id=' + encodeURIComponent(r.id);
        html +=
          '<div class="cm-chefbot-card">' +
            '<img src="' + _escape(r.image) + '" alt="' + _escape(r.title) + '" onerror="this.src=\'' + base + 'assets/images/placeholders/recipe-placeholder.svg\'" />' +
            '<div class="cm-chefbot-card__body">' +
              '<div class="cm-chefbot-card__title">' + _escape(r.title) + '</div>' +
              '<div class="cm-chefbot-card__meta"><i class="fa-solid fa-fire text-primary"></i> ' + _escape(r.calories) + ' kcal • <i class="fa-regular fa-clock"></i> ' + _escape(r.totalTime) + ' phút • ' + _escape(r.servings) + ' người</div>' +
              '<div class="cm-chefbot-card__actions">' +
                '<a href="' + detailUrl + '" class="cm-chefbot-mini-btn cm-chefbot-mini-btn--primary"><i class="fa-solid fa-eye"></i> Xem món</a>' +
                '<button type="button" class="cm-chefbot-mini-btn cm-chefbot-mini-btn--green cm-add-shop-btn" data-recipe-idx="' + idx + '"><i class="fa-solid fa-cart-plus"></i> + Đi chợ</button>' +
              '</div>' +
            '</div>' +
          '</div>';
      });
      html += '</div>';
    }

    // Render 1-Click Auto-Fill Recipe Draft Button if present (Nhóm 3 - #9)
    if (data.recipeDraft) {
      state.lastDraft = data.recipeDraft;
      html +=
        '<button type="button" class="cm-chefbot-draft-btn" id="cmApplyAiDraftBtn">' +
          '<i class="fa-solid fa-wand-magic-sparkles"></i> Điền tự động vào Form Đăng Công Thức' +
        '</button>';
    }

    wrapper.innerHTML = html;
    msgBox.appendChild(wrapper);

    // Bind "+ Đi chợ" buttons inside cards
    if (Array.isArray(data.recipes) && data.recipes.length > 0) {
      wrapper.querySelectorAll('.cm-add-shop-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var idx = parseInt(btn.getAttribute('data-recipe-idx'), 10);
          var rec = data.recipes[idx];
          if (rec) {
            addIngredientsToShoppingList(rec.ingredients || [], rec.title);
          }
        });
      });
    }

    // Bind Shopping List auto-merge if returned directly
    if (Array.isArray(data.shoppingList) && data.shoppingList.length > 0) {
      addIngredientsToShoppingList(data.shoppingList, 'Thực đơn ChefBot');
    }

    // Bind 1-Click AI Draft Fill button
    var draftBtn = wrapper.querySelector('#cmApplyAiDraftBtn');
    if (draftBtn && data.recipeDraft) {
      draftBtn.addEventListener('click', function () {
        applyAiRecipeDraft(data.recipeDraft);
      });
    }

    // Update quick suggestion chips dynamically if provided
    if (Array.isArray(data.suggestions) && data.suggestions.length > 0) {
      var chipsBar = document.getElementById('cmChefBotChips');
      if (chipsBar) {
        chipsBar.innerHTML = data.suggestions.map(function (s) {
          return '<button type="button" class="cm-chefbot-chip" data-prompt="' + _escape(s) + '">✨ ' + _escape(s) + '</button>';
        }).join('');
      }
    }

    msgBox.scrollTop = msgBox.scrollHeight;
  }

  function sendPrompt(text) {
    if (text) {
      appendUserMessage(text);
    }
    var activeRec = _detectCurrentRecipe();
    var contextPayload = {
      recipeId: activeRec ? activeRec.id : null,
      pagePath: window.location.pathname
    };

    var isHttp = window.location.protocol === 'http:' || window.location.protocol === 'https:';
    if (isHttp && typeof fetch === 'function') {
      fetch('/api/chatbot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, context: contextPayload })
      })
        .then(function (res) {
          if (!res.ok) throw new Error('Fallback to local engine');
          return res.json();
        })
        .then(function (data) {
          appendBotResponse(data);
        })
        .catch(function () {
          var localRes = _localFallbackEngine(text);
          appendBotResponse(localRes);
        });
    } else {
      var localRes = _localFallbackEngine(text);
      appendBotResponse(localRes);
    }
  }

  // ---------------------------------------------------------------
  // 1-Click Auto-Fill Recipe Draft into pages/account/recipe-form.html
  // ---------------------------------------------------------------
  function applyAiRecipeDraft(draft) {
    if (!draft) return;
    try {
      sessionStorage.setItem(STORAGE_AI_DRAFT_KEY, JSON.stringify(draft));
    } catch (e) {}

    // If already on recipe-form.html, fill immediately
    if (document.getElementById('recipeForm') && document.getElementById('recipeTitle')) {
      _fillRecipeFormFields(draft);
      if (typeof CookMateUI !== 'undefined' && CookMateUI.showToast) {
        CookMateUI.showToast('ChefBot đã điền tự động công thức "' + draft.title + '" vào biểu mẫu!', 'success');
      }
      return;
    }

    var base = _getBase();
    window.location.href = base + 'pages/account/recipe-form.html?aiDraft=1';
  }

  function _fillRecipeFormFields(draft) {
    if (!draft) return;
    var setVal = function (id, val) {
      var el = document.getElementById(id);
      if (el && val !== undefined && val !== null) {
        el.value = val;
        el.dispatchEvent(new Event('input'));
      }
    };
    setVal('recipeTitle', draft.title);
    setVal('recipeDescription', draft.description);
    setVal('recipeCategory', draft.categoryId || 3);
    setVal('recipeOccasion', draft.occasion || '');
    setVal('recipeDifficulty', draft.difficulty || 'Dễ');
    setVal('recipePrepTime', draft.prepTime || 15);
    setVal('recipeCookTime', draft.cookTime || 25);
    setVal('recipeServings', draft.servings || 4);
    setVal('recipeImage', draft.image || '');

    var ingContainer = document.getElementById('ingredientsList');
    if (ingContainer && typeof addIngredientRow === 'function' && Array.isArray(draft.ingredients)) {
      ingContainer.innerHTML = '';
      draft.ingredients.forEach(function (ing) {
        addIngredientRow(ing);
      });
    }

    var stepContainer = document.getElementById('stepsList');
    if (stepContainer && typeof addStepRow === 'function' && Array.isArray(draft.steps)) {
      stepContainer.innerHTML = '';
      draft.steps.forEach(function (st) {
        addStepRow(st);
      });
    }
  }

  function checkAndAutoFillDraftOnFormPage() {
    if (!document.getElementById('recipeForm') || !document.getElementById('recipeTitle')) return;
    try {
      var raw = sessionStorage.getItem(STORAGE_AI_DRAFT_KEY);
      if (!raw) return;
      var draft = JSON.parse(raw);
      sessionStorage.removeItem(STORAGE_AI_DRAFT_KEY);
      setTimeout(function () {
        _fillRecipeFormFields(draft);
        if (typeof CookMateUI !== 'undefined' && CookMateUI.showToast) {
          CookMateUI.showToast('✨ ChefBot AI đã điền sẵn công thức "' + draft.title + '" cho bạn!', 'success');
        }
      }, 250);
    } catch (e) {}
  }

  function init() {
    // Do not mount floating widget on login/register pages to keep Pho Auth V2 clean
    var path = window.location.pathname.replace(/\\/g, '/');
    if (path.indexOf('/pages/auth/') !== -1) return;

    buildWidget();
    checkAndAutoFillDraftOnFormPage();
  }

  return {
    init: init,
    sendPrompt: sendPrompt,
    addIngredientsToShoppingList: addIngredientsToShoppingList,
    applyAiRecipeDraft: applyAiRecipeDraft
  };
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () {
    CookMateChefBot.init();
  });
} else {
  CookMateChefBot.init();
}
