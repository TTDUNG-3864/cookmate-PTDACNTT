# CookMate

CookMate helps people find meals from ingredients, browse and scale approved recipes, save favorites, contribute recipes for review, and ask ChefBot cooking questions. The existing HTML, CSS and JavaScript pages remain in place. Flask serves those pages and the API; MySQL is the only runtime database.

## Requirements

- Python 3.10 or newer
- MySQL 5.7 or MySQL 8 with a database user allowed to create/use the configured database
- Google Gemini API key (`GEMINI_API_KEY`, server-side only) for Priority #1 & #2 Free Tier ChefBot models (`gemini-2.5-flash` -> `gemini-2.5-flash-lite`), plus local Ollama (`qwen3.5:4b`) as Priority #3 offline/quota fallback.

## Local setup

1. Create a virtual environment and install the pinned dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Review `.env.example`, configure MySQL values (`MYSQL_*`), set a strong `COOKMATE_SECRET_KEY`, and set `GEMINI_API_KEY` for Google Gemini Free Tier Priority #1 (`gemini-2.5-flash`) & Priority #2 (`gemini-2.5-flash-lite`). Only when both Gemini models fail does CookMate fall back to local Ollama `qwen3.5:4b` (automatically starting `ollama serve` in the background when `OLLAMA_AUTO_START=true`).

3. **Import unified full database (`database/cookmate_full_database.sql`)**:
   - Open **phpMyAdmin**, click the **Import** tab right from the home screen (or inside `cookmate`), select **`database/cookmate_full_database.sql`**, and click **Go / Thực hiện** (or via CLI: `mysql -u root --default-character-set=utf8mb4 < database/cookmate_full_database.sql`).
   - Safe and idempotent on both empty and populated servers (zero `DROP TABLE` / `DELIMITER` / triggers): automatically creates & selects `cookmate`, builds **17 InnoDB utf8mb4 tables** with Vietnamese table comments + SQL View **`v_danh_sach_300_mon_an`**, and seeds **300 approved Vietnamese & regional specialty recipes** (`ID 1..300` ascending, **6–8 detailed steps/recipe = 1,964 steps**), **278 normalized ingredients**, **211 culinary knowledge entries**, **113 regional synonyms**, and **28 verified Q&As**.

4. Verify runtime readiness or start the app (both entrypoints run the same unified bootstrap):

   ```powershell
   python main.py --check-only   # Inspect MySQL, Ollama & Gemini readiness cleanly
   python main.py                # Starts Ollama automatically if needed + serves Flask on http://127.0.0.1:5000
   # or: python app.py
   ```

   Visit `http://127.0.0.1:5000`. Startup verifies MySQL (`SELECT 1` + core tables + non-destructive schema upgrades) and stops with a server log error if MySQL is unreachable. The app never falls back to SQLite.

## Development accounts

These seeded accounts are for local development only. Replace their passwords and remove or disable them before deployment.

| Role | Email | Password |
|---|---|---|
| Admin | `admin@cookmate.vn` | `admin123` |
| Member | `giang@cookmate.vn` | `giang123` |

Passwords in MySQL are Werkzeug password hashes. New registrations are always assigned the `member` role; clients cannot register as admins.

## Add the 100 curated MySQL recipes

The catalog data lives in `scripts/recipes_100_data.py`; the loader in `scripts/seed_100_recipes.py` does not change the schema or overwrite existing dishes. It resolves categories by slug, normalizes ingredient names, uses generated database IDs, and keeps nutrition unknown when no reliable values are available. Images stay blank so the application can use its default image.

Run the read-only preflight first:

```powershell
python scripts/seed_100_recipes.py --dry-run
```

To apply the 100 recipes, the loader creates a full `mysqldump` backup in the operating system temporary directory, then inserts the catalog in one transaction and verifies recipes, steps, ingredient links, and foreign keys:

```powershell
python scripts/seed_100_recipes.py --apply
```

