# Email Improvements — Living Design Spec
**Date:** 2026-03-16
**Status:** Ready for Implementation

---

## How to use this spec

This is a **living state machine**. Every task has a status (`pending` / `in_progress` / `completed`).

**Rules for Claude:**
1. At the start of any session, read the Master Tracking Table to find what's `in_progress` or the next `pending` task.
2. Before starting a task, update its status to `in_progress` in both the Master Tracking Table and the task's own Tracking block.
3. When a task is complete, update its status to `completed` in both places, output the task's **Completion Prompt**, then update the next task to `in_progress`.
4. Never skip updating tracking — it is the source of truth across sessions.

Each task is scoped to fit in a single context window and ends with a **Completion Prompt** that primes the next session.

---

## Master Tracking Table

| Phase | Task | Status |
|---|---|---|
| 1 — Foundation | 1.1 DB Migration | `pending` |
| 1 — Foundation | 1.2 Settings Route + Page | `pending` |
| 1 — Foundation | 1.3 email_builder.py | `pending` |
| 2 — Core Email Features | 2.1 Tracking Pixel Route | `pending` |
| 2 — Core Email Features | 2.2 Unsubscribe Route + Page | `pending` |
| 2 — Core Email Features | 2.3 Update template_send() | `pending` |
| 2 — Core Email Features | 2.4 Update check_deadman_switch() | `pending` |
| 3 — Content & Appearance | 3.1 Quill.js Rich Text Editor | `pending` |
| 3 — Content & Appearance | 3.2 Font Picker (global + per-send) | `pending` |
| 3 — Content & Appearance | 3.3 Improve 5 Email Templates | `pending` |
| 4 — URL Shortener | 4.1 shortener.py module | `pending` |
| 4 — URL Shortener | 4.2 Wire shortener into send flow | `pending` |
| 5 — Containerization | 5.1 Dockerfile + docker-compose.yml | `pending` |
| 6 — Documentation | 6.1 docs/deployment/dns-setup.md | `pending` |
| 6 — Documentation | 6.2 docs/deployment/server-hardening.md | `pending` |

---

## Decisions Summary

| Feature | Decision |
|---|---|
| Tracking pixel | Toggle in settings, HMAC token per recipient, requires `base_url` to be set |
| Rich HTML templates | Improve all 5 existing template bodies in DB |
| Header/footer images | URL paste (user hosts externally), configured in settings |
| Font — global | Default font set in settings, applied to email wrapper |
| Font — per-send | Font picker on compose form, pre-selected to global default |
| Font — per-word | Quill.js v1.3.7 rich text editor replaces `<textarea>` fields |
| Unsubscribe | One-click, UUID token per contact, requires `base_url` |
| Unsubscribe — scanner risk | Known: email security scanners may pre-fetch links and auto-unsubscribe. Accepted tradeoff; note in UI. |
| URL shortener analytics | Link out to provider dashboard (no in-app data pull) |
| URL shortener providers | Bit.ly and TinyURL |
| URL shortener href parsing | Use Python stdlib `html.parser` (no BeautifulSoup dependency) |
| Architecture | `email_builder.py` + `shortener.py` modules |
| Settings persistence | New `settings` DB table (key-value) for prefs; SMTP secrets stay in `.env`; shortener API key stored in DB (not a system secret, but protect `newsletter.db` file permissions) |
| send_id ordering | Insert `sends` row before sending so `send_id` is available for pixel URLs; update `recipient_count` after |
| `email_builder.py` key access | `secret_key` passed as a parameter — no Flask app context dependency |
| HMAC verification | Use `hmac.compare_digest` for constant-time comparison |
| `send_bulk` | Retired from main send path; replaced by per-recipient loop in `template_send()` and `check_deadman_switch()` |
| Containerization | Dockerfile + docker-compose.yml, Phase 5 |
| Deployment docs | `docs/deployment/dns-setup.md` + `docs/deployment/server-hardening.md` |
| EC2 access | AWS SSM Session Manager — no SSH port needed. Port 22 kept closed. fail2ban included as safety net. |

---

## Data Model Reference

