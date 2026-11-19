# CookMate Ollama + Gemini chatbot report

Date: 2026-11-17

## Implementation

- Ollama `qwen3.5:4b` is the chatbot primary. Gemini is called only after a connection/model failure, timeout, empty or truncated output, thinking leakage, or a custom recipe that fails the ingredient checks. Gemini order remains `gemini-3.6-flash` then `gemini-4-hydrogen`.
- `/api/chat` sends top-level `think: false` and `stream: false`; `think` is not in `options`. The client reads only `message.content`, rejects empty/truncated content, and never returns `message.thinking`.
- MySQL retrieval uses the current ingredient catalog, approved recipes, recipe ingredients, recipe steps and saved nutrition. A title mention is not treated as pantry inventory. Custom recipes are labeled and checked against a CookMate proposal plan; invalid output tries Gemini, then uses a bounded CookMate recipe template where one is available.
- No MySQL schema or data changes were made. Chat failures still save the user/assistant exchange to the chat history.

## Runtime settings and performance

- Ollama version: `0.40.16`; `/api/show` reports `thinking` capability for `qwen3.5:4b`.
- `num_ctx=4096`, `num_predict=360`, up to 4 prior user/assistant turns, `keep_alive=5m`, timeout 90 seconds.
- The actual request shape and content-only behavior pass unit tests. Live responses contained no non-empty thinking field; the manager also rejects any response where `thinking` is non-empty.
- In the final live prompt run, four Ollama generations averaged **11.5 seconds** end to end and **140 generated tokens**. Individual generation times were about 9.6s, 10.1s, 11.3s and 14.7s. Static or guarded cases returned in under 30ms.
- First cold model load measured about 7.6 seconds; warmed requests reported roughly 5–8ms load time.
- Ollama `/api/ps` reported a 3.74GB model allocation, 4096 context, and 1.88GB allocated to VRAM. `ollama ps` reported a 50% CPU / 50% GPU split. Exact RAM-only model use is not exposed by this snapshot; the Ollama server processes showed about 95MB combined working set, which does not account for all mapped model memory. GPU snapshot: RTX 2050, 2546/4096MiB in use across the system.

## Requested scenarios

| Case | Result |
|---|---|
| TC01 — chicken and tomato | PASS. Ollama generated a short AI suggestion; MySQL had no matching approved recipe. The response separated available ingredients from items to prepare. |
| TC02 — substitute for soy sauce | PASS. CookMate recommended diluted fish sauce with a clear taste difference and did not treat sugar as a substitute. |
| TC03 — egg, tomato and scallion | PASS. Ollama used the stated ingredients and listed oil/seasonings separately. No matching approved recipe was presented as a database recipe. |
| TC04 — chicken and tomato soup | PASS. The response was labeled as a generated suggestion because no matching database recipe was found. Inventory text is normalized so dish ingredients are not claimed as pantry items. |
| TC05 — chicken tomato sauce for two | PASS. The response used a two-person quantity plan, listed all ingredients as needing preparation, and did not attribute the suggestion to MySQL. |
| TC06 — no cooking oil | PASS. A short no-oil tomato-and-egg soup suggestion uses no oil and marks all ingredients as needing preparation. |
| TC07 — estimate nutrition | PASS. No matching saved nutrition was found; CookMate declined to invent a number. |
| TC08 — quadratic equation | PASS. The domain guard refused the non-food request before calling either model. |

## Fallback and automated checks

- Fallback order was confirmed by mocked tests: Ollama failure → Gemini 3.6 Flash → Gemini 4 Hydrogen, with no unbounded retries. Successful Ollama answers skip Gemini.
- Live Gemini fallback was attempted during the earlier output-quality checks: Gemini 3.6 Flash returned HTTP 504; Gemini 4 Hydrogen returned HTTP 503/504. The app then returned a safe CookMate template for covered recipes. The Gemini fallback path is implemented and order-tested, but live Gemini generation was unavailable during this run.
- Full suite: **66 tests passed, 1 opt-in live Gemini test skipped**. MySQL read integration passed. `node --check assets/js/chatbot.js` and Python compilation passed.

