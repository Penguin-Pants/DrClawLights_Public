# DrClawlights v2 — Web Frontend Plan

> **Historical record.** This is the plan the dashboard was built from. `README.md` and the code describe the current state. Known differences: settings are a plain dict (no dataclass); `HIGHLIGHTS_FILE`, `HISTORY_FILE`, `DESIGN_FILE` and `CONFIG_FILE` are environment variables only and are never stored in `config.json`; the send hour and minute have no environment variable (dashboard only); the design-token parser reads every `--name: value;` declaration in the file, not only the Quick Start block, and the last value wins.

## Project Overview

DrClawlights is a Python service that sends a daily email digest of randomly selected Kindle book highlights. It reads a `highlights.json` file (produced by the companion project HighlightsGrabber), picks a random selection, and sends an HTML email via Resend. It runs as a persistent Railway.com service.

Version 2 adds a self-hosted admin dashboard so the owner can manage all settings, upload files, and configure the email format without touching Railway environment variables or manually swapping volume attachments.

---

## Decisions Made

### Hosting
**Same Railway service, single process.**
FastAPI serves the admin UI and runs the APScheduler digest scheduler in a background thread. No second Railway service, no separate deployment.

### Authentication
**Single admin password as a Railway environment variable (`ADMIN_PASSWORD`).**
Login issues a signed session cookie via `itsdangerous`. No database, no user table, no OAuth. One person uses this tool.

### Settings — what goes in the UI vs Railway env vars
**UI-editable (persisted to `/data/config.json`):**
- `FROM_EMAIL` — verified sender address
- `RECIPIENT_EMAIL` — digest recipient
- `BOOKS_PER_EMAIL` — books per digest (default 2)
- `HIGHLIGHTS_PER_BOOK` — highlights per book (default 3)
- Send time — hour + minute (default 06:00)
- Timezone (default Europe/Berlin)
- Email section toggles (Echo, Revisit, Book covers)
- Subject line format template

**Stays as Railway env vars (never shown in UI):**
- `RESEND_API_KEY`
- `ANTHROPIC_API_KEY`
- `ADMIN_PASSWORD`

### Highlights File Upload
**Silent replace.** Uploading a new `highlights.json` silently overwrites `/data/highlights.json`. No preview, no versioning, no confirmation step.

### Send Now
A **Send Now** button on the dashboard triggers an immediate digest send (equivalent to `python main.py --send-now`). Shows inline success/error feedback via HTMX. Primary use: testing after uploading a new highlights file or changing settings.

### Schedule Changes
**Hot-reload in-process.** When the send time or timezone is changed in the UI, the running APScheduler job is cancelled and re-added immediately. No Railway restart required.