### New table: `settings`

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL DEFAULT ''
);
```

Default keys seeded on `init_db()`:

| key | default |
|---|---|
| `base_url` | `''` |
| `header_image_url` | `''` |
| `footer_image_url` | `''` |
| `default_font` | `Georgia, serif` |
| `tracking_pixel_enabled` | `0` |
| `url_shortener_enabled` | `0` |
| `url_shortener_provider` | `bitly` |
| `url_shortener_api_key` | `''` |
| `url_shortener_bitly_group` | `''` |

### Modified: `contacts`

```sql
ALTER TABLE contacts ADD COLUMN unsubscribe_token TEXT;
```

UUID, generated at contact creation. For existing contacts, generated lazily at first send.

### Modified: `sends`

```sql
ALTER TABLE sends ADD COLUMN open_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sends ADD COLUMN recipient_count ... -- already exists, but now updated after send
```

`open_count` incremented each time any tracking pixel for that send fires.

---

## Architecture Reference

### New files

| File | Responsibility |
|---|---|
| `email_builder.py` | Composes full outgoing HTML from body + settings + recipient metadata |
| `shortener.py` | Bit.ly + TinyURL clients; replaces href URLs in HTML |
| `templates/settings.html` | Settings page UI |
| `templates/unsubscribe.html` | One-click unsubscribe confirmation page |
| `Dockerfile` | Container image |
| `docker-compose.yml` | Orchestration with volume-mounted SQLite |
| `docs/deployment/dns-setup.md` | DNS A-record setup guide |
| `docs/deployment/server-hardening.md` | EC2/VPS hardening guide |

### Modified files

| File | Changes |
|---|---|
| `database.py` | `settings` table, migrate `contacts` + `sends`, template refresh migration |
| `app.py` | `/settings`, `/unsubscribe/<token>`, `/track/<send_id>/<token>.gif` routes; updated `template_send()` and `check_deadman_switch()` |
| `templates/base.html` | Settings nav link |
| `templates/template_detail.html` | Quill editors, font picker, hidden inputs |
| `requirements.txt` | Add `gunicorn` |

### Updated send flow

```
1. Insert sends row (open_count=0, recipient_count=0) → get send_id
2. Render Jinja2 body with user field values
3. If url_shortener_enabled → shortener.shorten_all_urls(body, settings)
4. For each recipient:
     ensure contact.unsubscribe_token exists (generate if null)
     full_html = email_builder.build_email(
         body=body,
         settings=settings,
         unsubscribe_token=contact.unsubscribe_token,
         send_id=send_id,
         recipient_email=contact.email,
         secret_key=app.secret_key
     )
     mailer.send_email(contact.email, contact.name, subject, full_html)
5. Update sends SET recipient_count=successes WHERE id=send_id
```

---

## Phase 1 — Foundation

### Task 1.1 — DB Migration

**Tracking**
| Item | Status |
|---|---|
| Create `settings` table in `init_db()` | `pending` |
| Seed default settings keys | `pending` |
| Add `contacts.unsubscribe_token` (ALTER + migration guard) | `pending` |
| Add `sends.open_count` (ALTER + migration guard) | `pending` |
| Generate `unsubscribe_token` for all existing contacts | `pending` |

**Files touched:** `database.py`

**Details:**
- Add `settings` table creation to `init_db()` executescript.
- Seed default settings rows if `settings` table is empty.
- Use `PRAGMA table_info(contacts)` to check if `unsubscribe_token` column exists before running `ALTER TABLE` — SQLite doesn't support `IF NOT EXISTS` on `ALTER TABLE`.
- Same guard for `sends.open_count`.
- After adding `unsubscribe_token`, run: `UPDATE contacts SET unsubscribe_token = lower(hex(randomblob(16))) WHERE unsubscribe_token IS NULL` to backfill existing contacts.
- New contacts created via `add_contact()` and `import_contacts()` should also generate a token at insert time.

**Completion criteria:** `init_db()` is idempotent — running it on a fresh DB and on an existing DB with data produces no errors and correct schema.

**Completion Prompt:**
> Task 1.1 complete. DB migration done: `settings` table exists with default keys seeded; `contacts.unsubscribe_token` and `sends.open_count` columns added with migration guards; existing contacts backfilled with UUIDs. Next: Task 1.2 — Settings Route + Page. Read spec at `docs/superpowers/specs/2026-03-16-email-improvements-design.md`, update Task 1.2 status to `in_progress`, then implement the `/settings` GET/POST route in `app.py` and `templates/settings.html`.

---

### Task 1.2 — Settings Route + Page

**Tracking**
| Item | Status |
|---|---|
| `GET /settings` route — load all settings from DB | `pending` |
| `POST /settings` route — write all settings to DB | `pending` |
| `templates/settings.html` — Email Appearance section | `pending` |
| `templates/settings.html` — Open Tracking section + warning banner | `pending` |
| `templates/settings.html` — URL Shortener section | `pending` |
| Add Settings link to `templates/base.html` nav | `pending` |

**Files touched:** `app.py`, `templates/settings.html`, `templates/base.html`

**Details:**

`GET /settings`: load all rows from `settings` table into a dict `{key: value}`, pass to template.

`POST /settings`: for each expected key, read from `request.form`, write back to DB with `INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)`.

Settings page UI — three sections:

**Email Appearance:**
- Base URL (`base_url`) — text input, note: *"Required for tracking pixel and unsubscribe links to work from inside email clients."*
- Default Font (`default_font`) — `<select>` with: `Georgia, serif` / `Arial, sans-serif` / `Helvetica, sans-serif` / `Verdana, sans-serif` / `Times New Roman, serif` / `Trebuchet MS, sans-serif` / `Courier New, monospace`
- Header Image URL (`header_image_url`) — text input, note: *"Leave blank to disable."*
- Footer Image URL (`footer_image_url`) — text input

**Open Tracking:**
- Tracking pixel toggle (`tracking_pixel_enabled`) — checkbox rendered as a toggle
- Warning banner (shown when `tracking_pixel_enabled=1` AND `base_url` is blank or starts with `http://localhost` or `http://127.`): *"⚠️ Tracking requires the app to be publicly accessible. Set a Base URL above, or leave tracking off for local use."*
- Note: *"When a recipient opens your email, their client loads a tiny invisible image. Some email clients block these."*