## Limitations

- The 4B model can produce extra or poorly categorized ingredients on open-ended recipes. CookMate now rejects custom output that includes known catalog ingredients outside the proposal and uses a small validated template set when both Gemini services fail. That validation and template coverage is not exhaustive for every possible dish.
- Gemini availability is external and was intermittent during this run. Live Gemini generation could not be confirmed; the service will use its safe error response or an available CookMate template.
- Memory values are a local snapshot. Actual RAM use varies with Ollama's CPU/GPU offload, other processes, and model load state.

## 100-recipe MySQL catalog expansion

- Added 100 complete Vietnamese recipes with the requested category split: 24 mains, 14 soups, 12 stir-fries, 14 grilled/fried dishes, 12 vegetarian dishes, 8 desserts, 6 drinks, and 10 appetizers. No target name or slug existed before the import, so no duplicate targets were skipped.
- The verified import added 100 dishes, 100 recipes, 130 normalized ingredients, 827 recipe-ingredient links, 359 dish-matching links, and 400 stored steps. Totals after import: 116 dishes, 116 recipes, 160 ingredients, 927 recipe-ingredient rows, and 479 steps. The eight category totals are 27, 18, 13, 17, 13, 9, 7, and 12 in the order above.
- `scripts/seed_100_recipes.py --dry-run` after import found all 100 target slugs, zero pending dishes, and zero new ingredients/links/steps. An audit compared every saved ingredient, quantity, note, step, and dish-matching link to the source catalog: 0 mismatches. Two newly added fruit ingredients were corrected to the `Trái cây` category after a full backup; schema and unrelated records were not changed.
- Integrity check: all 100 targets have exactly one approved recipe, 5–10 recipe ingredients, 3–7 dish-matching links, and 4 steps; ingredient foreign-key checks found no broken links. No recipe sources were invented. Nutrition stays unknown (database defaults); images use the application's default image.
- Live Flask test-client checks against local MariaDB: title search returned `Mì Quảng gà`; category + `Dễ` + 45-minute filters returned 10 recipes satisfying every filter; ingredient matching returned `Bò xào bông cải xanh` at 70% with `Tỏi` correctly listed as missing; detail returned 9 ingredients and 4 steps. Five API calls averaged **42.7 ms** on this machine.
- Added static catalog tests for exact count/distribution, unique slugs, and complete ingredient/step ranges. Full suite: **68 passed, 1 opt-in live Gemini test skipped**; MySQL read integration passed.

---

## Comprehensive Production Upgrade & Verification (2026-11-18)

### Gate G1 — Static Syntax & UI Production Hygiene
- Executed `py_compile` across **48** project Python files (excluding `.venv`): **PASS**.
- Executed `node --check` (`Node v24.19.0`) across **13** frontend JS files in `assets/js/`: **PASS**.
- Verified **32** inline `<script>` blocks across **23** HTML files (`index.html` + `pages/**/*.html`) via Node `new Function`: **0 syntax errors**.
- Hygiene audit scan confirmed **0** occurrences of `setupDemoAccounts`, `"tài khoản mẫu"`, `"bản thử nghiệm"`, `"demo count"`, `"giả lập"`, `"Thử nghiệm luồng rẽ nhánh"`, `"fa-sparkles"`, or hardcoded API keys.

### Gate G2 — MySQL / phpMyAdmin 200-Recipe Package & Integrity Audit
- Resolved a pre-existing MariaDB `10.4.32` InnoDB `DICT_SYS` mutex deadlock on test schema `cookmate_clean_test` by cleanly restarting `mysqld.exe` and importing `database/cookmate_200_recipes_phpmyadmin.sql` (573.2 KB).
- Two consecutive idempotent imports into `cookmate` succeeded without errors (**0.24s** on re-import).
- Live SQL audit confirmed **17 tables**:
  - `recipes`: **200** (`APPROVED`), split strictly across 8 categories `[45, 30, 25, 25, 25, 18, 14, 18]` matching `categories.recipe_count`.
  - `dishes`: **200**, `ingredients`: **234**, `recipe_ingredients`: **1,611**, `dish_ingredients`: **1,507**, `recipe_steps`: **815**.
  - `chatbot_knowledge_base`: **211**, `chatbot_synonyms`: **90**, `chatbot_learned_qa`: **28**, `users`: **6**, `categories`: **8**.
