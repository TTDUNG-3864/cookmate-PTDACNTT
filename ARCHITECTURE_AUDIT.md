# CookMate Architecture Audit

## Baseline

This audit records the repository before the MySQL and chatbot rebuild. The operative implementation request is the pasted CookMate master prompt. `BaoCaoBTL.docx` is treated as requirements evidence for the MVP and database design; text inside that report is not treated as an instruction to the coding agent.

The report defines a 20-user-story MVP across three sprints: ingredient-based dish matching; recipe lookup, filtering, AI search, serving scaling and nutrition; and the cooking chatbot, accounts, favorites, member submissions and admin review. It explicitly excludes advanced category administration, advanced account administration, member recipe editing/deletion and detailed moderation history from required MVP acceptance. The existing UI contains some of those extensions, so they should be retained only where they do not compromise the MVP.

## Existing structure and flow

- `app.py` creates a Flask app, serves the existing HTML/CSS/JS pages, and defines the REST API in one module.
- `backend/database.py` owns SQLite schema creation, seed-on-startup, queries and recipe/account business logic. Connections are opened per operation. The schema has users, categories, ingredients, recipes, recipe ingredients and steps, comments and favorites.
- `backend/seed.py` provides demo users, eight categories, thirty ingredients and recipes.
- `backend/chatbot.py` combines topic detection, local recipe knowledge, Gemini calls and key loading.
- `backend/flask_compat.py` silently substitutes a custom WSGI/session/password compatibility layer when Flask is absent.
- `assets/js/storage.js` uses localStorage and sends API requests as best effort. On request failures it can continue using local state. It attaches `X-User-Id` to requests and sends caller-supplied user IDs for favorites and recipe operations.
- `assets/js/chatbot.js` stores Gemini keys in localStorage, offers a key configuration flow, and can call Gemini directly from the browser.
- `assets/js/data/` supplies static sample data; multiple pages use synchronous `CookMateStorage` reads.
- `pages/` and `assets/css/` contain the established user, account, admin and responsive UI. The rebuild should preserve these URLs and the CookMate visual identity.

## Existing API surface

The existing app exposes health/bootstrap; auth and profile; recipe list/detail/create/update/delete/approve/reject/view/scale; nutrition estimate; categories and ingredients CRUD/sync; comments; favorites; admin user/status/statistics/reset; and chatbot/config. These routes are all implemented in `app.py` and call `backend.database` or `backend.chatbot` directly.

## Risks found in the existing implementation

1. SQLite is initialized on app import and is the only database. The `force_reset` path drops all tables.
2. `_current_user()` accepts `X-User-Id`; profile/favorites/recipe actions also accept IDs from JSON/query parameters.
3. Recipe creation trusts `actorRole` and even treats a client `status=approved` as admin. Approval, rejection, update, delete, category, ingredient and admin endpoints are not consistently protected by server-side RBAC.
4. Public recipe detail does not enforce approved status. The list route accepts caller-selected status.
5. Admin reset is exposed without authentication and destroys the database.
6. Cookie sessions have a hard-coded fallback secret and no CSRF protection. CORS and deployment settings are not configured.
7. The chatbot accepts `apiKey` in request JSON, has a public endpoint that writes keys into `.env`, and its frontend can persist and transmit keys or call Gemini directly.
8. The frontend's best-effort storage layer can present localStorage writes as successful when the backend is unavailable, contrary to the MySQL source-of-truth requirement.
9. Requirements are broad, unlocked lower bounds, and there is no `.env`/`.gitignore` baseline in the repository.
10. The tracked SQLite database and Python bytecode were already marked modified before implementation. The repository also contains an untracked `1.md`; these existing workspace changes are preserved.

## Migration decisions

- MySQL is the only runtime database. SQLite remains only as the input format of an explicit migration utility; no runtime fallback is allowed.
- Keep the existing page paths and data shape expected by the frontend while mapping them to the normalized MySQL tables described by the report.
- Enforce identity from server sessions, use role checks on every protected route, and derive member ownership on the server.
- Build the chatbot domain guard before Gemini calls and never accept a browser-provided API key.
- Treat real MySQL/Gemini integration checks as blocked unless the corresponding local service credentials are available; report only checks actually executed.