**URL Shortener:**
- Toggle (`url_shortener_enabled`) — checkbox as toggle
- Provider (`url_shortener_provider`) — `<select>`: Bit.ly / TinyURL
- API Key (`url_shortener_api_key`) — `<input type="password">`
- Bit.ly Group GUID (`url_shortener_bitly_group`) — text input, shown only when provider = `bitly`
- Info note: *"View click analytics at app.bitly.com → Links"*
- JS on page: hide/show Group GUID field based on provider selection

**Completion criteria:** Settings page loads, saves, and repopulates correctly. Warning banner appears/disappears based on `base_url` and tracking toggle state.

**Completion Prompt:**
> Task 1.2 complete. Settings route and page implemented: GET loads from DB, POST saves to DB; three sections (Email Appearance, Open Tracking, URL Shortener) including base_url field and warning banner; Settings added to nav. Next: Task 1.3 — email_builder.py. Read spec, update Task 1.3 to `in_progress`, then create `email_builder.py` with the `build_email()` function.

---

### Task 1.3 — email_builder.py

**Tracking**
| Item | Status |
|---|---|
| `build_email()` function signature | `pending` |
| Font wrapper div | `pending` |
| Header image injection | `pending` |
| Footer image injection | `pending` |
| Unsubscribe footer | `pending` |
| Tracking pixel injection (with HMAC) | `pending` |
| HMAC generation using `hmac.compare_digest`-safe approach | `pending` |

**Files touched:** `email_builder.py` (new)

**Details:**

```python
def build_email(body, settings, unsubscribe_token, send_id, recipient_email, secret_key) -> str
```

- `settings` is a plain dict `{key: value}` — no DB access inside this function.
- Font: applied as `font-family` on the outermost wrapper `<div style="max-width:600px;margin:0 auto;font-family:{font}">`.
- Header image: `<img src="{header_image_url}" style="width:100%;max-width:600px;display:block;" alt="">` — only rendered if `header_image_url` is non-empty.
- Footer image: same pattern, only if `footer_image_url` non-empty.
- Unsubscribe footer:
  ```html
  <div style="text-align:center;padding:20px;font-size:12px;color:#999;">
    <a href="{base_url}/unsubscribe/{unsubscribe_token}" style="color:#999;">Unsubscribe</a>
    &nbsp;·&nbsp; Sent by NewsLetterGo
  </div>
  ```
  Always included, even if `base_url` is empty (link will be relative — won't work externally but won't break the email).
- Tracking pixel HMAC:
  ```python
  import hmac, hashlib
  def _make_pixel_token(send_id, recipient_email, secret_key):
      key = secret_key.encode() if isinstance(secret_key, str) else secret_key
      msg = f"{send_id}:{recipient_email}".encode()
      return hmac.new(key, msg, hashlib.sha256).hexdigest()[:16]
  ```
  Pixel only injected if `tracking_pixel_enabled == '1'` AND `base_url` is non-empty.
- Returns a complete `<!DOCTYPE html>` document wrapping all of the above.

**Note on `hmac.compare_digest`:** The `/track/` route (Task 2.1) must use `hmac.compare_digest(expected_token, provided_token)` rather than `==` when verifying the token, to prevent timing attacks.