- Integrity audit confirmed **0** recipes with non-positive nutrition macros (`<= 0`), **0** orphan foreign keys across `recipe_ingredients`/`recipe_steps`/`dish_ingredients`, and **0** non-vegan ingredients in Category 5 (`Món chay`) after sanitizing legacy `'Nước mắm'` to `'Nước mắm chay'` in `scripts/build_200_phpmyadmin_sql.py`.

### Gate G3 & G4 — Unified Entrypoint & Live Gemini Smart Resolver Failover
- `python main.py --check-only` exited `0`: `mysql.ok=true` (17 tables), `ollama.running=true` (`qwen3.5:4b`), `gemini.sdk_status=READY` (`google-genai 3.3.0`, **19** `generateContent` text models discovered).
- Live failover test verified both `.env` default (`gemini-3.6-flash` / `gemini-4-hydrogen`) and injected non-existent model (`gemini-nonexistent-check-404`): automatically resolved via `client.models.list()` to working `gemini-3-flash-preview` (**20.02s** / **21.58s** on first failover, **3.57s** on cached follow-up call).

### Gate G5 — Live Flask `/api/health` & 10 ChefBot Scenarios + Self-Learning Feedback
- Executed end-to-end against live `http://127.0.0.1:5000`:
  - `GET /api/health` returned `200` (`totalRecipes: 200`, `totalCategories: 8`, `totalIngredients: 234`, `kbCount: 211`, `learnedQaCount: 28`, `ollama.warmed_up: true`).
  - **S1–S10 live results** (`PASS 10/10`):
    - S1 Pantry matching (`trứng gà, cà chua, đậu hũ, hành lá` — fixed `"ga"` substring trap): `200`, **10,220.6 ms**, `ollama_rag`, returned `Đậu hũ sốt cà chua thanh đạm` (`recipes=2`, `qaId=127`).
    - S2 Soy sauce substitution: `200`, **22,778.0 ms**, `ollama_custom`, grounded fish-sauce dilution ratio (`qaId=128`).
    - S3 Over-salted soup rescue: `200`, **6,252.8 ms**, `ollama_custom` (`qaId=129`).
    - S4 Portion scaling (2 -> 5): `200`, **14,474.4 ms**, `ollama_rag` (`recipes=2`).
    - S5 Phở bò Hà Nội macro nutrition lookup: `200`, **4,711.7 ms**, `ollama_rag` (`446 calo, 30.8g protein, 44.1g carbs, 15.6g fat, 2.2g fiber`, `qaId=130`).
    - S6 Vegan no-oil constraint: `200`, **11,977.8 ms**, `ollama_rag`, pure plant-based recommendation (`qaId=131`).
    - S7 Dessert / drink query: `200`, **14,951.3 ms**, `ollama_rag` (`Sinh tố dưa hấu bạc hà`, `qaId=132`).
    - S8 Regional synonyms (`trái thơm, đậu phụ`): `200`, **6,446.7 ms**, `ollama_rag`, normalized to `Dứa, Đậu hũ` (`qaId=133`).
    - S9 Off-topic guard (bitcoin + C++): `200`, **7.6 ms**, `mode=guard`, `classification=OFF_TOPIC`, zero LLM calls.
    - S10 Self-learning tip + 2x feedback promotion (`POST /api/chatbot/feedback`): `qaId=134` created (`quality_score=0.72, is_verified=0`), promoted on 2 positive ratings (`18.0 ms` / `5.4 ms`) to `quality_score=1.02, is_verified=1` in MySQL (test QAs cleaned back to 28 baseline).

### Gate G6 — Automated Python Unit & Integration Tests
- Added 4 test modules: `tests/test_gemini_smart_resolver.py`, `tests/test_ollama_lifecycle.py`, `tests/test_chatbot_self_learning.py`, `tests/test_phpmyadmin_sql_and_rbac.py`.
- Result: **Ran 81 tests — OK (skipped=1)** (`test_gemini_integration.py` opt-in live quota guard).

