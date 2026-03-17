# Email Improvements — Design Spec
**Date:** 2026-03-16
**Status:** Approved

---

## Overview

Add 7 email enhancements to Dead-Man-Newsletter: tracking pixel, rich HTML templates, header/footer images, selectable fonts (with per-word rich text editing), unsubscribe functionality, URL shortener integration, and a settings page to configure all of the above. Cap the project with Docker containerization and deployment documentation.

---

## Decisions Summary

| Feature | Decision |
|---|---|
| Tracking pixel | Toggle in settings, HMAC token per recipient, requires `base_url` to be set |
| Rich HTML templates | Improve all 5 existing template bodies in DB |
| Header/footer images | URL paste (user hosts externally), configured in settings |
| Font — global | Default font set in settings, applied to email wrapper |
| Font — per-send | Font picker on compose form, pre-selected to global default |
| Font — per-word | Quill.js rich text editor replaces `<textarea>` fields |
| Unsubscribe | One-click, UUID token per contact, requires `base_url` |
| URL shortener analytics | Link out to provider dashboard (no in-app data pull) |
| URL shortener providers | Bit.ly and TinyURL |
| Architecture | `email_builder.py` + `shortener.py` modules |
| Settings persistence | New `settings` DB table (key-value) for prefs; secrets stay in `.env` |
| Containerization | Dockerfile + docker-compose.yml, final implementation step |
| Deployment docs | `docs/deployment/dns-setup.md` + `docs/deployment/server-hardening.md` |

---

## 1. Data Model

### New table: `settings`

Key-value store for all app-level preferences. Read at send time and on the settings page.

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL DEFAULT ''
);
```

**Default keys seeded on `init_db()`:**

| key | default value | notes |
|---|---|---|
| `base_url` | `''` | Public URL of the app, e.g. `https://newsletter.example.com`. Required for tracking pixel and unsubscribe links to resolve from inside email clients. |
| `header_image_url` | `''` | Empty = no header image |
| `footer_image_url` | `''` | Empty = no footer image |
| `default_font` | `Georgia, serif` | Applied to email wrapper div |
| `tracking_pixel_enabled` | `0` | `1` = enabled. Only effective if `base_url` is set. |
| `url_shortener_enabled` | `0` | `1` = shorten all hrefs at send time |
| `url_shortener_provider` | `bitly` | `bitly` or `tinyurl` |
| `url_shortener_api_key` | `''` | Stored in DB (not `.env`) — not a system secret |
| `url_shortener_bitly_group` | `''` | Bit.ly group GUID (bit.ly only) |

### Modified: `contacts` — add `unsubscribe_token`

```sql
ALTER TABLE contacts ADD COLUMN unsubscribe_token TEXT;
```

UUID generated once per contact at creation time. For existing contacts, generated lazily on first send. Never changes. Used in `/unsubscribe/<token>`.

### Modified: `sends` — add `open_count`

```sql
ALTER TABLE sends ADD COLUMN open_count INTEGER NOT NULL DEFAULT 0;
```

Incremented each time the tracking pixel for that send is loaded by any recipient.

### No other DB changes

