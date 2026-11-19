/**
 * CookMate - Danh sách 8 danh mục món ăn chuẩn ảnh chụp ẩm thực thật
 * Dữ liệu chuẩn đồng bộ MySQL bảng categories (0 file .svg)
 */

const CATEGORIES = [
  {
    id: 1,
    name: 'Món chính',
    slug: 'mon-chinh',
    icon: 'fa-utensils',
    image: 'https://www.cet.edu.vn/wp-content/uploads/2018/03/thit-kho-tau-trung-cut.jpg',
    description: 'Các món mặn, kho, rim, bún cơm đậm đà cho bữa chính.',
    recipeCount: 45
  },
  {
    id: 2,
    name: 'Món canh - Súp',
    slug: 'mon-canh-sup',
    icon: 'fa-bowl-food',
    image: 'https://cdn2.fptshop.com.vn/unsafe/2024_3_23_638467922672032197_batch_cach-nau-canh-chua-ca-loc.jpg',
    description: 'Canh chua, súp bổ dưỡng và bún phở nước dùng thanh ngọt.',
    recipeCount: 30
  },
  {
    id: 3,
    name: 'Món xào',
    slug: 'mon-xao',
    icon: 'fa-fire',
    image: 'https://cdn2.fptshop.com.vn/unsafe/thit_bo_xao_thap_cam_2_7bb704dd0b.png',
    description: 'Món xào nhanh lửa lớn giữ trọn độ giòn xanh và hương vị.',
    recipeCount: 25
  },
  {
    id: 4,
    name: 'Món nướng - Chiên',
    slug: 'mon-nuong-chien',
    icon: 'fa-drumstick-bite',
    image: 'https://www.huongnghiepaau.com/wp-content/uploads/2018/06/ga-nuong-mat-ong.jpg',
    description: 'Món nướng thơm lừng và món chiên giòn rụm vàng ươm.',
    recipeCount: 25
  },
  {
    id: 5,
    name: 'Món chay',
    slug: 'mon-chay',
    icon: 'fa-leaf',
    image: 'https://cdn.tgdd.vn/2024/01/CookRecipe/GalleryStep/thanh-pham-44.jpg',
    description: 'Thực đơn thuần thực vật thanh đạm, đủ đạm và cân bằng dinh dưỡng.',
    recipeCount: 25
  },
  {
    id: 6,
    name: 'Món tráng miệng',
    slug: 'mon-trang-mieng',
    icon: 'fa-ice-cream',
    image: 'https://www.lorca.vn/wp-content/uploads/2022/11/maxresdefault-8.jpg',
    description: 'Chè truyền thống, bánh ngọt, rau câu và tráng miệng thanh mát.',
    recipeCount: 18
  },
  {
    id: 7,
    name: 'Đồ uống',
    slug: 'do-uong',
    icon: 'fa-mug-hot',
    image: 'https://cdn2.fptshop.com.vn/unsafe/640x0/filters:format(webp):quality(75)/cach_lam_tra_dao_cam_sa_2313d177e5.jpg',
    description: 'Cà phê phin, trà trái cây, sinh tố và sữa hạt bổ dưỡng.',
    recipeCount: 14
  },
  {
    id: 8,
    name: 'Món khai vị',
    slug: 'mon-khai-vi',
    icon: 'fa-plate-wheat',
    image: 'https://www.cet.edu.vn/wp-content/uploads/2018/11/goi-cuon-tom-thit.jpg',
    description: 'Gỏi cuốn, nộm thanh mát, chả giò và món khai tiệc nhẹ.',
    recipeCount: 18
  }
];