### Gate G7 — Headless Chrome CDP E2E, RBAC Workflow & 8-Viewport Overflow Audit
- Audited via Chrome Headless CDP (`--headless=new`) across all public, auth, member, and admin pages:
  - **12 public & auth routes + 5 admin SPA routes + `/pages/account/my-recipes.html`**: **0** console errors, **0** uncaught exceptions, **0** HTTP 404/500 application/API responses (browser default `/favicon.ico` probe excluded).
  - Protected branding & layout: Dark footer `rgb(41, 37, 36)` with loaded `hanoi-pho-art.svg` and zero duplicate auth links; ChefBot panel branded `"Đầu bếp CookMate AI — Trợ lý Ẩm thực & Dinh dưỡng"`; windowed pagination (`7` items + ellipsis across `200` recipes, interactive page 2 verified); `login.html` / `register.html` `0` `.auth-demo-box`, `.pho-stage` (`PHỞ HÀ NỘI`) visible at `1280px` and `display: none` at `375px`.
  - Full RBAC roundtrip verified end-to-end: Member submission forced `pending` -> Admin rejected with reason -> Member UI displayed rejection reason -> Member edit reset to `pending` -> Admin approved -> temporary test recipe deleted cleanly (`200` recipes preserved).
  - Admin SPA Shell: `#sidebarToggleBtn` toggled width `260px -> 0px -> 260px`, mobile header height **82.83px** (`<= 97px`).
  - **56/56 responsive checks** (`0px` horizontal overflow across `320, 375, 390, 414, 768, 1024, 1440, 1920px` on 7 core routes): **PASSED**.


---

## Database-Only ChefBot, Exact Ingredient Search, Unified Homepage Search & 208 Real Food Photos Verification (2026-11-18)

### Gate G1 — Syntax & Unit Test Suite (`100% PASS`)
- `py_compile` across **50** Python files: **PASS**.
- `node --check` across **13** Frontend JavaScript files: **PASS**.
- `python -m unittest discover -s tests -v`: **Ran 87 tests in 0.589s — OK (skipped=1)**, including new `tests/test_search_and_db_only_chatbot.py` covering NFC diacritic/whole-word `"Ức Gà"` / `"ức gà"` / `"uc ga"` scoring, Category 5 vegan exclusion, Ingredient Family `OR`-Grouping, longest-span masking, and foreign-dish Top-3 DB fallback.

### Gate G2 — Idempotent phpMyAdmin SQL Import & MySQL Audit (`100% PASS`)
- Rebuilt and re-imported `database/cookmate_200_recipes_phpmyadmin.sql` (**576.6 KB**) into live MySQL `cookmate` with **0 SQL errors**.
- Verified **8/8** categories use unique HTTPS real food photos (`0` `.svg`), **200/200** `APPROVED` recipes use **200 unique** HTTPS dish-matched real food photos (`0` `.svg`), **0** recipes missing macros (`calories, protein, carbs, fat, fiber > 0`), and **0** polluted `chatbot_learned_qa` rows.

### Gate G3 — Live Search Precision Audit (`/api/recipes?q=...` & `pages/search.html`, `100% PASS`)
- `"Ức Gà"`, `"ức gà"`, `"uc ga"` each returned **8** exact chicken-breast recipes (`#134 Ức gà sốt cà chua đậm đà [100 pts]`, `#143 Súp gà kem bắp ngọt sánh mịn [85 pts]`, `#14 Gà kho gừng ấm nồng ngày trở gió [85 pts]`, `#8 Gà nướng sả ớt da giòn thơm lừng [85 pts]`, `#145 Canh gà nấu cà chua dứa [85 pts]`, `#107 Nộm gà xé phay [85 pts]`, `#51 Súp gà ngô non [85 pts]`, `#17 Cơm gà Hội An [85 pts]`): **0% Món chay**, **0% Nấm đùi gà**, **0% Lẩu nấm / Bún bò Huế**.
- Tested 10 additional keywords (`Thịt bò` [13], `Cá lóc` [3], `Tôm` [26], `Đậu hũ` [22], `Trứng gà` [21], `Sườn` [9], `Cà chua` [30], `Nấm` [33], `Bún bò` [1 -> `Bún bò Huế cay nồng chuẩn vị Cố đô`], `Chè` [9]): **100% PASS**, **0%** vegan false positives on animal queries.