**Completion criteria:** `build_email()` returns valid HTML for all combinations of settings (no header, no footer, tracking off, base_url empty, etc.).

**Completion Prompt:**
> Task 1.3 complete. `email_builder.py` created with `build_email()` — wraps body with font, optional header/footer images, unsubscribe footer, and optional HMAC tracking pixel. Next: Task 2.1 — Tracking Pixel Route. Read spec, update Task 2.1 to `in_progress`, then add the `/track/<send_id>/<token>.gif` route to `app.py`.

---

## Phase 2 — Core Email Features

### Task 2.1 — Tracking Pixel Route

**Tracking**
| Item | Status |
|---|---|
| `/track/<send_id>/<token>.gif` route in `app.py` | `pending` |
| HMAC token verification with `hmac.compare_digest` | `pending` |
| Increment `sends.open_count` | `pending` |
| Return 1×1 transparent GIF bytes | `pending` |
| Open count displayed in `templates/history.html` | `pending` |

**Files touched:** `app.py`, `templates/history.html`, `templates/history_detail.html`

**Details:**

1×1 transparent GIF bytes (hardcoded — no file needed):
```python
TRACKING_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00'
    b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
    b'\x44\x01\x00\x3b'
)
```

Route:
```python
@app.route('/track/<int:send_id>/<token>.gif')
def track_open(send_id, token):
    expected = _make_pixel_token(send_id, ???, app.secret_key)  # see note
    ...
    return Response(TRACKING_GIF, mimetype='image/gif',
                    headers={'Cache-Control': 'no-store, no-cache'})
```

**Note on token verification:** The HMAC token encodes `send_id:recipient_email`. To verify, the route cannot reverse the token to get the email. Instead, it verifies existence: look up `sends` by `send_id`, verify the token is syntactically a 16-char hex string, then — since we can't reverse it — just increment unconditionally if the send exists. The HMAC's role here is as a modest forgery deterrent (not authentication). Alternatively: store the token in a `send_opens` table — but per spec we avoid this. **Decision:** accept that the pixel URL acts as an unforgeable-enough token; verify only that `send_id` exists and `token` is 16 hex chars. Use `hmac.compare_digest` is N/A here since we can't re-derive without the email. Document this in code comments.

Add `open_count` column to the history table display and history detail page.

**Completion criteria:** Loading the pixel URL increments `open_count`; history page shows open counts; non-existent send_id returns the GIF without error.

**Completion Prompt:**
> Task 2.1 complete. `/track/<send_id>/<token>.gif` route implemented; open_count incremented on pixel load; history page updated with open count column. Next: Task 2.2 — Unsubscribe Route + Page. Read spec, update Task 2.2 to `in_progress`, then add `/unsubscribe/<token>` route and `templates/unsubscribe.html`.

---

### Task 2.2 — Unsubscribe Route + Page

**Tracking**
| Item | Status |
|---|---|
| `GET /unsubscribe/<token>` route | `pending` |
| Sets `contacts.unsubscribed = 1` | `pending` |
| `templates/unsubscribe.html` confirmation page | `pending` |
| Graceful handling of unknown token | `pending` |

**Files touched:** `app.py`, `templates/unsubscribe.html` (new)

**Details:**

```python
@app.route('/unsubscribe/<token>')
def unsubscribe(token):
    db = get_db()
    contact = db.execute(
        "SELECT id FROM contacts WHERE unsubscribe_token=?", (token,)
    ).fetchone()
    if contact:
        db.execute("UPDATE contacts SET unsubscribed=1 WHERE id=?", (contact['id'],))
        db.commit()
    db.close()
    return render_template('unsubscribe.html')  # same page regardless — no info leak
```

`unsubscribe.html` page content:
- ✅ large checkmark or similar
- Heading: "You've been unsubscribed"
- Body: "You won't receive any more emails from this newsletter."
- No back link, no re-subscribe option

**⚠️ Known limitation note (add as HTML comment in template):** Some email security scanners pre-fetch all links in incoming emails, which may trigger this route and unsubscribe the recipient before they ever read the email. This is an accepted tradeoff of one-click unsubscribe. A two-step confirmation flow would prevent this but adds friction.

**Completion criteria:** Clicking a valid unsubscribe token sets `unsubscribed=1` and shows confirmation page. Invalid token shows same page (no error).