The loader intentionally stops if any target dish name or slug already exists, rather than partially importing or replacing data. Run the dry-run after import to confirm that all 100 targets are present and no additional rows are pending.

## SQLite migration

The old `database/cookmate.db` remains untouched. SQLite is read only by the explicit migration utility and is not imported by the running app.

To preserve an existing SQLite dataset, create an empty MySQL database, point `MYSQL_DATABASE` in `.env` at that database (or import table definitions from `database/cookmate_full_database.sql`), then run:

```powershell
python -m backend.database.migrations --source database/cookmate.db
```

The migration refuses to write into non-empty target tables, copies the legacy records in a transaction, checks row counts and creator relationships, and leaves the SQLite file in place. Back up both databases before doing a production migration.

## Environment settings

`.env` is ignored by Git. `.env.example` lists the supported settings:

- `COOKMATE_SECRET_KEY`: required session signing secret. Use a long, random value.
- `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`: MySQL connection.
- `MYSQL_POOL_SIZE`: maximum pooled connections.
- `OLLAMA_BASE_URL`: local Ollama URL; defaults to `http://127.0.0.1:11434`.
- `OLLAMA_MODEL`: local primary model; defaults to `qwen3.5:4b`.
- `OLLAMA_AUTO_START`, `OLLAMA_AUTO_PULL`: automatically launch `ollama serve` on startup (`true` by default) and optionally pull missing models (`false` by default).
- `OLLAMA_TIMEOUT`: local generation timeout in seconds; defaults to `90`.
- `OLLAMA_KEEP_ALIVE`: how long Ollama keeps the model loaded; defaults to `15m`.
- `OLLAMA_NUM_CTX`, `OLLAMA_NUM_PREDICT`: bounded context (`4096`) and output token limits (`520`).
- `CHATBOT_HISTORY_TURNS`: number of previous user/assistant turns to keep; defaults to `4`.
- `GEMINI_API_KEY`: optional server-only Gemini Developer API key (`google-genai==3.3.0`) used for cloud fallbacks and web recipe search. Never put it in HTML, JavaScript, browser storage, or requests; matching quotes are stripped automatically.
- `GEMINI_PRIMARY_MODEL`, `GEMINI_FALLBACK_MODEL`: defaults to `gemini-2.5-flash` and `gemini-2.5-flash-lite`; legacy/unavailable aliases automatically fail over via the Smart Model Resolver and `client.models.list()` auto-discovery (30-minute health cache).
- `GEMINI_TIMEOUT`: per-call timeout in seconds (`28`, converted to milliseconds `>= 10000` for `types.HttpOptions`).
- `GEMINI_MAX_RETRIES`: bounded retries for structured transient 429/503/504 errors; defaults to `1` and is capped at `3`.
- `CORS_ALLOWED_ORIGINS`: comma-separated exact origins. Add the deployed frontend origin when frontend and API use separate hosts; do not use `*` with credentials.
- `CHATBOT_ENABLED`, `CHATBOT_DOMAIN_GUARD`, `CHATBOT_RAG_ENABLED`: chatbot feature switches.

**ChefBot ("Đầu bếp CookMate AI — Trợ lý Ẩm thực & Dinh dưỡng")** runs SQL-grounded Hybrid RAG + Self-Learning Memory across three MySQL tables (`chatbot_knowledge_base`, `chatbot_synonyms`, `chatbot_learned_qa`):
1. Regional Vietnamese synonym expansion (`chatbot_synonyms`) and multi-turn verified fast-path lookup (`chatbot_learned_qa`).
2. Local primary inference via Ollama (`qwen3.5:4b`, `/api/chat`, `think: false`, `stream: false`) reading only `message.content`, with strict output validation (no leaked thinking or ungrounded ingredients).
3. Automatic failover to Google Gemini (`google-genai==3.3.0`, `models.generate_content`, `vertexai=False`) via Smart Model Resolver + live model auto-discovery when local generation fails or fails validation.
4. Useful generated cooking answers persist to `chatbot_learned_qa` and return `qa_id`; user feedback (`POST /api/chatbot/feedback` with `rating` `1`/`-1`) updates `quality_score` (`+0.15` / `-0.35`, auto-verifying at `>= 0.95`).

