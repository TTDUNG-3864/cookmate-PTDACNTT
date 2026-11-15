// ===================================================================
// CookMate ChefBot — Trợ Lý AI Chuyên Giải Đáp Về Món Ăn (Nhóm 1 & Nhóm 2)
// Tập trung chuyên sâu vào ẩm thực & nấu nướng:
//   Nhóm 1: Có nguyên liệu này nấu món gì? • Tư vấn Calo/Dinh dưỡng • Quy đổi khẩu phần
//   Nhóm 2: Xử lý sự cố món ăn (cháy, mặn, nhão, khê, đục, dai, tanh) •
//           Thay thế nguyên liệu khi thiếu • Hỏi đáp chi tiết món ăn đang xem
// ===================================================================

var CookMateChefBot = (function () {
  'use strict';

  var state = {
    isOpen: false,
    currentRecipe: null
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
  // Local Fallback Culinary AI Engine (Nhóm 1 & Nhóm 2 - Offline / file://)
  // ---------------------------------------------------------------
  function _localFallbackEngine(message) {
    var raw = String(message || '').trim();
    var norm = _normalizeVi(raw);
    var allRecipes = (typeof CookMateStorage !== 'undefined' && CookMateStorage.getAllRecipes)
      ? CookMateStorage.getAllRecipes()
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
        difficulty: r.difficulty || 'Dễ'
      };
    }

    // 0. Guardrail: Từ chối lịch sự câu hỏi ngoài phạm vi món ăn
    var offTopic = ['lap trinh', 'code python', 'javascript', 'toan hoc', 'giai phuong trinh', 'chinh tri', 'chung khoan', 'bitcoin', 'bong da'];
    if (offTopic.some(function (k) { return norm.indexOf(k) !== -1; })) {
      return {
        intent: 'off_topic',
        reply: '🙏 Xin lỗi bạn, mình là **Trợ lý Đầu bếp AI của CookMate** nên **chỉ giải đáp các câu hỏi về món ăn, nguyên liệu, dinh dưỡng và kỹ thuật nấu nướng**.\n\n' +
          'Bạn hãy thử hỏi mình:\n' +
          '- *"Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?"*\n' +
          '- *"Khi làm món ăn bị cháy thì xử lý như nào?"*\n' +
          '- *"Thiếu nước cốt dừa thì thay thế bằng gì?"*',
        recipes: [],
        suggestions: [
          'Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?',
          'Khi làm món ăn bị cháy thì xử lý như nào?',
          'Thiếu nước cốt dừa thì thay bằng gì?'
        ]
      };
    }

    // 1. Xử lý sự cố nhà bếp (Nhóm 2: Cháy, khê, mặn, nhão, đục, dai, tanh...)
    if (
      norm.indexOf('bi chay') !== -1 || norm.indexOf('chay noi') !== -1 || norm.indexOf('chay khet') !== -1 ||
      norm.indexOf('bi khe') !== -1 || norm.indexOf('com khe') !== -1 || norm.indexOf('bi man') !== -1 ||
      norm.indexOf('man qua') !== -1 || norm.indexOf('chua man') !== -1 || norm.indexOf('com nhao') !== -1 ||
      norm.indexOf('bi nhao') !== -1 || norm.indexOf('bi duc') !== -1 || norm.indexOf('nuoc pho duc') !== -1 ||
      norm.indexOf('bi dai') !== -1 || norm.indexOf('thit dai') !== -1 || norm.indexOf('bi tanh') !== -1 ||
      norm.indexOf('ca tanh') !== -1 || norm.indexOf('cap cuu') !== -1
    ) {
      if (norm.indexOf('chay') !== -1 || norm.indexOf('khet') !== -1 || norm.indexOf('khe') !== -1) {
        return {
          intent: 'kitchen_rescue',
          reply: '🆘 **Xử lý sự cố món ăn — Món ăn / Nồi kho / Cơm bị cháy hoặc có mùi khê khét:**\n\n' +
            '- **Bước 1 — Tắt bếp ngay & TUYỆT ĐỐI KHÔNG ĐẢO/KHUẤY:** Đừng cạo đáy nồi vì vị đắng và cặn đen sẽ lan ra toàn bộ món ăn.\n' +
            '- **Bước 2 — Gắp phần chưa cháy sang nồi sạch mới:** Nhẹ nhàng lấy phần thức ăn phía trên sang nồi khác.\n' +
            '- **Bước 3 — Khử mùi khê tức thì:**\n' +
            '  • *Với cơm bị khê:* Đặt **1–2 lát bánh mì sandwich** hoặc **vài gốc hành lá tươi** lên mặt cơm, đậy nắp 5–10 phút để hút sạch mùi khê.\n' +
            '  • *Với món kho bị cháy sốt:* Pha lại nước sốt mới (nước dừa/nước lọc + chút nước mắm + đường + gừng/hành tím) đun nhỏ lửa 5 phút.\n' +
            '- **Bước 4 — Làm sạch nồi cháy dễ dàng:** Đun sôi nước với `2 muỗng Baking Soda + 3 muỗng giấm trắng` trong nồi 5 phút, vết cháy sẽ tự bong ra!',
          recipes: [],
          suggestions: ['Canh bị mặn quá chữa sao?', 'Cơm bị nhão xử lý thế nào?', 'Thiếu nước cốt dừa thay bằng gì?']
        };
      }
      if (norm.indexOf('nhao') !== -1) {
        return {
          intent: 'kitchen_rescue',
          reply: '🆘 **Xử lý sự cố món ăn — Cơm bị nhão hoặc bị sống:**\n\n' +
            '- **Cơm bị nhão:** Mở nắp thoát hơi, đặt **1–2 lát bánh mì ruột trắng** lên mặt cơm, đậy nắp bật chế độ `Warm` 10 phút để hút hết nước thừa.\n' +
            '- **Cơm bị sống / sượng:** Xới tơi cơm, rưới đều `2 muỗng canh nước ấm + 1 muỗng cà phê rượu trắng` rồi bấm nấu lại.',
          recipes: [],
          suggestions: ['Khi làm món ăn bị cháy xử lý như nào?', 'Canh bị mặn quá chữa sao?', 'Nước phở bị đục làm sao cho trong?']
        };
      }
      if (norm.indexOf('duc') !== -1) {
        return {
          intent: 'kitchen_rescue',
          reply: '🆘 **Xử lý sự cố món ăn — Nước dùng Phở / Canh hầm xương bị đục:**\n\n' +
            '- **Tuyệt chiêu lòng trắng trứng:** Đánh tan `1 lòng trắng trứng gà`, đổ vào nồi nước dùng đang ấm rồi khuấy đều. Khi sôi lăn tăn, lòng trắng đông tụ sẽ cuốn sạch toàn bộ cặn đục — chỉ cần vớt bỏ là nước dùng trong veo!\n' +
            '- **Thả vài lát khoai tây sống hoặc củ cải trắng:** Giúp hút cặn và làm ngọt nước.',
          recipes: [],
          suggestions: ['Thịt bò bị dai xử lý sao?', 'Khi làm món ăn bị cháy xử lý như nào?', 'Canh bị mặn quá chữa sao?']
        };
      }
      if (norm.indexOf('dai') !== -1) {
        return {
          intent: 'kitchen_rescue',
          reply: '🆘 **Xử lý sự cố món ăn — Thịt bò / Thịt hầm bị dai cứng:**\n\n' +
            '- **Khi đang hầm:** Cho vào nồi `vài lát dứa (thơm) chín`, `1 miếng đu đủ xanh nhỏ` hoặc `1 muỗng cà phê nước cốt chanh` — enzyme tự nhiên giúp thịt mềm nhanh gấp đôi.\n' +
            '- **Khi ướp thịt bò xào:** Thái ngang thớ, ướp với `1 muỗng dầu ăn + chút bột bắp`, chỉ nêm nước mắm khi xào lửa lớn gần chín.',
          recipes: [],
          suggestions: ['Khi làm món ăn bị cháy xử lý như nào?', 'Cá bị tanh khử mùi sao?', 'Thiếu bột năng thay bằng gì?']
        };
      }
      return {
        intent: 'kitchen_rescue',
        reply: '🆘 **Xử lý sự cố món ăn — Món canh / Món kho bị mặn quá:**\n\n' +
          '- **Mẹo khoai tây sống (Hiệu quả nhất):** Gọt vỏ `1 củ khoai tây sống`, cắt lát dày thả vào nồi canh/nồi kho đun 10 phút rồi vớt ra — khoai tây sẽ hút bớt muối thừa cực nhạy!\n' +
          '- **Với món canh:** Châm thêm nước sôi + cà chua hoặc đậu hũ non.\n' +
          '- **Với món kho:** Thêm nước dừa tươi (hoặc nước lọc) + `1 muỗng cà phê đường phèn` để cân bằng vị mặn.',
        recipes: [],
        suggestions: ['Khi làm món ăn bị cháy xử lý như nào?', 'Cơm bị nhão xử lý thế nào?', 'Thiếu nước cốt dừa thay bằng gì?']
      };
    }

    // 2. Thay thế nguyên liệu khi thiếu (Nhóm 2)
    if (norm.indexOf('thay') !== -1 || norm.indexOf('thieu') !== -1 || norm.indexOf('het ') !== -1 || norm.indexOf('khong co') !== -1) {
      if (norm.indexOf('cot dua') !== -1) {
        return {
          intent: 'ingredient_substitution',
          reply: '🔄 **Gợi ý thay thế khi thiếu "Nước cốt dừa":**\n\n' +
            '- **Sữa tươi không đường + Bơ lạt (Khuyên dùng):** Pha `200ml sữa tươi không đường + 15g bơ lạt` đun chảy (giữ được 85–90% độ béo ngậy cho món cà ri, kho, bánh).\n' +
            '- **Sữa đặc + Sữa tươi:** Pha `180ml sữa tươi + 2 muỗng canh sữa đặc` cho các món chè.\n' +
            '- **Kem tươi (Whipping Cream):** Thay thế tỷ lệ `1:1` cho món súp hoặc cà ri.',
          recipes: [],
          suggestions: ['Thiếu bột năng thay bằng gì?', 'Ăn chay thay nước mắm bằng gì?', 'Không có rượu nấu ăn khử mùi bằng gì?']
        };
      }
      if (norm.indexOf('bot nang') !== -1 || norm.indexOf('bot bap') !== -1) {
        return {
          intent: 'ingredient_substitution',
          reply: '🔄 **Gợi ý thay thế khi thiếu "Bột năng / Bột bắp":**\n\n' +
            '- **Bột bắp ↔ Bột năng:** Thay thế trực tiếp tỷ lệ `1:1` (hoà với nước lạnh trước khi cho vào nồi đang sôi).\n' +
            '- **Bột sắn dây:** Thay tỷ lệ `1:1`, rất hợp cho các món chè và súp.\n' +
            '- **Bột mì đa dụng:** Dùng tỷ lệ `2 muỗng bột mì = 1 muỗng bột năng` cho các món sốt xào.',
          recipes: [],
          suggestions: ['Thiếu nước cốt dừa thay bằng gì?', 'Thiếu dầu hào thay bằng gì?', 'Khi làm món ăn bị cháy xử lý như nào?']
        };
      }
      return {
        intent: 'ingredient_substitution',
        reply: '🔄 **Bảng gợi ý thay thế nguyên liệu thông dụng khi thiếu trong bếp:**\n\n' +
          '- **Thiếu Nước cốt dừa:** Dùng `200ml sữa tươi không đường + 15g bơ lạt`.\n' +
          '- **Thiếu Bột năng:** Thay bằng `Bột bắp` hoặc `Bột sắn dây` tỷ lệ `1:1`.\n' +
          '- **Thiếu Nước mắm (ăn chay):** Dùng `Nước tương + 1/4 muỗng cà phê muối`.\n' +
          '- **Thiếu Dầu hào:** Pha `1 muỗng canh nước tương + 1/2 muỗng cà phê đường + chút bột năng`.\n' +
          '- **Thiếu Rượu nấu ăn:** Dùng `Gừng tươi đập dập + 1 muỗng canh giấm gạo` hoặc cốt chanh.',
        recipes: [],
        suggestions: ['Thiếu nước cốt dừa thay bằng gì?', 'Thiếu bột năng thay bằng gì?', 'Khi làm món ăn bị cháy xử lý như nào?']
      };
    }

    // 3. Quy đổi khẩu phần ăn (Nhóm 1 - UC06-A)
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
          suggestions: ['Cách nấu ' + rec.title, 'Thực đơn 3 bữa 1500 kcal', 'Khi làm món ăn bị cháy xử lý như nào?']
        };
      }
    }

    // 4. Tư vấn Calo & Dinh dưỡng (Nhóm 1 - UC06-B)
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
          '\n\n🔥 **Tổng năng lượng 3 món:** `' + totalCal + ' kcal/người`.',
        recipes: lowCal.map(toCard),
        suggestions: ['Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?', 'Phở bò Hà Nội cho 8 người', 'Thiếu nước cốt dừa thay bằng gì?']
      };
    }

    // 5. Có nguyên liệu này nấu món gì? (Nhóm 1 - Fridge Matcher)
    var expandedNorm = norm;
    if (typeof expandSearchKeywords === 'function') {
      expandedNorm = expandSearchKeywords(raw).join(' ');
    } else if (norm.indexOf('uc ga') !== -1 || norm.indexOf('dui ga') !== -1) {
      expandedNorm += ' thit ga ga ta';
    }
    var matchedRecipes = [];
    allRecipes.forEach(function (r) {
      var have = [];
      var miss = [];
      (r.ingredients || []).forEach(function (ing) {
        var inorm = _normalizeVi(ing.name);
        var words = inorm.split(' ').slice(0, 2).join(' ');
        if ((inorm && expandedNorm.indexOf(inorm) !== -1) || (words.length >= 4 && expandedNorm.indexOf(words) !== -1)) {
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
        reply: '🧊 **Từ nguyên liệu bạn đang có**, bạn có thể nấu ngay **' + matchedRecipes.length + ' món ngon** sau đây:\n\n' +
          topMatches.map(function (m, i) {
            var missStr = m.miss.length > 0 ? ' *(Cần thêm: ' + m.miss.slice(0, 3).join(', ') + ')*' : ' *(Đủ nguyên liệu!)*';
            return (i + 1) + '. **' + m.r.title + '** — Khớp **' + m.have.length + '/' + (m.r.ingredients || []).length + '** nguyên liệu (' + m.have.join(', ') + ')' + missStr;
          }).join('\n'),
        recipes: topMatches.map(function (m) { return toCard(m.r); }),
        suggestions: ['Khi làm món ăn bị cháy xử lý như nào?', 'Thiếu nước cốt dừa thay bằng gì?', 'Thực đơn 3 bữa 1500 kcal']
      };
    }

    // 6. Hỏi đáp món đang xem (Nhóm 2)
    if (activeRec) {
      var stepsText = (activeRec.steps || []).map(function (s, idx) {
        return '- **Bước ' + (s.step || (idx + 1)) + ':** ' + s.description;
      }).join('\n');
      return {
        intent: 'recipe_context',
        reply: '🍲 **Hướng dẫn nấu món đang xem: "' + activeRec.title + '"**\n\n' +
          '- **Thời gian:** Chuẩn bị ' + (activeRec.prepTime || 15) + 'p + Nấu ' + (activeRec.cookTime || 25) + 'p | **Khẩu phần gốc:** ' + (activeRec.servings || 4) + ' người\n\n' +
          stepsText,
        recipes: [toCard(activeRec)],
        suggestions: [
          'Quy đổi ' + activeRec.title + ' cho 8 người',
          'Khi làm món ăn bị cháy xử lý như nào?',
          'Thiếu nước cốt dừa thay bằng gì?'
        ]
      };
    }

    // Phản hồi mặc định
    var featured = allRecipes.slice(0, 3);
    return {
      intent: 'general_recommend',
      reply: '👨‍🍳 **Xin chào! Mình là Trợ lý Đầu bếp AI của CookMate (Chuyên giải đáp về Món ăn & Nấu nướng).**\n\n' +
        'Bạn có thể hỏi mình:\n' +
        '- 🧊 **Có nguyên liệu này nấu món gì:** *"Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?"*\n' +
        '- 🆘 **Xử lý sự cố món ăn:** *"Khi làm món ăn bị cháy thì xử lý như nào?"*, *"Canh bị mặn chữa sao?"*\n' +
        '- 🔄 **Thay thế nguyên liệu bị thiếu:** *"Thiếu nước cốt dừa / bột năng thay bằng gì?"*\n' +
        '- ⚖️ **Định lượng & Dinh dưỡng:** *"Phở bò cho 8 người"*, *"Thực đơn 3 bữa 1500 kcal"*',
      recipes: featured.map(toCard),
      suggestions: [
        'Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?',
        'Khi làm món ăn bị cháy thì xử lý như nào?',
        'Thiếu nước cốt dừa thì thay bằng gì?',
        'Phở bò Hà Nội nấu cho 8 người'
      ]
    };
  }

  // ---------------------------------------------------------------
  // Inject Scoped Styles
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
      '  width: 400px; max-width: calc(100vw - 24px); height: 580px; max-height: calc(100vh - 110px);',
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
      '.cm-chefbot-context-bar {',
      '  background: #FFF7ED; border-bottom: 1px solid #FED7AA; padding: 7px 12px;',
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
      '.cm-chefbot-card img { width: 56px; height: 56px; border-radius: 9px; object-fit: cover; flex-shrink: 0; }',
      '.cm-chefbot-card__body { flex: 1; min-width: 0; }',
      '.cm-chefbot-card__title {',
      '  font-size: 13px; font-weight: 700; color: #1C1917; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;',
      '}',
      '.cm-chefbot-card__meta { font-size: 11px; color: #78716C; margin-top: 2px; }',
      '.cm-chefbot-card__actions { display: flex; gap: 6px; margin-top: 5px; }',
      '.cm-chefbot-mini-btn {',
      '  font-size: 11px; font-weight: 700; padding: 4px 9px; border-radius: 6px; text-decoration: none;',
      '  border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;',
      '}',
      '.cm-chefbot-mini-btn--primary { background: #FFF0EB; color: #E85D2A; }',
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
      '<span class="cm-chefbot-launcher__icon"><i class="fa-solid fa-utensils"></i></span>' +
      '<span class="cm-chefbot-launcher__label">Hỏi Đầu bếp AI</span>' +
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
          '<button type="button" class="cm-chefbot-mini-btn cm-chefbot-mini-btn--primary" id="cmAskCurrentBtn">Hỏi cách nấu món này</button>' +
        '</div>';
    }

    panel.innerHTML =
      '<div class="cm-chefbot-header">' +
        '<div class="cm-chefbot-brand">' +
          '<div class="cm-chefbot-avatar"><i class="fa-solid fa-utensils"></i></div>' +
          '<div>' +
            '<div class="cm-chefbot-title">CookMate ChefBot AI</div>' +
            '<div class="cm-chefbot-subtitle"><span class="cm-chefbot-launcher__pulse"></span> Chuyên giải đáp Món ăn • Sự cố bếp • Nguyên liệu</div>' +
          '</div>' +
        '</div>' +
        '<div class="cm-chefbot-header-actions">' +
          '<button type="button" class="cm-chefbot-icon-btn" id="cmChefBotResetBtn" title="Làm mới cuộc trò chuyện"><i class="fa-solid fa-rotate-right"></i></button>' +
          '<button type="button" class="cm-chefbot-icon-btn" id="cmChefBotCloseBtn" title="Thu gọn"><i class="fa-solid fa-xmark"></i></button>' +
        '</div>' +
      '</div>' +
      contextHtml +
      '<div class="cm-chefbot-messages" id="cmChefBotMessages"></div>' +
      '<div class="cm-chefbot-chips" id="cmChefBotChips">' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?">🧊 Có nguyên liệu này nấu gì?</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Khi làm món ăn bị cháy thì xử lý như nào?">🔥 Món ăn bị cháy xử lý sao?</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Thiếu nước cốt dừa thì thay bằng gì?">🔄 Thiếu nguyên liệu thay bằng gì?</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Canh bị mặn quá chữa sao?">🆘 Canh bị mặn chữa sao?</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Phở bò Hà Nội cho 8 người ăn">⚖️ Quy đổi khẩu phần 8 người</button>' +
        '<button type="button" class="cm-chefbot-chip" data-prompt="Thực đơn 3 bữa 1500 kcal">🥗 Tư vấn món theo Calo</button>' +
      '</div>' +
      '<form class="cm-chefbot-input-bar" id="cmChefBotForm">' +
        '<input type="text" class="cm-chefbot-input" id="cmChefBotInput" placeholder="Hỏi về nguyên liệu sẵn có, món bị cháy/mặn, đồ thay thế..." autocomplete="off" />' +
        '<button type="submit" class="cm-chefbot-send" aria-label="Gửi câu hỏi"><i class="fa-solid fa-paper-plane"></i></button>' +
      '</form>';

    document.body.appendChild(launcher);
    document.body.appendChild(panel);

    _bindWidgetEvents(launcher, panel);

    appendBotResponse({
      reply:
        'Xin chào! Mình là **Trợ lý Đầu bếp AI của CookMate** 👨‍🍳 (Chuyên giải đáp về Món ăn & Kỹ thuật nấu nướng).\n\n' +
        'Bạn có thể hỏi mình ngay về:\n' +
        '1. 🧊 **Có nguyên liệu này nấu món gì?** *(VD: "Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?")*\n' +
        '2. 🔥 **Xử lý sự cố khi nấu ăn:** *(VD: "Khi làm món ăn bị cháy thì xử lý như nào?", "Canh bị mặn / cơm bị nhão chữa sao?")*\n' +
        '3. 🔄 **Thay thế nguyên liệu bị thiếu:** *(VD: "Thiếu nước cốt dừa / bột năng thay bằng gì?")*\n' +
        '4. ⚖️ **Quy đổi khẩu phần & Dinh dưỡng:** *(VD: "Phở bò cho 8 người", "Thực đơn 3 bữa 1500 kcal")*'
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

    var askCurrentBtn = document.getElementById('cmAskCurrentBtn');
    if (askCurrentBtn && state.currentRecipe) {
      askCurrentBtn.addEventListener('click', function () {
        sendPrompt('Hướng dẫn các bước nấu và định lượng món ' + state.currentRecipe.title);
      });
    }

    document.getElementById('cmChefBotChips').addEventListener('click', function (e) {
      var chip = e.target.closest('.cm-chefbot-chip');
      if (!chip) return;
      var promptText = chip.getAttribute('data-prompt');
      if (promptText) {
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
      sendPrompt(val);
    });
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

    if (Array.isArray(data.recipes) && data.recipes.length > 0) {
      html += '<div class="cm-chefbot-cards">';
      data.recipes.forEach(function (r) {
        var detailUrl = base + 'pages/recipe-detail.html?id=' + encodeURIComponent(r.id);
        html +=
          '<div class="cm-chefbot-card">' +
            '<img src="' + _escape(r.image) + '" alt="' + _escape(r.title) + '" onerror="this.src=\'' + base + 'assets/images/placeholders/recipe-placeholder.svg\'" />' +
            '<div class="cm-chefbot-card__body">' +
              '<div class="cm-chefbot-card__title">' + _escape(r.title) + '</div>' +
              '<div class="cm-chefbot-card__meta"><i class="fa-solid fa-fire text-primary"></i> ' + _escape(r.calories) + ' kcal • <i class="fa-regular fa-clock"></i> ' + _escape(r.totalTime) + ' phút • ' + _escape(r.servings) + ' người</div>' +
              '<div class="cm-chefbot-card__actions">' +
                '<a href="' + detailUrl + '" class="cm-chefbot-mini-btn cm-chefbot-mini-btn--primary"><i class="fa-solid fa-book-open"></i> Xem công thức chi tiết</a>' +
              '</div>' +
            '</div>' +
          '</div>';
      });
      html += '</div>';
    }

    wrapper.innerHTML = html;
    msgBox.appendChild(wrapper);

    if (Array.isArray(data.suggestions) && data.suggestions.length > 0) {
      var chipsBar = document.getElementById('cmChefBotChips');
      if (chipsBar) {
        chipsBar.innerHTML = data.suggestions.map(function (s) {
          return '<button type="button" class="cm-chefbot-chip" data-prompt="' + _escape(s) + '">💡 ' + _escape(s) + '</button>';
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

  function init() {
    var path = window.location.pathname.replace(/\\/g, '/');
    if (path.indexOf('/pages/auth/') !== -1) return;
    buildWidget();
  }

  return {
    init: init,
    sendPrompt: sendPrompt
  };
})();

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () {
    CookMateChefBot.init();
  });
} else {
  CookMateChefBot.init();
}