### Gate G4 — Live 100% Database-Only ChefBot Audit (`POST /api/chatbot`, `11/11 PASS`)
- Tested `"Tôi có thịt gà và cà chua, nấu món gì?"` + 10 ingredient, scaling, calorie, oil-free, and foreign-dish (`sushi cá hồi`) queries against live `http://127.0.0.1:5000/api/chatbot`:
  - **11/11** responses cited exact `APPROVED` MySQL recipe titles, gram/ml/unit quantities, MySQL `kcal` figures, and returned `recipes >= 1` clickable cards.
  - **0/11** contained `"chưa có trong CSDL CookMate"`, `"Gợi ý tự nấu"`, or `<think>`.

### Gates G5, G6, G7, G8 — Real Headless Chrome CDP Verification (`100% PASS`)
- **Gate G5 (Homepage Unified Search & Header Clearance):**
  - Visible search `<input>` count on `/` = **1** in default keyword mode AND **1** after switching `#heroTabPantry` (`6` matched recipes rendered inline for `Thịt gà + Cà chua`).
  - Header clearance (`headingTop - headerBottom`): `/`: **+72px**, `/pages/search.html`: **+111px**, `/pages/recipes.html`: **+24px**, `/pages/categories.html`: **+64px**, `/pages/new-recipes.html`: **+64px**, `/pages/featured-recipes.html`: **+64px**, `/pages/holiday-recipes.html`: **+64px**, `/pages/recipe-detail.html?id=134`: **+171px** (**0px** clipped).
  - `#aiSearchBtn` on `/pages/search.html`: full text `"Tìm thêm bằng AI"`, `width=136px`, `clientWidth=132px`, `scrollWidth=132px` (`clipped=false`), sort label single-line `height=26px`.
- **Gate G6 (Real Chrome Image Decode Audit):**
  - `/` and `/pages/categories.html`: **8/8** category photos loaded (`complete=true`, `min naturalWidth=600px`, `0` `.svg`).
  - Self-healed `#93 Chè đậu xanh nước cốt dừa` (`quanche.vn` -> `cdn.tgdd.vn` `800x500` JPEG), rebuilt SQL & re-imported MySQL -> **200/200 (`100%`)** recipe photos decoded in real Chrome (`complete=true`, `naturalWidth >= 300px`, `broken=0`).
- **Gate G7 (E2E Search DOM & ChefBot Widget Navigation):**
  - `/pages/search.html?q=Ức%20Gà` rendered all **8** chicken-breast cards with real chicken photos; ChefBot widget answered `"Tôi có thịt gà và cà chua, nấu món gì?"` with DB cards `['Ức gà sốt cà chua đậm đà', 'Canh gà nấu cà chua dứa', 'Mì Quảng gà']` and clicking card #1 navigated to `/pages/recipe-detail.html?id=134` (`h1='Ức gà sốt cà chua đậm đà'`).
- **Gate G8 (8-Viewport Responsive & Console Hygiene Audit):**
  - Across `320, 375, 390, 414, 768, 1024, 1440, 1920px` on User, Auth (`.pho-stage` hidden `<1024px`, visible `>=1024px`), and Admin SPA Shell (`#sidebarToggleBtn`, mobile header `<= 97px`): **0** horizontal overflows, **0** JS console/page errors, **0** HTTP 404/500 responses.


---

## 300-Recipe Regional Upgrade, 6–8 Detailed Culinary Steps, Gemini Free Priority -> Ollama, Expanded ChefBot UI & Unified phpMyAdmin SQL Verification (2026-11-18)