Before generation, CookMate looks up named ingredients in MySQL and searches approved `recipes` and `recipe_ingredients`; retrieved `recipe_steps` and stored nutrition are included only when available. It distinguishes ingredients the user explicitly says they have from ingredients merely named in a requested dish. If no suitable database recipe exists, the model may offer a clearly labeled suggestion using ingredients named in the question and explicitly listed additions; it never assumes the user already has those additions. It does not claim that such a suggestion is a CookMate database recipe or invent stored nutrition.

Missing Gemini credentials do not prevent local Ollama answers. If both Ollama and Gemini are unavailable, the API returns a safe service response. Out-of-domain prompts are blocked before calling either model. Online recipe search still uses Gemini and reports when that feature is unavailable. The user interface never receives credentials or model thinking data.

If `GEMINI_API_KEY` is missing, local Ollama answers remain available; only cloud fallback is unavailable. Out-of-domain prompts are blocked before any model call. The internal cooking guide is used when `CHATBOT_ENABLED=false`. Online recipe search reports when Gemini is unavailable and still returns matching internal recipes; it does not invent website sources.

## API overview

All endpoints return JSON under `/api`.

| Area | Endpoints |
|---|---|
| Status and data | `GET /health`, `GET /bootstrap`, `GET /categories`, `GET /ingredients` |
| Authentication | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `GET /auth/csrf`, `PUT /users/profile` |
| Recommendations | `POST /recommendations/match` |
| Recipes | `GET /recipes`, `GET /recipes/{id}`, `POST /recipes`, `PUT /recipes/{id}`, `DELETE /recipes/{id}`, `GET /recipes/my`, `GET /recipes/{id}/scale?servings=N`, `POST /recipes/ai-search` |
| Favorites | `GET /favorites`, `POST /favorites/toggle` |
| Moderation | `GET /admin/pending-recipes`, `GET /admin/recipes/{id}`, `POST /admin/recipes/{id}/approve`, `POST /admin/recipes/{id}/reject` |
| ChefBot | `POST /chatbot`, `POST /chatbot/feedback`, `GET /chatbot/config`, `POST /chatbot/sessions`, `GET /chatbot/sessions/{id}`, `DELETE /chatbot/sessions/{id}` |

Registration, profile, recipe submission, favorites, comments and moderation use signed server sessions. Mutating authenticated requests must include the `X-CSRF-Token` returned by `/api/auth/csrf`, `/api/auth/me`, login or registration. User IDs and roles sent by the browser are ignored. Public recipe responses contain approved recipes only; members can see their own submissions through `/api/recipes/my`. Editing a submitted recipe sends it back to the pending review queue. Owners can delete their own recipes; administrators can moderate all submissions.

## Tests

Run the local automated checks with:

```powershell
python -m unittest discover -s tests -v
```

Automated tests mock service errors and verify request shape, retrieval boundaries, and fallback order. Live Ollama checks require the local Ollama service and `qwen3.5:4b`; live Gemini checks require a configured Gemini key.

## Deployment

Run Ollama on the same host or a trusted private network as Flask and install `qwen3.5:4b`. Set production MySQL credentials and a strong `COOKMATE_SECRET_KEY`; add `GEMINI_API_KEY` if cloud fallbacks are desired. Set `OLLAMA_BASE_URL` to the reachable private Ollama host and `CORS_ALLOWED_ORIGINS` to the exact frontend origin. Deploy the Flask API behind HTTPS and a production WSGI server; `python app.py` is for local development. For a separately hosted static frontend, configure `window.COOKMATE_API_BASE_URL` before loading the app scripts.

The root `.env` is loaded by absolute path. In local development, its Gemini key takes precedence over process variables; conflicting key sources are detected and logged by source only. In production, process environment values take precedence over `.env`.