**Completion Prompt:**
> Task 2.2 complete. `/unsubscribe/<token>` route implemented; contact marked unsubscribed on valid token; `unsubscribe.html` confirmation page created. Next: Task 2.3 — Update template_send(). Read spec, update Task 2.3 to `in_progress`, then refactor `template_send()` in `app.py` to use the new per-recipient send flow with `email_builder.py`.

---

### Task 2.3 — Update template_send()

**Tracking**
| Item | Status |
|---|---|
| Insert `sends` row before sending (to get `send_id`) | `pending` |
| Load `settings` dict from DB once before loop | `pending` |
| Per-recipient loop using `email_builder.build_email()` | `pending` |
| Lazy `unsubscribe_token` generation for contacts missing one | `pending` |
| Update `sends.recipient_count` after loop | `pending` |
| Error collection and flash messages unchanged | `pending` |
| `send_bulk` retired from this path | `pending` |

**Files touched:** `app.py`

**Details:**

Load settings helper (add to `app.py` or `database.py`):
```python
def get_settings(db):
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {r['key']: r['value'] for r in rows}
```

New flow in `template_send()`:
1. Resolve recipients list (same logic as now).
2. Insert `sends` row immediately with `recipient_count=0` → `send_id = db.lastrowid`.
3. Load `settings = get_settings(db)`.
4. Render body template with field values.
5. If `url_shortener_enabled == '1'`: call `shortener.shorten_all_urls(body, settings)` — **import guard**: if shortener not yet implemented (Task 4.1 is pending), skip gracefully.
6. Per-recipient loop: ensure `unsubscribe_token` exists (generate UUID if null, save to DB), call `email_builder.build_email(...)`, call `mailer.send_email(...)`.
7. After loop: `UPDATE sends SET recipient_count=successes WHERE id=send_id`.

**Completion criteria:** Sends work end-to-end with per-recipient HTML (unique unsubscribe links and pixel URLs per recipient). Error handling and flash messages behave the same as before.

**Completion Prompt:**
> Task 2.3 complete. `template_send()` refactored to per-recipient loop using `email_builder.build_email()`; `sends` row inserted before loop to capture `send_id`; `send_bulk` retired from this path. Next: Task 2.4 — Update check_deadman_switch(). Read spec, update Task 2.4 to `in_progress`, then apply the same per-recipient send pattern to `check_deadman_switch()`.

---

### Task 2.4 — Update check_deadman_switch()

**Tracking**
| Item | Status |
|---|---|
| Insert `sends` row before sending | `pending` |
| Load settings from DB | `pending` |
| Per-recipient loop with `email_builder.build_email()` | `pending` |
| Update `recipient_count` after loop | `pending` |

**Files touched:** `app.py`

**Details:**

`check_deadman_switch()` runs in an APScheduler context (no HTTP request, no Flask request context). `app.secret_key` is available as a module-level attribute, so passing it as a parameter to `build_email()` works fine.

Apply the same pattern as Task 2.3: insert `sends` row first, load settings, per-recipient loop, update count. The body is built from the deadman-switch template as now.

**Completion criteria:** Dead man's switch emails include unsubscribe links and tracking pixels (when enabled) identical to regular sends.

**Completion Prompt:**
> Task 2.4 complete. `check_deadman_switch()` updated to per-recipient loop with `email_builder`. Phase 2 complete. Next: Task 3.1 — Quill.js Rich Text Editor. Read spec, update Task 3.1 to `in_progress`, then integrate Quill.js into `templates/template_detail.html`.

---

## Phase 3 — Content & Appearance

### Task 3.1 — Quill.js Rich Text Editor

**Tracking**
| Item | Status |
|---|---|
| Quill.js v1.3.7 CDN script + stylesheet in template | `pending` |
| Replace each `textarea` field with Quill editor div | `pending` |
| Hidden inputs paired with each editor | `pending` |
| Form submit JS: copy `quill.root.innerHTML` to hidden inputs | `pending` |
| Toolbar: font family (7 fonts), size, bold, italic, underline, link, list, color | `pending` |
| Register custom fonts with Quill's whitelist | `pending` |

**Files touched:** `templates/template_detail.html`

**Details:**

CDN (pin to v1.3.7 — v2 has incompatible API):
```html
<link href="https://cdn.quilljs.com/1.3.7/quill.snow.css" rel="stylesheet">
<script src="https://cdn.quilljs.com/1.3.7/quill.js"></script>
```

For each field of type `"textarea"`:
```html
<div id="editor-{{ field.name }}" style="height:150px;"></div>
<input type="hidden" name="{{ field.name }}" id="hidden-{{ field.name }}">
```