### Gate G1 — Static Syntax, Unit Test Suite & Single-SQL Hygiene (`100% PASS`)
- `py_compile` across **54** Python files: **PASS** (`0` syntax errors).
- `node --check` across **13** Frontend JavaScript files in `assets/js/`: **PASS** (`0` syntax errors).
- `python -m unittest discover -s tests -v`: **Ran 91 tests in 0.668s — OK (skipped=1)**, including new multi-ingredient `AND` intersection, incompatible-combo `5x` protein weighting, regional dish synonym tests (`tests/test_recommendation_match.py`), reversed `Gemini #1 -> Gemini #2 -> Ollama` priority tests (`tests/test_chatbot_service_errors.py`, `tests/test_chatbot_retrieval.py`), and unified `cookmate_full_database.sql` schema/view assertions (`tests/test_database_schema.py`, `tests/test_phpmyadmin_sql_and_rbac.py`).
- `database/` directory audit: contains **ONLY ONE** `.sql` file — `database/cookmate_full_database.sql` (**1,883,728 bytes** / **1,839.6 KB**) alongside preserved `database/cookmate.db`.

### Gate G2 — Clean Idempotent phpMyAdmin SQL Import & 300-Recipe Integrity Audit (`100% PASS`)
- Executed **2 consecutive CLI imports** of `database/cookmate_full_database.sql` without specifying a database name on the command line (verifying embedded `CREATE DATABASE IF NOT EXISTS cookmate ...; USE cookmate;`): **0 SQL errors** on both runs.
- Live MySQL `cookmate` verification:
  - **17** `BASE TABLE`s (all with Vietnamese `COMMENT='...'`) + **1** `VIEW` (`v_danh_sach_300_mon_an` returning **300** rows ordered `ma_mon = 1..300`, `0` `DEFINER` clauses).
  - `dishes = 300`, `recipes (APPROVED) = 300` distributed across 8 categories `{1: 71, 2: 47, 3: 28, 4: 43, 5: 31, 6: 26, 7: 20, 8: 34}` matching `categories.recipe_count`.
  - `ingredients = 278`, `recipe_ingredients = 2,388`, `dish_ingredients = 2,384`, `recipe_steps = 1,964`, `chatbot_knowledge_base = 211`, `chatbot_synonyms = 126`, `chatbot_learned_qa = 28`.
  - Step & FK integrity: **300/300** recipes have **6–7** sequential steps (`avg_instruction_chars = 306.7`), **0** generic `"Bước X"` step titles, **0** steps with `duration_mins <= 0`, **0** empty `tip_note` rows, **0** orphan foreign keys (`orphan_ri = 0`, `orphan_di = 0`), **0** recipes with zero/negative nutrition macros, and **0** animal ingredients in Category 5 (`Món chay`).

### Gate G3 — Real Headless Chrome Image Decode Audit Across 308 Photos (`100% PASS`)
- Loaded all **8** category images and all **300** `APPROVED` recipe `image_url` entries inside real Headless Chrome via CDP:
  - Categories: **8/8** (`complete === true`, `naturalWidth >= 600px`, `0` `.svg`).
  - Recipes: **300/300** (**300 unique HTTPS URLs**, `complete === true`, `naturalWidth >= 300px`, `0` broken/404 images).

### Gate G4 — Multi-Ingredient `AND` Intersection & Regional Synonym Search (`100% PASS`)
- `POST /api/recommendations/match`:
  - `["Cá basa", "Bột bắp"]` -> `fullMatch: true`, `count: 1`, `['Cá basa phi lê tẩm bột bắp chiên giòn sốt me']` (**0** *Khoai tây chiên* or partial starch matches).
  - `["Thịt gà", "Cà chua"]` -> `fullMatch: true`, `count: 3`, `['Ức gà sốt cà chua đậm đà', 'Canh gà nấu cà chua dứa', 'Mì Quảng gà']`.
  - `["Thịt bò", "Bông cải xanh"]` -> `fullMatch: true`, `count: 1`, `['Bò xào bông cải xanh']`.
  - `["Cá lóc", "Dứa"]` -> `fullMatch: true`, `count: 2`, `['Cá lóc nướng mỡ hành đậu phộng cuốn bánh tráng', 'Canh chua cá lóc miền Tây']`.
  - `["Trứng gà", "Cà chua"]` -> `fullMatch: true`, `count: 4`, top `['Canh cà chua trứng', 'Mực nhồi thịt sốt cà chua', 'Bò né chảo gang ốp la']`.
  - Incompatible combo `["Thịt trâu gác bếp", "Bột rau câu"]` -> `fullMatch: false` with clear Vietnamese fallback notice and `5x` Core Protein weighting.