### Email Format Controls
Three sub-sections in the Email Format panel:
1. **Design file upload** — upload a new `DESIGN.md`. The email builder parses the CSS custom properties block from the Quick Start section and extracts colour/typography tokens, which are baked into the email's inline styles.
2. **Section toggles** — on/off switches for: Echo section (AI cross-book connection), Revisit section (highlight you haven't seen in a while), Book cover images.
3. **Subject line format** — a text field with a template string (e.g. `Today's highlights from {book1} & {book2}`) with a live preview of what it renders to.

### Design Token Parsing
**Parse the CSS custom properties block from the markdown file.** Regex finds the triple-backtick CSS block under `### CSS Custom Properties` in the Quick Start section and extracts `--color-*` and typography tokens. These are mapped to email CSS at build time. Works automatically with the current `DESIGN.md` format.

⚠️ *This is the one decision that would be moderately painful to undo — if the design.md format changes significantly, the parser would need updating. Acceptable trade-off for a single-user tool.*

### Email Preview
**Rendered iframe, inline in the Email Format panel.** The server generates the actual email HTML using a random sample from the current `highlights.json` and current settings, and returns it into a sandboxed `<iframe>` on the page. Updates automatically via HTMX when section toggles or subject format change.

### Page Interaction Style
**HTMX.** A ~14 KB script tag, no build step, no JS framework. The server returns HTML fragments that swap into the page. Used for: Send Now feedback, email preview refresh on toggle change, flash messages.

### Web Framework
**FastAPI + Jinja2** server-rendered HTML templates. No separate frontend framework.

### Web Server
**Uvicorn directly.** Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`. One process. Right-sized for a personal admin panel with one user.

### Admin UI Design
**Apple-derived design system from `DESIGN.md`:**
- Page canvas: `#f5f5f7`
- Card surface: `#ffffff`
- Primary text: `#1d1d1f`
- Secondary text: `#707070`
- CTA button: `#0071e3`
- Border/divider: `#e8e8ed`
- Font: Inter / system-ui
- Card border radius: `28px`
- Button border radius: `999px`
- No box shadows — elevation via colour value only
- Spacing base unit: `4px`

---

## Architecture

### How Config Is Stored
A new file `/data/config.json` holds all UI-editable settings. On startup, the app reads this file and merges with env vars. The scheduler is hot-reloaded in-process when time/timezone changes. Design tokens are parsed from `/data/design.md` at email-build time.

### How the Email Is Restyled
`email_builder.py` is updated to:
1. Load `/data/design.md` (falls back to the bundled default)
2. Parse CSS custom properties block via regex
3. Map tokens to email CSS: `--color-ink` → primary text, `--color-fog` → background, `--color-snow` → card surface, `--color-silver-mist` → borders, Inter/system-ui as font stack
4. Respect section toggles (skip Echo/Revisit/cover rendering if toggled off)
5. Use the custom subject line template

### File Structure
```
DrClawlights/
├── app.py                  # NEW — FastAPI app, starts scheduler on startup
├── config.py               # NEW — load/save /data/config.json, merge with env vars
├── routes/
│   ├── auth.py             # NEW — /login, /logout
│   ├── dashboard.py        # NEW — settings form, upload, send-now
│   └── email_format.py     # NEW — design upload, toggles, subject, preview
├── templates/
│   ├── base.html           # NEW — nav, CSS vars, HTMX script
│   ├── login.html          # NEW
│   ├── dashboard.html      # NEW
│   └── email_format.html   # NEW
├── static/
│   └── style.css           # NEW — Apple design system in CSS
├── main.py                 # UPDATED — scheduler logic extracted, importable
├── email_builder.py        # UPDATED — design token parsing, toggles, subject template
├── digest.py               # unchanged
├── history.py              # unchanged
├── insights.py             # unchanged
├── requirements.txt        # UPDATED — adds fastapi, uvicorn, jinja2, etc.
└── railway.toml            # UPDATED — start command → uvicorn
```

---

## Build Plan

### Phase 1 — Foundation
- Add `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `itsdangerous` to `requirements.txt`
- Create `config.py` — load/save `/data/config.json`, merge with env vars, typed config dataclass
- Refactor `main.py` — extract `run_digest()` and scheduler setup so they can be imported by `app.py`
- Create `app.py` — FastAPI app with lifespan handler that starts the scheduler in a background thread
- Update `railway.toml` start command to `uvicorn app:app --host 0.0.0.0 --port $PORT`

### Phase 2 — Auth
- `routes/auth.py` — `GET /login`, `POST /login`, `POST /logout`
- Signed session cookie via `itsdangerous.TimestampSigner`, validated against `ADMIN_PASSWORD` env var
- Auth dependency injected into all protected routes
- `templates/login.html` — Apple-style: fog canvas, white card, single password field, `#0071e3` submit button

### Phase 3 — Dashboard (Settings + Upload + Send Now)
- `templates/base.html` — sticky nav with "Dr. Clawlights" wordmark, page canvas `#f5f5f7`, HTMX script tag, flash message zone
- `templates/dashboard.html` — two-column layout: settings form left, highlights upload + send now right
- `routes/dashboard.py`:
  - `GET /` — render dashboard with current config
  - `POST /settings` — validate and save settings to `config.json`, hot-reload scheduler if time/tz changed
  - `POST /upload` — replace `/data/highlights.json`, return HTMX success fragment
  - `POST /send-now` — call `run_digest()`, return HTMX success/error fragment

### Phase 4 — Email Format Panel
- `templates/email_format.html` — three card sections: Design File, Section Toggles, Subject Format; iframe preview panel alongside
- `routes/email_format.py`:
  - `GET /email-format` — render panel with current toggles/subject/design filename
  - `POST /email-format/design` — save uploaded `design.md` to `/data/design.md`
  - `POST /email-format/toggles` — save toggle state to `config.json`, return preview fragment
  - `POST /email-format/subject` — save subject template to `config.json`, return subject preview fragment
  - `GET /email-format/preview` — render full email HTML using current highlights + config, returned into iframe
- Update `email_builder.py`:
  - `load_design_tokens(path)` — parse CSS custom properties block from design.md via regex
  - Update `build_html()` to accept tokens dict and toggle flags
  - Update `build_subject()` to accept a format template string

### Phase 5 — Polish & Deploy
- Error/success flash messages (HTMX out-of-band swaps to a toast zone)
- Auth middleware — redirect unauthenticated requests to `/login`
- Copy the project's `DESIGN.md` to `/data/design.md` on first run if not present
- Manual end-to-end test: upload highlights → adjust toggles → check preview → Send Now → verify inbox
- Push to `claude/clawlights-web-frontend-56118q`, open draft PR

---

## Environment Variables (complete list for v2)

| Variable | Where set | Required | Notes |
|---|---|---|---|
| `ADMIN_PASSWORD` | Railway env var | Yes | Protects the admin UI |
| `RESEND_API_KEY` | Railway env var | Yes | Email sending via Resend |
| `ANTHROPIC_API_KEY` | Railway env var | No | Enables Echo section |
| `FROM_EMAIL` | `/data/config.json` | Yes | Editable from UI |
| `RECIPIENT_EMAIL` | `/data/config.json` | Yes | Editable from UI |
| `BOOKS_PER_EMAIL` | `/data/config.json` | No | Default: 2 |
| `HIGHLIGHTS_PER_BOOK` | `/data/config.json` | No | Default: 3 |
| `SEND_HOUR` | `/data/config.json` | No | Default: 6 |
| `SEND_MINUTE` | `/data/config.json` | No | Default: 0 |
| `TIMEZONE` | `/data/config.json` | No | Default: Europe/Berlin |
| `HIGHLIGHTS_FILE` | `/data/config.json` | No | Default: /data/highlights.json |
| `HISTORY_FILE` | `/data/config.json` | No | Default: /data/history.json |

---

## Data Files on Railway Volume (/data)

| File | Purpose |
|---|---|
| `highlights.json` | Kindle highlights — uploaded via UI or volume mount |
| `history.json` | Tracks which highlights have been sent and when |
| `config.json` | All UI-editable settings (created by app on first save) |
| `design.md` | Active design token source for email styling (copied from repo on first run) |