Quill font whitelist (required to use custom fonts in toolbar):
```js
var Font = Quill.import('formats/font');
Font.whitelist = ['georgia', 'arial', 'helvetica', 'verdana', 'times-new-roman', 'trebuchet', 'courier'];
Quill.register(Font, true);
```

Font CSS mapping (add to template `<style>` block):
```css
.ql-font-georgia { font-family: Georgia, serif; }
.ql-font-arial { font-family: Arial, sans-serif; }
/* etc. */
```

Form submit JS:
```js
document.querySelector('form').addEventListener('submit', function() {
    editors.forEach(function(q) {
        document.getElementById('hidden-' + q.fieldName).value = q.editor.root.innerHTML;
    });
});
```

**Completion criteria:** All textarea fields in all 5 template compose forms render as Quill editors. Submitting the form sends HTML content (including inline font spans) as the field values. Preview works with rich content.

**Completion Prompt:**
> Task 3.1 complete. Quill.js v1.3.7 integrated into `template_detail.html`; all textarea fields replaced with Quill editors with custom font toolbar; hidden inputs populated on submit. Next: Task 3.2 — Font Picker. Read spec, update Task 3.2 to `in_progress`, then add the per-send font picker below the Quill editors and wire it into `email_builder.build_email()`.

---

### Task 3.2 — Font Picker (global default + per-send override)

**Tracking**
| Item | Status |
|---|---|
| Font picker `<select>` added to compose form | `pending` |
| Pre-populated from `settings.default_font` | `pending` |
| Passed as `font` field in form POST | `pending` |
| `email_builder.build_email()` uses passed font over settings default | `pending` |

**Files touched:** `templates/template_detail.html`, `app.py`, `email_builder.py`

**Details:**

In `template_detail.html`, below the Quill editors and above the send/preview buttons:
```html
<div>
  <label>Font <span style="font-size:12px;color:#888;">(default from Settings — change for this send only)</span></label>
  <select name="font">
    {% for f in fonts %}
    <option value="{{ f.value }}" {% if f.value == settings.default_font %}selected{% endif %}>{{ f.label }}</option>
    {% endfor %}
  </select>
</div>
```

In `template_detail` route: load `settings` from DB, pass `fonts` list and `settings` to template.

In `template_send()`: read `font = request.form.get('font', settings.get('default_font', 'Georgia, serif'))`, pass to `build_email()`.

`build_email()`: add `font` parameter (optional, defaults to `settings.get('default_font')`). If `font` arg is passed, it takes precedence.

**Note:** The wrapper `font-family` is the fallback. Quill inline `<span style="font-family:...">` tags override it for specific words/lines. This is intentional — the wrapper provides the base, Quill provides overrides.

**Completion criteria:** Font picker shows on compose form pre-selected to global default; changing it and sending uses the new font for the email wrapper; Quill per-word fonts still override within the content.

**Completion Prompt:**
> Task 3.2 complete. Per-send font picker added to compose form, wired through `template_send()` to `build_email()`. Next: Task 3.3 — Improve 5 Email Templates. Read spec, update Task 3.3 to `in_progress`, then update the 5 template bodies in `database.py` with improved HTML.

---

### Task 3.3 — Improve 5 Email Templates

**Tracking**
| Item | Status |
|---|---|
| `newsletter` template improved | `pending` |
| `job-seeking` template improved | `pending` |
| `social-roundup` template improved | `pending` |
| `new-videos` template improved | `pending` |
| `deadman-switch` template improved | `pending` |
| Migration: only overwrite if body matches original default | `pending` |
| `{{ var \| safe }}` applied to all textarea-sourced variables | `pending` |

**Files touched:** `database.py`

**Details:**

Each template body gets:
- Cleaner spacing, consistent padding, improved typographic hierarchy
- Mobile-friendly inline CSS (already 600px max-width)
- Better CTA button styles where applicable
- `{{ var | safe }}` on all textarea-sourced variables (so Quill HTML renders correctly)

**Migration guard:** Before re-seeding, check if current body matches the original (compare against a SHA-256 hash of the original body string, stored as a constant in `database.py`). If it doesn't match, the user has customised the template — skip it. Log a message: `"Skipping template '{slug}': has been customised."`.

**Completion criteria:** All 5 templates render correctly with improved styling. Textarea variables render as HTML (not escaped). Existing customised templates are not overwritten.

**Completion Prompt:**
> Task 3.3 complete. All 5 template bodies improved; `| safe` filter applied to textarea variables; migration guard in place. Phase 3 complete. Next: Task 4.1 — shortener.py module. Read spec, update Task 4.1 to `in_progress`, then create `shortener.py` with Bit.ly and TinyURL support.