Template bodies are updated in-place via a migration helper that re-seeds them only if they match the original default content (i.e. haven't been customised by the user).

---

## 2. Architecture

### New files

| File | Responsibility |
|---|---|
| `email_builder.py` | Composes the full outgoing HTML email from a rendered body + settings + recipient metadata |
| `shortener.py` | Bit.ly and TinyURL API clients; replaces all `href` URLs in HTML at send time |
| `templates/settings.html` | Settings page UI |
| `templates/unsubscribe.html` | One-click unsubscribe confirmation page |
| `Dockerfile` | Container image definition |
| `docker-compose.yml` | Orchestration with volume-mounted SQLite and `.env` passthrough |
| `docs/deployment/dns-setup.md` | DNS A-record setup for Route 53, GoDaddy, Squarespace, Namecheap, Cloudflare |
| `docs/deployment/server-hardening.md` | EC2/VPS hardening guide (see Section 7) |

### Modified files

| File | Changes |
|---|---|
| `database.py` | Add `settings` table, migrate `contacts` and `sends`, add template refresh migration |
| `app.py` | Add `/settings`, `/unsubscribe/<token>`, `/track/<send_id>/<token>.gif` routes; update `template_send()` and `check_deadman_switch()` to use new modules |
| `templates/base.html` | Add Settings nav link |
| `templates/template_detail.html` | Replace `<textarea>` fields with Quill editors; add font picker; add hidden inputs for form submission |

### Updated send flow

```
1. Render Jinja2 body template with user's field values
2. If url_shortener_enabled → shortener.shorten_all_urls(body, settings)
3. For each recipient:
     full_html = email_builder.build_email(
         body, settings,
         unsubscribe_token=contact.unsubscribe_token,
         send_id=send_id,
         recipient_email=contact.email
     )
     mailer.send_email(contact.email, contact.name, subject, full_html)
4. Log to sends table (open_count=0)
```

---

## 3. `email_builder.py`

Single public function:

```python
def build_email(body, settings, unsubscribe_token, send_id, recipient_email) -> str
```

Produces a complete `<!DOCTYPE html>` document. Structure:

1. Outer wrapper `<div>` with `font-family` set to the chosen font
2. Header image `<img>` (if `header_image_url` is set)
3. `body` content injected as-is (HTML from Quill / template)
4. Footer image `<img>` (if `footer_image_url` is set)
5. Unsubscribe footer: `<a href="{base_url}/unsubscribe/{token}">Unsubscribe</a>`
6. Tracking pixel `<img>` (if `tracking_pixel_enabled` and `base_url` set):
   ```
   <img src="{base_url}/track/{send_id}/{token}.gif" width="1" height="1" style="display:none">
   ```

**HMAC token** for tracking pixel:
```python
token = hmac.new(
    app.secret_key.encode(),
    f"{send_id}:{recipient_email}".encode(),
    hashlib.sha256
).hexdigest()[:16]
```

No per-recipient DB row needed — the token is verified on the fly when the pixel loads.

---

## 4. `shortener.py`

```python
def shorten_url(url, provider, api_key, group_guid=None) -> str
```
Returns the shortened URL, or the original URL on any API error (fail open — never break an email send).

```python
def shorten_all_urls(html, settings) -> str
```
Parses all `href="..."` values from the HTML using regex, shortens each unique URL, returns updated HTML. Skips `mailto:`, `#`, and the app's own `/unsubscribe/` links.

**Provider implementations:**
- **Bit.ly:** `POST https://api-ssl.bitly.com/v4/shorten` with `Authorization: Bearer <api_key>`, body `{"long_url": url, "group_guid": group_guid}`
- **TinyURL:** `POST https://api.tinyurl.com/create` with `Authorization: Bearer <api_key>`, body `{"url": url}`

---

## 5. New Routes in `app.py`

### `GET /settings` + `POST /settings`
Reads/writes all keys in the `settings` table. Single form, single submit. Displays a warning banner if `tracking_pixel_enabled=1` but `base_url` is blank or starts with `http://localhost`.

### `GET /unsubscribe/<token>`
1. Look up contact by `unsubscribe_token`
2. Set `unsubscribed = 1`
3. Render `unsubscribe.html` ("You've been unsubscribed")
4. If token not found: render same page with a generic message (no error leak)

### `GET /track/<int:send_id>/<token>.gif`
1. Verify HMAC token against `send_id` using `app.secret_key`
2. If valid: `UPDATE sends SET open_count = open_count + 1 WHERE id = ?`
3. Always return a 1×1 transparent GIF (hardcoded bytes), `Content-Type: image/gif`

---

## 6. Settings Page UI

Three sections on `/settings`:

**Email Appearance**
- Default Font (select: Georgia, Arial, Helvetica, Verdana, Times New Roman, Trebuchet MS, Courier New)
- Header Image URL (text input)
- Footer Image URL (text input)
- Base URL (text input, e.g. `https://newsletter.example.com`) — with explanatory note about tracking and unsubscribe links

**Open Tracking**
- Toggle: Track email opens (tracking pixel)
- Warning banner (shown when enabled + base_url blank/localhost): *"Tracking requires the app to be publicly accessible. Set a Base URL above, or leave this off for local use."*

**URL Shortener**
- Toggle: Auto-shorten links in emails
- Provider select: Bit.ly / TinyURL
- API Key (password input)
- Bit.ly Group GUID (text input, shown only when Bit.ly selected)
- Info note: *"View click analytics at app.bitly.com → Links"*

---

## 7. Rich Text Editor (Quill.js)

**Integration:** CDN `<script>` tag in `template_detail.html`. No npm, no build step.

**Scope:** Every template field of type `"textarea"` gets a Quill editor. Fields of type `"text"` remain plain `<input>` elements.

**Toolbar:** Font family (7 email-safe fonts), font size (small/normal/large/huge), bold, italic, underline, link, ordered/unordered list, text color.

**Form submission:** Each Quill editor has a paired `<input type="hidden">`. A `<script>` block on the form's `submit` event copies `quill.root.innerHTML` into the hidden input before the POST.

**Template variable rendering:** Template `body_template` strings that render textarea variables must use `{{ var | safe }}` (Jinja2 auto-escaping would otherwise escape the Quill HTML output). This is a targeted change to the 5 template bodies — only textarea-sourced variables get `| safe`.

**Font picker (per-send override):** Added below the Quill editors as a standard `<select>`, pre-populated from the global `default_font` setting. Passed as a hidden field and applied by `email_builder.py` to the wrapper `font-family`.

---

## 8. Template Improvements

All 5 existing template bodies (`newsletter`, `job-seeking`, `social-roundup`, `new-videos`, `deadman-switch`) are updated with improved inline CSS:
- Consistent max-width (600px), better padding and spacing
- Clear visual hierarchy (h1/h2 sizes, color accents)
- Mobile-responsive meta viewport already in wrapper
- Button styles for CTA links
- Better table rendering for deadman-switch details

Templates are re-seeded during migration only if their current `body_template` exactly matches the original default — user-customised templates are not overwritten.

---

## 9. Containerization

**`Dockerfile`:**
- Base image: `python:3.12-slim`
- Install dependencies from `requirements.txt`
- Run with `gunicorn` on port 5000
- Non-root user

**`docker-compose.yml`:**
- Mounts `./newsletter.db` as a volume so SQLite data persists across container restarts
- Reads `.env` file for SMTP credentials and `SECRET_KEY`
- Exposes port 5000 (sit behind nginx/Caddy on the host for SSL)

---

## 10. Deployment Documentation

### `docs/deployment/dns-setup.md`
Step-by-step A-record setup for:
- AWS Route 53
- GoDaddy
- Squarespace
- Namecheap
- Cloudflare

Covers: finding your server IP, TTL recommendations, verifying propagation with `dig` / `nslookup`, and pointing the app's `base_url` setting to the domain.

### `docs/deployment/server-hardening.md`
Hardening guide for EC2 / any VPS running the Docker container:

- **Security group / firewall:** Open ports 80 and 443 only. Port 22 (SSH) is not required — use **AWS SSM Session Manager** for shell access with zero open ports.
- **UFW:** Second-layer firewall matching security group rules (`ufw allow 80`, `ufw allow 443`, `ufw default deny incoming`)
- **nginx reverse proxy:** Proxies `localhost:5000` → public 443, handles SSL termination
- **Let's Encrypt (Certbot):** `certbot --nginx -d yourdomain.com`, auto-renewal cron
- **Non-root deploy user:** Create dedicated user, run Docker as that user
- **fail2ban:** Configured for SSH brute-force protection — included as a safety net for environments where port 22 is later opened
- **systemd service:** Keep Docker container alive across reboots

---

## Out of Scope

- In-app display of URL shortener click counts (link out to provider dashboard instead)
- File upload for header/footer images (URL paste only)
- Per-template font defaults (global default + per-send override is sufficient)
- Rich text editing for `text`-type fields (single-line fields stay as plain inputs)