- `GET /api/recipes?q=...`:
  - `q="bún chả quạt"` -> `['Bún chả Hà Nội nướng than hoa']`.
  - `q="thịt kho hột vịt"` -> `['Thịt kho tàu nước dừa trứng vịt']`.
  - `q="Ức Gà"` -> **11** chicken-breast recipes (`0` vegan dishes).

### Gate G5 — Reversed AI Priority (`Gemini Free #1 -> Gemini Free #2 -> Ollama`) & `aiDiagnostics` (`100% PASS`)
- Live `POST /api/chatbot` called `GEMINI_PRIMARY_MODEL` (`gemini-2.5-flash`) first; on HTTP 404 for that model ID on the active API key, Smart Discovery mapped immediately to `gemini-3-flash-preview` (`HTTP 200`, `activeProvider: "gemini"`, `geminiFailed: false`), returning grounded 300-recipe MySQL answers (`Bún thang Hà Nội tinh hoa phố cổ`, `Cá basa phi lê tẩm bột bắp chiên giòn sốt me`).
- Simulated dual-Gemini HTTP 429 rate-limit test verified seamless failover to local `Ollama` (`activeProvider: "ollama"`, `modelUsed: "ollama/qwen3.5:4b"`, `geminiFailed: true`, `attemptedModels: ["gemini-2.5-flash", "gemini-2.5-flash-lite"]`) with exact Vietnamese warning `userWarningVi`.

### Gates G6, G7, G8 — Real Headless Chrome CDP UI, ChefBot & 8-Viewport Audit (`100% PASS`)
- **Gate G6 (Pantry Popover & 6–8 Step Detail UI):**
  - `/` (`#heroTabPantry`): `datalistCount: 0`, `.pantry-suggest-popover` visible (`height: 240px`, `width: 680px`, `12` categorized items); selecting `Cá basa` + `Bột bắp` rendered `Cá basa phi lê tẩm bột bắp chiên giòn sốt me` with badge `"Khớp đủ 2/2 nguyên liệu đã chọn"` (`Sẵn sàng 86% nguyên liệu chính · 40 phút · 596 kcal`).
  - `/pages/recipe-detail.html?id=6` & `?id=201` (`Bún thang Hà Nội tinh hoa phố cổ`): `7` sequential steps rendered with meaningful culinary titles (`genericTitles: 0`), `7/7` `⏱️ X phút` badges, `7/7` `💡 Bí quyết Đầu bếp` tip boxes, base font `15.5px` expanding to `20px` in Kitchen Mode.
- **Gate G7 (Expanded ChefBot UI, Contrast & Warning Banner):**
  - `#cmChefBotPanel` Desktop default `480px × 740px`, expanded via `#cmBotExpand` to `780px × 792px`; redundant `"TRỢ LÝ BẾP"` badge removed (`badgeExists: false`, `headerOverlap: false`); `<textarea>` `overflowY: "hidden"` on single-line input; user message text `rgb(255, 255, 255)` on `#E85D2A -> #D94E1F` gradient; recipe card thumbnails `64×64px`; live status `"🟢 Gemini (gemini-3-flash-preview)"` and amber warning banner + `"🟡 Đang dùng Ollama cục bộ (ollama/qwen3.5:4b)"` verified when `geminiFailed === true`.
- **Gate G8 (8-Viewport Responsive & Admin SPA Shell):**
  - Across `320, 375, 390, 414, 768, 1024, 1440, 1920px` on Home, Search, Recipes, Recipe Detail, Login (`.pho-stage` hidden `<1024px`, visible `>=1024px`), and Admin SPA Shell: **`overflowCount: 0`**, **`consoleErrorCount: 0`**, **`httpErrorCount: 0`**.