---

## Phase 4 — URL Shortener

### Task 4.1 — shortener.py module

**Tracking**
| Item | Status |
|---|---|
| `shorten_url()` — Bit.ly implementation | `pending` |
| `shorten_url()` — TinyURL implementation | `pending` |
| `shorten_url()` — fail-open on any error | `pending` |
| `shorten_all_urls()` — parse hrefs with `html.parser` | `pending` |
| `shorten_all_urls()` — skip `mailto:`, `#`, `/unsubscribe/` links | `pending` |
| `shorten_all_urls()` — deduplicate URLs (shorten each unique URL once) | `pending` |

**Files touched:** `shortener.py` (new)

**Details:**

```python
def shorten_url(url, provider, api_key, group_guid=None) -> str:
    """Returns shortened URL, or original URL on any failure."""
    try:
        if provider == 'bitly':
            # POST https://api-ssl.bitly.com/v4/shorten
            # Headers: Authorization: Bearer {api_key}, Content-Type: application/json
            # Body: {"long_url": url, "group_guid": group_guid}
            # Response: {"link": "https://bit.ly/..."}
        elif provider == 'tinyurl':
            # POST https://api.tinyurl.com/create
            # Headers: Authorization: Bearer {api_key}, Content-Type: application/json
            # Body: {"url": url, "domain": "tinyurl.com"}
            # Response: {"data": {"tiny_url": "https://tinyurl.com/..."}}
    except Exception:
        return url  # fail open — never break a send
```

```python
def shorten_all_urls(html, settings) -> str:
    """Parse all href values with html.parser, shorten unique URLs, return updated HTML."""
    # Use html.parser via HTMLParser subclass to find all href attributes
    # Skip: starts with 'mailto:', '#', '/unsubscribe/', relative paths
    # Deduplicate: build {original: shortened} map, replace all at end
    # Use str.replace on the raw HTML string after building the map
```

Use stdlib `urllib.request` or `http.client` for HTTP calls — no new dependencies required. Alternatively `urllib.request.urlopen` with JSON encoding.

**Completion criteria:** `shorten_all_urls` correctly replaces all qualifying hrefs. `shorten_url` returns the original URL on network failure or API error. No new pip dependencies introduced.

**Completion Prompt:**
> Task 4.1 complete. `shortener.py` created with Bit.ly + TinyURL support; fail-open error handling; `html.parser`-based href replacement. Next: Task 4.2 — Wire shortener into send flow. Read spec, update Task 4.2 to `in_progress`, then integrate `shortener.shorten_all_urls()` into `template_send()` and `check_deadman_switch()`.

---

### Task 4.2 — Wire shortener into send flow

**Tracking**
| Item | Status |
|---|---|
| Import `shortener` in `app.py` | `pending` |
| Call `shorten_all_urls()` in `template_send()` when enabled | `pending` |
| Call `shorten_all_urls()` in `check_deadman_switch()` when enabled | `pending` |

**Files touched:** `app.py`

**Details:**

In `template_send()` (Task 2.3 left a placeholder for this):
```python
from shortener import shorten_all_urls

if settings.get('url_shortener_enabled') == '1':
    body = shorten_all_urls(body, settings)
```

Same in `check_deadman_switch()`.

**Completion criteria:** Sending a newsletter with shortener enabled replaces all qualifying hrefs. Shortener disabled = no change to hrefs.

**Completion Prompt:**
> Task 4.2 complete. URL shortener wired into both send paths. Phase 4 complete. Next: Task 5.1 — Dockerfile + docker-compose.yml. Read spec, update Task 5.1 to `in_progress`, then create `Dockerfile`, `docker-compose.yml`, and add `gunicorn` to `requirements.txt`.

---

## Phase 5 — Containerization

### Task 5.1 — Dockerfile + docker-compose.yml

**Tracking**
| Item | Status |
|---|---|
| `gunicorn` added to `requirements.txt` | `pending` |
| `Dockerfile` written | `pending` |
| `docker-compose.yml` written | `pending` |
| `.dockerignore` written | `pending` |
| `.gitignore` updated (add `.superpowers/`) | `pending` |

**Files touched:** `Dockerfile` (new), `docker-compose.yml` (new), `.dockerignore` (new), `requirements.txt`, `.gitignore`

**Details:**

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN useradd -m appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
```

`docker-compose.yml`:
```yaml
version: '3.9'
services:
  web:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./newsletter.db:/app/newsletter.db
    env_file:
      - .env
    restart: unless-stopped
