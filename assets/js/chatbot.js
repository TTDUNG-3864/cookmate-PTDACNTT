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
  // BẢNG QUY TẮC CẤP CỨU & XỬ LÝ SỰ CỐ MÓN ĂN / SƠ CHẾ (Nhóm 2)
  // ---------------------------------------------------------------
  var RESCUE_RULES = [
    {
      id: 'poultry_odor',
      pattern: /(ga|vit|ngan|ngong|chim|gia cam).*(bi hoi|mui hoi|tanh|hoi|khu mui|lam sach|so che|xu li|xu ly)|(bi hoi|mui hoi|khu mui).*(ga|vit|ngan|ngong|gia cam)/,
      title: 'Khử sạch mùi hôi lông & mùi tanh của Thịt Gà / Vịt / Ngan',
      steps: [
        '**Bước 1 — Cắt bỏ tuyến dầu ở phao câu (Nguyên nhân số 1 gây hôi):** Dùng dao cắt bỏ hoàn toàn 2 cục tuyến nhờn màu vàng nhạt trên phao câu gà/vịt và phần máu đông sát xương sống, cuống họng.',
        '**Bước 2 — Chà xát hỗn hợp Gừng đập dập + Muối hạt + Rượu trắng (hoặc Giấm/Chanh):** Lấy `1 củ gừng tươi đập dập + 2 muỗng canh muối hạt + 2 muỗng canh rượu trắng` (nếu không có rượu dùng `1 quả chanh` hoặc `2 muỗng giấm`), chà kỹ cả bên ngoài da lẫn bên trong bụng gà khoảng 3–5 phút rồi rửa sạch bằng nước lạnh.',
        '**Bước 3 — Nếu thịt gà đã luộc/nấu lên mà vẫn còn mùi hôi:** Cho ngay vào nồi `1 củ gừng nướng đập dập + 3 củ hành tím nướng + 2 cây sả đập dập + 1 muỗng canh rượu trắng`, mở vung đun sôi 5 phút để hơi rượu cuốn bay mùi hôi.',
        '**Mẹo bảo quản:** Sau khi rửa sạch, thấm khô nước trước khi ướp hoặc chế biến để thịt gà thơm ngọt, da giòn vàng.'
      ],
      suggestions: [
        'Tôi có ức gà thì nấu món gì?',
        'Thịt lợn bị hôi xử lý thế nào?',
        'Tôi không có xì dầu thì thay bằng gì?'
      ]
    },
    {
      id: 'pork_beef_odor',
      pattern: /(heo|lon|bo|de|cuu|thit|xuong|long|da day|bau duc).*(bi hoi|mui hoi|hoi|tanh|khu mui|so che|tran|luoc so|xu li|xu ly)|(bi hoi|mui hoi|khu mui).*(heo|lon|bo|de|thit|xuong|long)/,
      title: 'Khử mùi hôi của Thịt Heo (Lợn) / Thịt Bò / Xương & Nội tạng',
      steps: [
        '**Với Thịt Heo (Lợn) / Xương heo bị hôi:** Ngâm thịt trong nước muối loãng pha `vài lát gừng + 1 muỗng giấm` 10 phút. Sau đó cho thịt vào nồi từ lúc **nước còn lạnh** cùng `1 củ hành tím đập dập + vài lát gừng`, đun sôi 2–3 phút cho bọt bẩn tiết hết ra ngoài rồi rửa lại bằng nước ấm.',
        '**Với Thịt Bò / Dê có mùi gây nồng:** Chà xát thịt với `gừng tươi nướng cháy vỏ đập dập + rượu trắng` trong 3 phút. Gừng nướng và rượu sẽ trung hòa hoàn toàn mùi gây đặc trưng.',
        '**Với Lòng / Dạ dày / Nội tạng:** Bóp kỹ 2 lần với `bột mì (hoặc bột năng) + muối hạt + cốt chanh/giấm` để kéo sạch nhớt, sau đó chần sơ với nước gừng sả.'
      ],
      suggestions: [
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
        'Thịt bò bị dai xử lý sao?',
        'Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?'
      ]
    },
    {
      id: 'fish_seafood_odor',
      pattern: /(ca |hai san|tom|muc|oc|ngheu|so|cua|luon|ech).*(tanh|hoi|nhot|khu mui|lam sach|so che|xu li|xu ly)|bi tanh|mui tanh|khu tanh|ca tanh/,
      title: 'Khử sạch mùi tanh & nhớt của Cá / Tôm / Mực / Hải sản',
      steps: [
        '**Bước 1 — Loại bỏ màng đen & máu tanh:** Cạo sạch lớp màng đen trong bụng cá, lấy hết mang cá và đường máu dọc sống lưng (đây là ổ gây tanh mạnh nhất).',
        '**Bước 2 — Ngâm nước Vo gạo hoặc Muối + Chanh/Giấm/Gừng:** Ngâm cá/hải sản trong `nước vo gạo đặc` hoặc `nước muối pha cốt chanh + gừng đập dập` 10 phút rồi rửa sạch.',
        '**Bước 3 — Với cá da trơn (cá basa, cá hú, lươn) nhiều nhớt:** Chà với `tro bếp, bột mì hoặc muối hạt + giấm trắng` (tuyệt đối không dội nước sôi quá nóng làm tróc da cá).',
        '**Bước 4 — Khi đang nấu kho/canh cá:** Cho `vài lát gừng, sả, nghệ, thì là, hành lá` hoặc `1 muỗng rượu trắng` vào lúc nước đang sôi để khử tanh triệt để.'
      ],
      suggestions: [
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
        'Khi làm món ăn bị cháy xử lý như nào?',
        'Tôi không có xì dầu thì thay bằng gì?'
      ]
    },
    {
      id: 'burned_food',
      pattern: /bi chay|chay noi|chay khet|khet|bi khe|com khe|chay day|chay den|mui khe/,
      title: 'Món ăn / Nồi kho / Cơm bị cháy hoặc có mùi khê khét',
      steps: [
        '**Bước 1 — Tắt bếp ngay & TUYỆT ĐỐI KHÔNG ĐẢO/KHUẤY:** Đừng cạo phần đáy nồi bị cháy vì vị đắng và cặn đen sẽ lan ra toàn bộ phần thức ăn còn ngon.',
        '**Bước 2 — Gắp phần chưa cháy sang nồi sạch mới:** Nhẹ nhàng múc phần thức ăn phía trên sang một chiếc nồi khác.',
        '**Bước 3 — Khử mùi khê tức thì:**\n  • *Với cơm bị khê:* Đặt **1–2 lát bánh mì sandwich** (hoặc vài gốc hành lá tươi / 1 cục than hoa sạch đặt trong chén nhỏ) lên mặt cơm, đậy nắp 5–10 phút để hút sạch mùi khê.\n  • *Với món kho/hầm bị cháy sốt:* Pha lại nước sốt mới (nước dừa/nước lọc + chút nước mắm + đường + gừng/hành tím) đun nhỏ lửa 5 phút.',
        '**Bước 4 — Làm sạch nồi bị cháy đen không tốn sức:** Đổ nước ngập vết cháy, thêm `2 muỗng canh Baking Soda + 3 muỗng giấm trắng`, đun sôi 5 phút rồi ngâm 15 phút — mảng cháy sẽ tự bong ra dễ dàng!'
      ],
      suggestions: [
        'Canh bị mặn quá chữa sao?',
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?'
      ]
    },
    {
      id: 'too_salty',
      pattern: /bi man|man qua|man chat|chua man|giam man|lo tay cho nhieu muoi|nhieu mam/,
      title: 'Món canh / Món kho / Món xào bị mặn quá tay',
      steps: [
        '**Mẹo 1 — Khoai tây sống hút muối (Hiệu quả nhất):** Gọt vỏ `1 củ khoai tây sống`, cắt lát dày thả vào nồi canh/nồi kho đun 10 phút rồi vớt ra — khoai tây sẽ hút bớt muối thừa cực nhạy mà không làm hỏng vị món ăn!',
        '**Mẹo 2 — Với món canh/súp:** Châm thêm nước sôi ấm, thả thêm **đậu hũ non, cà chua, củ cải trắng** hoặc nấm để giãn vị mặn.',
        '**Mẹo 3 — Với món thịt/cá kho hoặc xào:** Chắt bớt nước kho mặn ra, thêm `nước dừa tươi (hoặc nước lọc) + 1 muỗng cà phê đường phèn/mật ong + vài giọt cốt chanh` đun sôi lại để dịu ngay vị gắt.'
      ],
      suggestions: [
        'Khi làm món ăn bị cháy xử lý như nào?',
        'Cơm bị nhão xử lý thế nào?',
        'Tôi không có xì dầu thì thay bằng gì?'
      ]
    },
    {
      id: 'rice_mushy_or_raw',
      pattern: /com nhao|bi nhao|nhao nhoet|com song|bi song|com suong|bi suong|com kho/,
      title: 'Cơm bị nhão (dư nước) hoặc bị sống / sượng / khô',
      steps: [
        '**Khi cơm bị nhão:** Xới nhẹ cho tơi, mở nắp nồi 2 phút cho thoát hơi nước, sau đó đặt **1–2 lát bánh mì sandwich (ruột trắng)** lên mặt cơm, đậy nắp bật `Warm` 10 phút — bánh mì sẽ hút hết hơi nước thừa giúp hạt cơm ráo dẻo.',
        '**Khi cơm bị sống / sượng ở giữa:** Xới tơi cơm chuyển sang nồi khác (hoặc gom cơm vào giữa nồi), rưới đều theo tỷ lệ `2 muỗng canh nước ấm + 1 muỗng cà phê rượu trắng` cho mỗi bát cơm, đậy kín nắp bấm `Cook` lại — hơi rượu sẽ làm chín hạt gạo và bay hơi hết không để lại mùi.',
        '**Khi cơm bị khô cứng:** Rưới vài muỗng nước ấm hoặc nước cốt dừa kèm `1/2 muỗng cà phê dầu ăn/bơ`, hấp lại 5–7 phút.'
      ],
      suggestions: [
        'Khi làm món ăn bị cháy xử lý như nào?',
        'Canh bị mặn quá chữa sao?',
        'Nước phở bị đục làm sao cho trong?'
      ]
    },
    {
      id: 'cloudy_broth',
      pattern: /bi duc|nuoc dung duc|nuoc pho duc|nuoc canh duc|lam trong nuoc/,
      title: 'Nước dùng Phở / Bún / Canh hầm xương bị đục',
      steps: [
        '**Tuyệt chiêu lòng trắng trứng gà:** Đánh tan `1 lòng trắng trứng gà` với 1 muỗng nước lạnh, đổ vào nồi nước dùng đang ấm (khoảng 70°C) rồi khuấy đều. Khi đun sôi lăn tăn, lòng trắng trứng đông tụ sẽ cuốn theo toàn bộ cặn bẩn lơ lửng — chỉ cần vớt bỏ lớp trứng này là nước dùng trong veo!',
        '**Thả khoai tây sống hoặc củ cải trắng:** Cắt vài khúc củ cải trắng hoặc khoai tây sống thả vào nồi hầm 15 phút để hút bọt đục và tăng vị ngọt thanh.',
        '**Lưu ý phòng tránh:** Luôn chần xương với nước lạnh + gừng + hành tím ở lửa đầu, rửa sạch rồi mới ninh ở lửa nhỏ liu riu (không đậy kín nắp).'
      ],
      suggestions: [
        'Thịt bò bị dai xử lý sao?',
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
        'Phở bò Hà Nội cho 8 người ăn'
      ]
    },
    {
      id: 'tough_dry_meat',
      pattern: /bi dai|thit dai|bo dai|bi kho|thit kho|lau mem|ham lau/,
      title: 'Thịt bò xào / Thịt hầm bị dai cứng hoặc khô xác',
      steps: [
        '**Nếu món hầm đang nấu bị dai:** Cho vào nồi `vài lát dứa (thơm) chín`, `1 miếng đu đủ xanh nhỏ`, hoặc `1 muỗng cà phê nước cốt chanh / giấm` — enzyme bromelain & papain tự nhiên sẽ phá vỡ sợi cơ giúp thịt mềm nhanh gấp đôi.',
        '**Nếu thịt bò xào bị dai:** Thái mỏng **ngang thớ**, ướp với `1 muỗng dầu ăn + 1/2 muỗng bột bắp + chút gừng` (tuyệt đối không ướp muối/nước mắm từ đầu vì muối rút nước làm khô thịt). Xào lửa thật lớn, thịt vừa chín tới là tắt bếp ngay.',
        '**Nếu ức gà bị khô bã:** Ngâm ức gà trong nước muối loãng 10 phút hoặc ướp với `1 muỗng sữa tươi / dầu oliu` trước khi áp chảo.'
      ],
      suggestions: [
        'Tôi có ức gà thì nấu món gì?',
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?'
      ]
    },
    {
      id: 'too_spicy_sour_sweet_bitter',
      pattern: /bi cay|cay qua|bi chua|chua qua|bi ngot|ngot qua|bi dang|dang qua|canh kho qua/,
      title: 'Cân bằng lại món ăn bị quá Cay / quá Chua / quá Ngọt / bị Đắng',
      steps: [
        '**Món bị quá Cay:** Thêm chất béo từ sữa (`nước cốt dừa, sữa tươi, kem tươi, bơ đậu phộng`) hoặc thêm vị chua-ngọt nhẹ (`cà chua, đường phèn, cốt chanh`) — chất béo hòa tan capsaicin trong ớt giúp giảm cay tức thì.',
        '**Món bị quá Chua:** Thêm `1/2 – 1 muỗng cà phê đường phèn` (hoặc mật ong) để làm tròn vị; nếu quá chua gắt, cho một nhúm cực nhỏ `Baking Soda` (bột muối nở) bằng đầu đũa để trung hòa axit.',
        '**Món bị quá Ngọt:** Vắt thêm `nước cốt chanh, giấm táo` hoặc một chút nước mắm/ớt tươi để kéo lại độ cân bằng.',
        '**Món khổ qua (mướp đắng) hoặc măng bị Đắng:** Bào mỏng khổ qua, bóp nhẹ với chút muối rồi rửa sạch hoặc ngâm nước đá lạnh 10 phút trước khi nấu; với măng thì luộc mở vung 2 lần với nước vo gạo.'
      ],
      suggestions: [
        'Canh bị mặn quá chữa sao?',
        'Khi làm món ăn bị cháy xử lý như nào?',
        'Tôi không có xì dầu thì thay bằng gì?'
      ]
    },
    {
      id: 'sticking_splattering_soggy',
      pattern: /dinh chao|bi nat|ca ran nat|vang dau|ban dau|bi iu|mat gion|mem xiu/,
      title: 'Chiên rán bị dính chảo, nát cá, văng dầu hoặc mất độ giòn',
      steps: [
        '**Chống dính chảo & văng dầu khi chiên cá/đậu:** Thấm thật khô thực phẩm bằng giấy ăn. Làm nóng chảo, chà `1 lát gừng tươi` khắp mặt chảo hoặc rắc `1/4 muỗng cà phê bột mì / muối` vào dầu nóng trước khi thả cá vào.',
        '**Để đồ chiên giòn lâu không bị ỉu:** Pha bột chiên với `nước đá lạnh hoặc chút bia/giấm trắng`, chiên 2 lửa (lửa 1 vừa chín tới vớt ra nghỉ 3 phút, lửa 2 dầu thật nóng chiên nhanh 1 phút cho vỏ giòn rụm).'
      ],
      suggestions: [
        'Cá bị tanh khử mùi sao?',
        'Thiếu bột năng thay bằng gì?',
        'Khi làm món ăn bị cháy xử lý như nào?'
      ]
    }
  ];

  // ---------------------------------------------------------------
  // TỪ ĐIỂN THAY THẾ NGUYÊN LIỆU CHI TIẾT (Nhóm 2 - 35+ nguyên liệu)
  // ---------------------------------------------------------------
  var SUBSTITUTION_CATALOG = [
    {
      keywords: ['xi dau', 'nuoc tuong'],
      name: 'Xì dầu (Nước tương)',
      items: [
        '**Cách 1 — Nước mắm + Đường + Nước ấm (Tiện nhất trong bếp Việt):** Pha `1/2 muỗng canh nước mắm + 1/2 muỗng canh nước ấm + 1/2 muỗng cà phê đường` (nếu cần màu nâu đẹp mắt như xì dầu thì thêm `2–3 giọt nước màu kho thịt/caramel`). Phù hợp cho cả món xào, kho, ướp thịt.',
        '**Cách 2 — Dầu hào pha loãng:** Dùng `1 muỗng canh dầu hào + 1 muỗng canh nước lọc` thay cho 1 muỗng canh xì dầu (rất hợp cho các món rau xào, bò xào, mì xào).',
        '**Cách 3 — Muối + Đường nâu/Mật mía (Nếu ăn chay & hết sạch nước chấm):** Hòa `1/2 muỗng cà phê muối + 1/2 muỗng cà phê đường nâu + 1 muỗng canh nước nấm luộc/nước lọc`.'
      ],
      suggestions: [
        'Thiếu dầu hào thì thay bằng gì?',
        'Thiếu nước mắm thì thay bằng gì?',
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?'
      ]
    },
    {
      keywords: ['nuoc mam'],
      name: 'Nước mắm',
      items: [
        '**Thay thế trong món mặn (xào, kho, canh):** Dùng **Xì dầu (Nước tương) + chút muối** theo tỷ lệ `1 muỗng canh xì dầu + 1/4 muỗng cà phê muối` thay cho 1 muỗng canh nước mắm.',
        '**Thay thế cho món Chay:** Nấu **nước tương + nước luộc nấm hương/táo tàu + chút muối biển**, hoặc dùng **tương Miso pha loãng** để tạo vị đậm đà umami.',
        '**Khi pha nước chấm gỏi/nem:** Dùng `Xì dầu + cốt chanh + đường + tỏi ớt` hoặc `Muối ớt chanh`.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu dầu hào thì thay bằng gì?',
        'Thiếu nước cốt dừa thay bằng gì?'
      ]
    },
    {
      keywords: ['dau hao'],
      name: 'Dầu hào',
      items: [
        '**Công thức tự pha giống 95% dầu hào:** Khuấy đều `1 muỗng canh xì dầu (nước tương) + 1/2 muỗng cà phê đường + 1/3 muỗng cà phê bột năng (hoặc bột bắp) + 1 muỗng canh nước lọc`. Khi cho vào chảo nóng, hỗn hợp sẽ sánh bóng và đậm ngọt y hệt dầu hào!',
        '**Thay bằng Tương Hoisin (tương đen ăn phở):** Dùng tỷ lệ `1:1` và giảm bớt lượng đường trong món ăn.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu bột năng thay bằng gì?',
        'Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?'
      ]
    },
    {
      keywords: ['cot dua', 'nuoc cot dua'],
      name: 'Nước cốt dừa',
      items: [
        '**Sữa tươi không đường + Bơ lạt (Khuyên dùng cho Cà ri, Kho, Bánh):** Pha `200ml sữa tươi không đường + 15g bơ lạt đun chảy` (có thể thêm 1/2 muỗng bột năng để tạo độ sánh béo đạt 85–90% so với cốt dừa thật).',
        '**Kem tươi (Whipping Cream / Cooking Cream):** Thay thế trực tiếp tỷ lệ `1:1` cho các món súp, cà ri, sốt.',
        '**Sữa đặc + Sữa tươi:** Pha `180ml sữa tươi + 2 muỗng canh sữa đặc` cho các món chè hoặc sinh tố.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu bột năng thay bằng gì?',
        'Thiếu nước dừa tươi kho thịt thay bằng gì?'
      ]
    },
    {
      keywords: ['nuoc dua', 'dua tuoi'],
      name: 'Nước dừa tươi (dùng để kho thịt/cá, hầm xương)',
      items: [
        '**Nước lọc ấm + Đường phèn (hoặc Mật ong):** Pha `250ml nước lọc ấm + 1.5 muỗng cà phê đường phèn` (đường phèn cho vị ngọt thanh tự nhiên rất giống nước dừa tươi khi kho tàu, kho cá).',
        '**Nước mía loãng hoặc Nước củ đậu/củ cải luộc:** Tạo độ ngọt dịu tự nhiên và lên màu cánh gián đẹp mắt.'
      ],
      suggestions: [
        'Thiếu nước cốt dừa thay bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?',
        'Khi làm món ăn bị cháy xử lý như nào?'
      ]
    },
    {
      keywords: ['bot nang', 'bot bap', 'bot ngo', 'bot san'],
      name: 'Bột năng / Bột bắp / Bột sắn dây (Tạo độ sánh)',
      items: [
        '**Bột bắp ↔ Bột năng ↔ Bột sắn dây:** Thay thế trực tiếp cho nhau theo tỷ lệ `1:1` (luôn hòa tan với nước nguội trước khi đổ từ từ vào nồi đang sôi).',
        '**Bột mì đa dụng hoặc Bột gạo:** Dùng tỷ lệ `2 muỗng bột mì = 1 muỗng bột năng` cho các món sốt xào, súp.'
      ],
      suggestions: [
        'Thiếu bột chiên giòn thay bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu dầu hào thay bằng gì?'
      ]
    },
    {
      keywords: ['bot chien gion', 'bot chien xu', 'bot mi'],
      name: 'Bột chiên giòn / Bột chiên xù / Bột mì',
      items: [
        '**Khi thiếu Bột chiên giòn:** Tự pha theo tỷ lệ vàng `3 muỗng canh bột mì + 1 muỗng canh bột bắp (hoặc bột năng) + 1/4 muỗng cà phê bột nở (hoặc vài giọt cốt chanh) + chút muối tiêu`, khuấy với nước đá lạnh.',
        '**Khi thiếu Bột chiên xù:** Dùng **vụn bánh mì sandwich nướng giòn bóp nhỏ**, **bánh phồng tôm sống giã vụn**, hoặc **ngũ cốc ăn sáng (Cornflakes) đập dập**.'
      ],
      suggestions: [
        'Thiếu bột năng thay bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?',
        'Chiên cá bị dính chảo xử lý sao?'
      ]
    },
    {
      keywords: ['ruou nau an', 'ruou trang', 'ruou mirin', 'ruou gao', 'ruou vang', 'ruou'],
      name: 'Rượu nấu ăn / Rượu trắng / Rượu Mirin',
      items: [
        '**Để khử mùi hôi thịt, cá, hải sản:** Thay bằng `Gừng tươi đập dập + 1 muỗng canh giấm trắng (hoặc nước cốt chanh)` + chút muối hạt.',
        '**Để thay Rượu Mirin (Nhật Bản):** Pha `1 muỗng canh giấm gạo (hoặc nước táo ép) + 1/2 muỗng cà phê đường`.',
        '**Để thay Rượu vang đỏ khi sốt/hầm bò:** Dùng `Nước ép nho không đường + 1/2 muỗng cà phê giấm` hoặc `Nước dùng bò + chút sốt cà chua`.'
      ],
      suggestions: [
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?',
        'Cá bị tanh khử mùi sao?'
      ]
    },
    {
      keywords: ['hat nem', 'bot ngot', 'mi chinh', 'bot canh'],
      name: 'Hạt nêm / Bột ngọt (Mì chính) / Bột canh',
      items: [
        '**Khi không có Hạt nêm / Mì chính:** Phối hợp `Muối + Nước mắm (hoặc Xì dầu) + 1/2 muỗng cà phê Đường` theo tỷ lệ cân bằng. Đường giúp làm dịu độ gắt của muối và kích vị ngọt tự nhiên.',
        '**Tạo ngọt tự nhiên cho nước canh/súp:** Ninh cùng `hành tây, củ cải trắng, cà rốt, bắp Mỹ, nấm hương` hoặc `tôm khô / mực khô nướng`.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu dầu hào thay bằng gì?',
        'Canh bị mặn quá chữa sao?'
      ]
    },
    {
      keywords: ['duong phen', 'duong nau', 'mat ong', 'duong'],
      name: 'Đường / Đường phèn / Đường nâu / Mật ong',
      items: [
        '**Thiếu Đường phèn:** Thay bằng `Đường cát trắng` tỷ lệ `1:1` (kèm thêm vài lát lê hoặc củ cải nếu nấu chè/nước dùng để giữ vị thanh).',
        '**Thiếu Đường nâu:** Trộn `1 muỗng canh đường trắng + 1/2 muỗng cà phê mật mía (hoặc mật ong / vài giọt nước màu)`.',
        '**Thiếu Mật ong (khi ướp đồ nướng):** Dùng `Sữa đặc + Đường nâu` hoặc `Nước đường thắng nhẹ + vài giọt cốt chanh` để thịt nướng vẫn bóng mềm, lên màu đẹp.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu nước cốt dừa thay bằng gì?',
        'Tôi có ức gà thì nấu món gì?'
      ]
    },
    {
      keywords: ['chanh', 'giam', 'me', 'khe', 'chua'],
      name: 'Chanh / Giấm / Me chua',
      items: [
        '**Thiếu Chanh tươi:** Thay bằng `Giấm gạo / Giấm táo` (tỷ lệ 1:1), hoặc dùng `Quất (Tắc), Me chua, Khế chua, Cà chua, Dứa (Thơm)` tùy món canh hay nước chấm.',
        '**Thiếu Giấm:** Dùng `Nước cốt chanh tươi pha thêm 1 chút nước lọc` tỷ lệ `1:1`.',
        '**Thiếu Me khi nấu canh chua:** Dùng `Nước cốt chanh + Cà chua + Dứa (thơm)` hoặc `Sấu / Khế chua / Dọc mùng`.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Món ăn bị chua quá chữa sao?',
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?'
      ]
    },
    {
      keywords: ['bo', 'bo lat', 'dau an', 'dau oliu', 'mo heo'],
      name: 'Bơ / Dầu ăn / Dầu Oliu',
      items: [
        '**Thiếu Bơ (khi áp chảo, xào, làm sốt):** Thay bằng `Dầu ăn / Dầu oliu` tỷ lệ `3/4 muỗng dầu = 1 muỗng bơ` (có thể thêm 1 muỗng sữa tươi để giữ mùi béo thơm).',
        '**Thiếu Bơ (khi làm bánh):** Thay bằng `Dầu thực vật, Sốt táo nghiền (Applesauce), hoặc Chuối chín nghiền`.',
        '**Thiếu Dầu ăn:** Có thể thắng `Mỡ heo/Mỡ gà`, dùng `Bơ`, hoặc chuyển sang áp chảo chống dính với một chút nước dùng.'
      ],
      suggestions: [
        'Thiếu nước cốt dừa thay bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu kem tươi whipping cream thay bằng gì?'
      ]
    },
    {
      keywords: ['sua tuoi', 'sua dac', 'kem tuoi', 'whipping cream', 'cooking cream', 'pho mai', 'sua chua'],
      name: 'Sữa tươi / Sữa đặc / Kem tươi (Whipping Cream)',
      items: [
        '**Thiếu Kem tươi (Whipping/Cooking Cream):** Pha `150ml sữa tươi không đường + 50g bơ lạt đun chảy + 1 muỗng cà phê bột mì/bột bắp` khuấy đều — dùng nấu súp, mì Ý, cà ri béo ngậy tương đương 90% kem tươi!',
        '**Thiếu Sữa tươi:** Pha loãng `1 muỗng canh sữa đặc với 4 muỗng canh nước ấm` hoặc dùng `Nước cốt dừa loãng / Sữa hạt`.',
        '**Thiếu Sữa đặc:** Đun nhỏ lửa `100ml sữa tươi + 40g đường + 10g bơ` cho sánh lại.'
      ],
      suggestions: [
        'Thiếu nước cốt dừa thay bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu bơ thay bằng gì?'
      ]
    },
    {
      keywords: ['hanh tim', 'hanh kho', 'hanh tay', 'hanh la', 'toi'],
      name: 'Hành tím / Hành tây / Hành lá / Tỏi',
      items: [
        '**Thiếu Hành tím (Hành khô):** Thay bằng `Hành tây băm nhỏ` hoặc `Phần đầu trắng của hành lá / Hành boa-rô (tỏi tây)` đập dập phi thơm.',
        '**Thiếu Tỏi tươi:** Dùng `Bột tỏi (1/4 muỗng cà phê bột tỏi = 1 tép tỏi tươi)`, hoặc dùng `Hành tím + chút Gừng/Hẹ` để tạo mùi thơm dậy vị.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu gừng hoặc sả thay bằng gì?',
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?'
      ]
    },
    {
      keywords: ['gung', 'sa', 'rieng', 'nghe', 'ot', 'tieu'],
      name: 'Gừng / Sả / Riềng / Nghệ / Ớt / Tiêu',
      items: [
        '**Thiếu Gừng tươi:** Dùng `Sả đập dập, Riềng, hoặc Vỏ chanh/cam thái chỉ + Tiêu đen` để khử mùi tanh và tạo vị ấm.',
        '**Thiếu Sả:** Dùng `Gừng tươi + Vỏ chanh bào mỏng (chứa tinh dầu sả chanh tự nhiên) + Lá chanh`.',
        '**Thiếu Ớt tươi:** Dùng `Ớt bột, Tương ớt, Sa tế` hoặc `Tiêu đen xay / Gừng` để tạo độ cay nồng.'
      ],
      suggestions: [
        'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
        'Tôi không có xì dầu thì thay bằng gì?',
        'Cá bị tanh khử mùi sao?'
      ]
    },
    {
      keywords: ['nuoc mau', 'nuoc hang', 'karmel', 'caramel', 'mau dieu', 'ngu vi huong'],
      name: 'Nước màu kho thịt (Nước hàng) / Màu điều / Ngũ vị hương',
      items: [
        '**Tự thắng Nước màu trong 2 phút:** Cho `2 muỗng canh đường + 1 muỗng canh nước lọc` vào nồi đun lửa vừa (không khuấy) đến khi chuyển màu cánh gián đẹp mắt thì đổ `3 muỗng nước ấm` vào. Nếu lười thắng đường: dùng **Xì dầu đậm (Dark soy sauce) + Mật ong** hoặc **Nước dừa tươi**!',
        '**Thiếu Dầu màu điều:** Phi `1 muỗng cà phê bột nghệ (hoặc bột ớt Paprika + sốt cà chua)` với dầu ăn ấm để lấy màu vàng cam óng ả.',
        '**Thiếu Ngũ vị hương:** Phối `Tiêu xay + Bột quế (hoặc 1 mảnh quế/hồi) + Bột nghệ + Tỏi băm`.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu nước dừa tươi kho thịt thay bằng gì?',
        'Khi làm món ăn bị cháy xử lý như nào?'
      ]
    },
    {
      keywords: ['trung', 'trung ga', 'ca chua', 'tuong ca'],
      name: 'Trứng gà / Cà chua / Tương cà',
      items: [
        '**Thiếu Trứng gà (để tẩm bột chiên):** Phết một lớp `Sữa tươi không đường`, `Nước cốt dừa`, hoặc `Bột mì pha nước sệt` để áo bột chiên xù bám chặt.',
        '**Thiếu Trứng gà (trong làm bánh/chả):** Dùng `1/2 quả chuối chín nghiền`, `2 muỗng sữa chua`, hoặc `1 muỗng bột năng` để tạo độ kết dính.',
        '**Thiếu Cà chua tươi:** Dùng `Tương cà (Ketchup) pha thêm chút nước + vài giọt giấm/chanh` để tạo màu đỏ và vị chua ngọt.'
      ],
      suggestions: [
        'Tôi không có xì dầu thì thay bằng gì?',
        'Thiếu bột chiên giòn thay bằng gì?',
        'Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?'
      ]
    }
  ];

  function _extractMissingIngredientPhrase(rawText) {
    var m = String(rawText || '').match(/(?:khong co|thieu|het|thay the|thay)\s+([^?.,!]+?)(?:\s+(?:thi|co the|bang|nhu nao|the nao|sao|khong|dc|duoc)|$)/i);
    if (!m) return '';
    return m[1].trim();
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
          '- *"Thịt gà của tôi bị hôi có thể xử lí bằng gì?"*\n' +
          '- *"Tôi không có xì dầu thì thay thế bằng gì?"*',
        recipes: [],
        suggestions: [
          'Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?',
          'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
          'Tôi không có xì dầu thì thay bằng gì?'
        ]
      };
    }

    // 1. Xử lý sự cố nhà bếp & Sơ chế khử mùi (Nhóm 2: Hôi, tanh, cháy, khê, mặn, nhão, đục, dai, cay, chua...)
    for (var i = 0; i < RESCUE_RULES.length; i++) {
      var rule = RESCUE_RULES[i];
      if (rule.pattern.test(norm)) {
        return {
          intent: 'kitchen_rescue',
          reply: '🆘 **Hướng dẫn xử lý — ' + rule.title + ':**\n\n' +
            rule.steps.map(function (s) { return '- ' + s; }).join('\n'),
          recipes: [],
          suggestions: rule.suggestions
        };
      }
    }

    if (
      norm.indexOf('xu li') !== -1 || norm.indexOf('xu ly') !== -1 ||
      norm.indexOf('chua ') !== -1 || norm.indexOf('cap cuu') !== -1 ||
      norm.indexOf('khu mui') !== -1 || norm.indexOf('bi hoi') !== -1 || norm.indexOf('mui hoi') !== -1
    ) {
      return {
        intent: 'kitchen_rescue',
        reply: '🆘 **Cẩm nang xử lý nhanh sự cố & sơ chế nguyên liệu trong bếp:**\n\n' +
          '- **Thịt gà / vịt / heo bị hôi:** Cắt bỏ tuyến dầu phao câu (với gia cầm), chà kỹ bằng `Gừng đập dập + Muối hạt + Rượu trắng (hoặc Chanh/Giấm)` trong 3–5 phút rồi rửa sạch.\n' +
          '- **Món ăn bị cháy / khê:** Tắt bếp ngay, **không khuấy đáy nồi**, gắp phần chưa cháy sang nồi sạch mới và đặt `1 lát bánh mì sandwich` lên mặt để hút sạch mùi khê.\n' +
          '- **Món canh / kho bị mặn:** Thả `vài lát khoai tây sống` vào đun 10 phút để hút muối thừa, hoặc thêm nước ấm + chút đường phèn.\n' +
          '- **Thịt hầm bị dai:** Cho `vài lát dứa (thơm) hoặc 1 muỗng cốt chanh` vào nồi hầm.',
        recipes: [],
        suggestions: [
          'Thịt gà của tôi bị hôi có thể xử lí bằng gì?',
          'Khi làm món ăn bị cháy xử lý như nào?',
          'Canh bị mặn quá chữa sao?'
        ]
      };
    }

    // 2. Thay thế nguyên liệu khi thiếu (Nhóm 2: "tôi không có xì dầu", "thiếu...", "hết...", "thay...")
    var padded = ' ' + norm + ' ';
    var isSubTrigger = (
      norm.indexOf('thay') !== -1 ||
      norm.indexOf('thieu') !== -1 ||
      norm.indexOf('khong co') !== -1 ||
      norm.indexOf('ko co') !== -1 ||
      norm.indexOf('k co') !== -1 ||
      norm.indexOf('chua co') !== -1 ||
      norm.indexOf('het ') !== -1 ||
      norm.indexOf('quen mua') !== -1 ||
      norm.indexOf('khong mua duoc') !== -1
    );
    if (isSubTrigger) {
      var matchedSubs = [];
      SUBSTITUTION_CATALOG.forEach(function (entry) {
        var hit = entry.keywords.some(function (kw) {
          return padded.indexOf(' ' + kw + ' ') !== -1 || norm.indexOf(kw) !== -1;
        });
        if (hit) matchedSubs.push(entry);
      });

      if (matchedSubs.length > 0) {
        var chosen = matchedSubs[0];
        return {
          intent: 'ingredient_substitution',
          reply: '🔄 **Giải pháp thay thế khi bạn không có / thiếu "' + chosen.name + '":**\n\n' +
            chosen.items.map(function (it) { return '- ' + it; }).join('\n') +
            '\n\n💡 *Mẹo nhỏ:* Khi dùng nguyên liệu thay thế, bạn hãy nếm thử từng chút một để điều chỉnh độ mặn/ngọt vừa khẩu vị gia đình nhé!',
          recipes: [],
          suggestions: chosen.suggestions
        };
      }

      var missingItem = _extractMissingIngredientPhrase(raw);
      if (missingItem) {
        return {
          intent: 'ingredient_substitution',
          reply: '🔄 **Hướng dẫn xử lý khi bạn không có "' + missingItem + '":**\n\n' +
            '- **Nếu "' + missingItem + '" là gia vị tạo vị mặn/đậm (như xì dầu, nước mắm, dầu hào, hạt nêm):** Bạn có thể phối hợp `Muối + Đường + một loại nước chấm sẵn có trong bếp` theo tỷ lệ 1 mặn : 0.5 ngọt để cân bằng vị Umami.\n' +
            '- **Nếu "' + missingItem + '" là gia vị tạo mùi thơm (như hành, tỏi, gừng, sả, rượu nấu ăn):** Hãy thay bằng một loại củ/lá có tinh dầu tương đương sẵn có trong bếp (như gừng, hành lá, tiêu đen, vỏ chanh/cam).\n' +
            '- **Nếu "' + missingItem + '" là nguyên liệu tạo độ sánh/béo (như bột năng, cốt dừa, kem tươi, bơ):** Có thể dùng `Sữa tươi + Dầu ăn/Bơ` (tạo béo) hoặc `Bột mì/Bột gạo hòa nước lạnh` (tạo sánh).\n\n' +
            '👉 *Bạn đang định nấu món gì với **' + missingItem + '**? Hãy nhắn tên món ăn để mình chỉ cách gia giảm chuẩn nhất nhé!*',
          recipes: [],
          suggestions: [
            'Tôi không có xì dầu thì thay bằng gì?',
            'Thiếu dầu hào thì thay bằng gì?',
            'Thiếu nước cốt dừa thay bằng gì?'
          ]
        };
      }

      return {
        intent: 'ingredient_substitution',
        reply: '🔄 **Bảng gợi ý thay thế nhanh các nguyên liệu hay hết trong bếp:**\n\n' +
          '- **Không có Xì dầu (Nước tương):** Pha `1/2 muỗng nước mắm + 1/2 muỗng nước ấm + 1/2 muỗng cà phê đường` (thêm 2 giọt nước màu nếu cần màu nâu).\n' +
          '- **Không có Dầu hào:** Pha `1 muỗng xì dầu + 1/2 muỗng cà phê đường + chút bột năng`.\n' +
          '- **Không có Nước cốt dừa:** Dùng `200ml sữa tươi không đường + 15g bơ lạt`.\n' +
          '- **Không có Bột năng:** Thay bằng `Bột bắp` hoặc `Bột sắn dây` tỷ lệ `1:1`.\n' +
          '- **Không có Rượu nấu ăn:** Dùng `Gừng tươi đập dập + 1 muỗng giấm/cốt chanh`.',
        recipes: [],
        suggestions: [
          'Tôi không có xì dầu thì thay bằng gì?',
          'Thiếu nước cốt dừa thay bằng gì?',
          'Thiếu bột năng thay bằng gì?'
        ]
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
          suggestions: ['Cách nấu ' + rec.title, 'Thực đơn 3 bữa 1500 kcal', 'Thịt gà của tôi bị hôi có thể xử lí bằng gì?']
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
        suggestions: ['Tôi có thịt bò, trứng gà, cà chua thì nấu món gì?', 'Phở bò Hà Nội cho 8 người', 'Tôi không có xì dầu thì thay bằng gì?']
      };
    }

    // 5. Có nguyên liệu này nấu món gì? (Nhóm 1 - Fridge Matcher)
    // Không kích hoạt tìm theo tủ lạnh nếu câu hỏi là về sự cố / sơ chế ("bị ...", "xử lí", "khử mùi"...)
    var isProblemQuery = ['bi ', 'xu li', 'xu ly', 'khu mui', 'lam sach', 'so che', 'tai sao', 'vi sao', 'chua '].some(function (kw) {
      return norm.indexOf(kw) !== -1;
    });
    if (!isProblemQuery) {
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
          suggestions: ['Thịt gà của tôi bị hôi có thể xử lí bằng gì?', 'Tôi không có xì dầu thì thay bằng gì?', 'Thực đơn 3 bữa 1500 kcal']
        };
      }
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