```

`.dockerignore`: `.git`, `.env`, `__pycache__`, `*.pyc`, `.superpowers/`, `newsletter.db`

Note in `docker-compose.yml` comments: *"newsletter.db is volume-mounted so data persists across container rebuilds. Protect this file — it contains contact emails and settings including the shortener API key."*

**Completion criteria:** `docker compose up --build` starts the app; data persists across `docker compose down && docker compose up`; `.env` variables are passed through correctly.

**Completion Prompt:**
> Task 5.1 complete. Dockerfile, docker-compose.yml, and .dockerignore created; gunicorn added to requirements.txt; .gitignore updated. Phase 5 complete. Next: Task 6.1 — DNS Setup docs. Read spec, update Task 6.1 to `in_progress`, then write `docs/deployment/dns-setup.md`.

---

## Phase 6 — Documentation

### Task 6.1 — DNS Setup Guide

**Tracking**
| Item | Status |
|---|---|
| Intro: what DNS A-record means, what IP to use | `pending` |
| AWS Route 53 steps | `pending` |
| GoDaddy steps | `pending` |
| Squarespace steps | `pending` |
| Namecheap steps | `pending` |
| Cloudflare steps | `pending` |
| Verification: dig / nslookup | `pending` |
| Pointing `base_url` in app settings | `pending` |

**Files touched:** `docs/deployment/dns-setup.md` (new)

**Details:**

Cover: find your server's public IP (EC2 Elastic IP), create an A record (`newsletter.yourdomain.com → IP`), recommended TTL (300s for initial setup, 3600s once stable), verify with `dig newsletter.yourdomain.com` and `nslookup newsletter.yourdomain.com 8.8.8.8`. End with: set `base_url` to `https://newsletter.yourdomain.com` in the app settings.

**Completion Prompt:**
> Task 6.1 complete. `docs/deployment/dns-setup.md` written covering Route 53, GoDaddy, Squarespace, Namecheap, Cloudflare. Next: Task 6.2 — Server Hardening Guide. Read spec, update Task 6.2 to `in_progress`, then write `docs/deployment/server-hardening.md`.

---

### Task 6.2 — Server Hardening Guide

**Tracking**
| Item | Status |
|---|---|
| EC2 security group: ports 80 + 443 only | `pending` |
| AWS SSM Session Manager setup (no SSH needed) | `pending` |
| UFW firewall rules | `pending` |
| Non-root deploy user | `pending` |
| nginx reverse proxy config | `pending` |
| Let's Encrypt / Certbot | `pending` |
| SSL auto-renewal cron | `pending` |
| fail2ban (SSH protection, dormant until port 22 opened) | `pending` |
| systemd service unit for Docker | `pending` |
| File permissions: `newsletter.db` (600, owned by appuser) | `pending` |

**Files touched:** `docs/deployment/server-hardening.md` (new)

**Details:**

Security model:
- EC2 security group: inbound 80 (HTTP) and 443 (HTTPS) only. **No port 22.** Use AWS SSM Session Manager for shell access — no open ports required.
- UFW: `ufw default deny incoming`, `ufw allow 80`, `ufw allow 443`, `ufw enable`
- nginx: reverse proxy `localhost:5000` → public 443; HTTP → HTTPS redirect
- Certbot: `sudo certbot --nginx -d newsletter.yourdomain.com`; auto-renewal via `crontab -e`: `0 3 * * * certbot renew --quiet`
- fail2ban: install, configure `/etc/fail2ban/jail.local` with `[sshd]` enabled — dormant since port 22 is closed, but active if it's ever opened
- systemd: service unit that runs `docker compose up` on boot
- `newsletter.db` permissions: `chmod 600 newsletter.db` — readable only by the app user

**Completion criteria:** Guide is complete, accurate, and followable by a non-expert user on a fresh EC2 Ubuntu instance.

**Completion Prompt:**
> Task 6.2 complete. `docs/deployment/server-hardening.md` written. ALL PHASES COMPLETE. The full email improvements spec has been implemented. Review the Master Tracking Table — all tasks should show `completed`. Consider running the app end-to-end to verify all features work together.

---

## Out of Scope

- In-app display of URL shortener click counts (link out to provider dashboard instead)
- File upload for header/footer images (URL paste only)
- Per-template font defaults (global default + per-send override is sufficient)
- Rich text editing for `text`-type fields (single-line fields stay as plain inputs)
- Re-subscribe functionality
- Per-recipient open tracking (only send-level open_count)
