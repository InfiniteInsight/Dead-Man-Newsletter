import os
import json
import re
import secrets
import smtplib
import socket
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from dotenv import load_dotenv, set_key

load_dotenv()

from database import get_db, init_db, get_settings
from mailer import send_email, send_bulk
import email_builder

ENV_PATH = Path(__file__).parent / '.env'

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-me')
app.jinja_env.filters['fromjson'] = json.loads

# 1x1 transparent GIF
TRACKING_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00'
    b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
    b'\x44\x01\x00\x3b'
)

# --- Initialize DB on startup (skipped during testing; conftest.py handles this) ---
if not os.environ.get('TESTING'):
    with app.app_context():
        init_db()


# ============================================================
# SETUP WIZARD
# ============================================================

def is_smtp_configured():
    """Check if SMTP credentials are present and non-empty."""
    return bool(os.environ.get('SMTP_USER')) and bool(os.environ.get('SMTP_PASSWORD'))


@app.route('/')
def index():
    if not is_smtp_configured():
        return redirect(url_for('setup', step='welcome'))
    return redirect(url_for('dashboard'))


@app.route('/setup')
@app.route('/setup/<step>')
def setup(step='welcome'):
    return render_template('setup.html', step=step, env=os.environ)


@app.route('/setup/save-provider', methods=['POST'])
def setup_save_provider():
    """Step 2 result: save the chosen provider's SMTP settings to .env."""
    provider = request.form.get('provider', '')

    presets = {
        'gmail': {'SMTP_HOST': 'smtp.gmail.com', 'SMTP_PORT': '587'},
        'outlook': {'SMTP_HOST': 'smtp-mail.outlook.com', 'SMTP_PORT': '587'},
        'yahoo': {'SMTP_HOST': 'smtp.mail.yahoo.com', 'SMTP_PORT': '587'},
        'zoho': {'SMTP_HOST': 'smtp.zoho.com', 'SMTP_PORT': '587'},
        'protonmail': {'SMTP_HOST': '127.0.0.1', 'SMTP_PORT': '1025'},
        'tuta': {'SMTP_HOST': 'mail.tutanota.com', 'SMTP_PORT': '587'},
        'brevo': {'SMTP_HOST': 'smtp-relay.brevo.com', 'SMTP_PORT': '587'},
        'mailgun': {'SMTP_HOST': 'smtp.mailgun.org', 'SMTP_PORT': '587'},
        'custom': {
            'SMTP_HOST': request.form.get('custom_host', ''),
            'SMTP_PORT': request.form.get('custom_port', '587'),
        },
    }

    settings = presets.get(provider, presets['gmail'])

    # Ensure .env file exists
    if not ENV_PATH.exists():
        ENV_PATH.write_text('')

    for key, val in settings.items():
        set_key(str(ENV_PATH), key, val)
        os.environ[key] = val

    flash(f'Provider settings saved.', 'success')
    return redirect(url_for('setup', step='credentials'))


@app.route('/setup/save-credentials', methods=['POST'])
def setup_save_credentials():
    """Step 3 result: save email/password/name to .env."""
    smtp_user = request.form.get('smtp_user', '').strip()
    smtp_password = request.form.get('smtp_password', '').strip()
    from_name = request.form.get('from_name', '').strip()
    from_email = request.form.get('from_email', '').strip() or smtp_user

    if not smtp_user or not smtp_password:
        flash('Email and password are required.', 'error')
        return redirect(url_for('setup', step='credentials'))

    if not ENV_PATH.exists():
        ENV_PATH.write_text('')

    for key, val in [('SMTP_USER', smtp_user), ('SMTP_PASSWORD', smtp_password),
                     ('FROM_NAME', from_name), ('FROM_EMAIL', from_email)]:
        set_key(str(ENV_PATH), key, val)
        os.environ[key] = val

    flash('Credentials saved.', 'success')
    return redirect(url_for('setup', step='test-connection'))


@app.route('/setup/test-connection', methods=['POST'])
def setup_test_connection():
    """AJAX endpoint: test SMTP connection (no email sent)."""
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', 587))
    user = os.environ.get('SMTP_USER', '')
    password = os.environ.get('SMTP_PASSWORD', '')

    steps = []

    # Step 1: DNS / connectivity
    try:
        socket.create_connection((host, port), timeout=10)
        steps.append({'name': f'Connect to {host}:{port}', 'ok': True})
    except Exception as e:
        steps.append({'name': f'Connect to {host}:{port}', 'ok': False, 'error': str(e)})
        return jsonify({'steps': steps, 'success': False})

    # Step 2: STARTTLS
    try:
        server = smtplib.SMTP(host, port, timeout=10)
        server.starttls()
        steps.append({'name': 'STARTTLS encryption', 'ok': True})
    except Exception as e:
        steps.append({'name': 'STARTTLS encryption', 'ok': False, 'error': str(e)})
        return jsonify({'steps': steps, 'success': False})

    # Step 3: Authentication
    try:
        server.login(user, password)
        steps.append({'name': f'Authenticate as {user}', 'ok': True})
    except smtplib.SMTPAuthenticationError as e:
        steps.append({'name': f'Authenticate as {user}', 'ok': False,
                      'error': 'Authentication failed. Check your username and password. If using Gmail, make sure you\'re using an App Password.'})
        server.quit()
        return jsonify({'steps': steps, 'success': False})
    except Exception as e:
        steps.append({'name': f'Authenticate as {user}', 'ok': False, 'error': str(e)})
        server.quit()
        return jsonify({'steps': steps, 'success': False})

    server.quit()
    return jsonify({'steps': steps, 'success': True})


@app.route('/setup/send-test', methods=['POST'])
def setup_send_test():
    """AJAX endpoint: send a real test email."""
    test_addr = request.form.get('test_email', '').strip()
    if not test_addr:
        return jsonify({'success': False, 'error': 'Enter an email address.'})

    try:
        subject = "NewsLetterGo — Test Email"
        body = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:40px;background:#f5f5f5;font-family:-apple-system,sans-serif;">
<div style="max-width:480px;margin:0 auto;background:white;border-radius:12px;padding:40px;text-align:center;">
<h1 style="color:#1a1a2e;margin:0 0 10px;">It works!</h1>
<p style="color:#666;font-size:16px;line-height:1.6;">
Your email is configured correctly.<br>
You're ready to start sending newsletters with <strong>NewsLetterGo</strong>.
</p>
<hr style="border:none;border-top:1px solid #eee;margin:30px 0;">
<p style="color:#999;font-size:13px;">This is a test email from your setup wizard.</p>
</div>
</body></html>'''
        send_email(test_addr, '', subject, body)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ============================================================
# CONTACTS
# ============================================================


@app.route('/dashboard')
def dashboard():
    db = get_db()
    contact_count = db.execute("SELECT COUNT(*) FROM contacts WHERE unsubscribed=0").fetchone()[0]
    template_count = db.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
    send_count = db.execute("SELECT COUNT(*) FROM sends").fetchone()[0]
    recent_sends = db.execute(
        "SELECT s.*, t.name as template_name FROM sends s JOIN templates t ON s.template_id=t.id ORDER BY s.sent_at DESC LIMIT 5"
    ).fetchall()
    switch = db.execute("SELECT * FROM deadman_switch LIMIT 1").fetchone()
    db.close()
    return render_template('dashboard.html',
                           contact_count=contact_count,
                           template_count=template_count,
                           send_count=send_count,
                           recent_sends=recent_sends,
                           switch=switch)


@app.route('/contacts')
def contacts():
    db = get_db()
    rows = db.execute("SELECT * FROM contacts ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template('contacts.html', contacts=rows)


@app.route('/contacts/add', methods=['POST'])
def add_contact():
    email = request.form.get('email', '').strip()
    name = request.form.get('name', '').strip()
    groups = request.form.get('groups', '').strip()

    if not email:
        flash('Email is required.', 'error')
        return redirect(url_for('contacts'))

    group_list = [g.strip() for g in groups.split(',') if g.strip()] if groups else []

    db = get_db()
    try:
        db.execute("INSERT INTO contacts (email, name, groups, unsubscribe_token) VALUES (?, ?, ?, lower(hex(randomblob(16))))",
                    (email, name, json.dumps(group_list)))
        db.commit()
        flash(f'Added {email}', 'success')
    except Exception as e:
        if 'UNIQUE' in str(e):
            flash(f'{email} already exists.', 'error')
        else:
            flash(str(e), 'error')
    db.close()
    return redirect(url_for('contacts'))


@app.route('/contacts/<int:contact_id>/delete', methods=['POST'])
def delete_contact(contact_id):
    db = get_db()
    db.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
    db.commit()
    db.close()
    flash('Contact deleted.', 'success')
    return redirect(url_for('contacts'))


@app.route('/contacts/<int:contact_id>/edit', methods=['POST'])
def edit_contact(contact_id):
    email = request.form.get('email', '').strip()
    name = request.form.get('name', '').strip()
    groups = request.form.get('groups', '').strip()
    group_list = [g.strip() for g in groups.split(',') if g.strip()] if groups else []

    db = get_db()
    db.execute("UPDATE contacts SET email=?, name=?, groups=? WHERE id=?",
               (email, name, json.dumps(group_list), contact_id))
    db.commit()
    db.close()
    flash('Contact updated.', 'success')
    return redirect(url_for('contacts'))


@app.route('/contacts/import', methods=['POST'])
def import_contacts():
    """Import contacts from CSV text: email,name,group1;group2"""
    csv_text = request.form.get('csv_data', '').strip()
    if not csv_text:
        flash('No data provided.', 'error')
        return redirect(url_for('contacts'))

    db = get_db()
    added = 0
    for line in csv_text.strip().split('\n'):
        parts = [p.strip() for p in line.split(',')]
        if not parts or not parts[0]:
            continue
        email = parts[0]
        name = parts[1] if len(parts) > 1 else ''
        groups = parts[2].split(';') if len(parts) > 2 else []
        groups = [g.strip() for g in groups if g.strip()]
        try:
            db.execute("INSERT INTO contacts (email, name, groups, unsubscribe_token) VALUES (?, ?, ?, lower(hex(randomblob(16))))",
                        (email, name, json.dumps(groups)))
            added += 1
        except Exception:
            pass  # skip duplicates
    db.commit()
    db.close()
    flash(f'Imported {added} contacts.', 'success')
    return redirect(url_for('contacts'))


# ============================================================
# TEMPLATES
# ============================================================

@app.route('/templates')
def templates_list():
    db = get_db()
    rows = db.execute("SELECT * FROM templates ORDER BY id").fetchall()
    db.close()
    return render_template('templates.html', templates=rows)


@app.route('/templates/<slug>')
def template_detail(slug):
    db = get_db()
    tpl = db.execute("SELECT * FROM templates WHERE slug=?", (slug,)).fetchone()
    if not tpl:
        flash('Template not found.', 'error')
        db.close()
        return redirect(url_for('templates_list'))

    groups_raw = db.execute("SELECT groups FROM contacts WHERE unsubscribed=0").fetchall()
    all_groups = set()
    for row in groups_raw:
        for g in json.loads(row['groups']):
            all_groups.add(g)
    db.close()

    fields = json.loads(tpl['fields'])
    return render_template('template_detail.html', template=tpl, fields=fields, groups=sorted(all_groups))


@app.route('/templates/<slug>/preview', methods=['POST'])
def template_preview(slug):
    db = get_db()
    tpl = db.execute("SELECT * FROM templates WHERE slug=?", (slug,)).fetchone()
    db.close()
    if not tpl:
        return jsonify({'error': 'Template not found'}), 404

    fields = json.loads(tpl['fields'])
    values = {}
    for f in fields:
        values[f['name']] = request.form.get(f['name'], '')

    from jinja2 import Template
    subject = Template(tpl['subject_template']).render(**values)
    body = Template(tpl['body_template']).render(**values)

    return jsonify({'subject': subject, 'body': body})


@app.route('/templates/<slug>/send', methods=['POST'])
def template_send(slug):

    db = get_db()
    tpl = db.execute("SELECT * FROM templates WHERE slug=?", (slug,)).fetchone()
    if not tpl:
        flash('Template not found.', 'error')
        db.close()
        return redirect(url_for('templates_list'))

    fields = json.loads(tpl['fields'])
    values = {}
    for f in fields:
        values[f['name']] = request.form.get(f['name'], '')

    font = request.form.get('font', '').strip() or None
    target_group = request.form.get('target_group', 'all')
    test_email = request.form.get('test_email', '').strip()

    from jinja2 import Template
    subject = Template(tpl['subject_template']).render(**values)
    body = Template(tpl['body_template']).render(**values)

    s = get_settings(db)

    # Optionally shorten URLs (shortener module added in Task 12)
    if s.get('url_shortener_enabled') == '1':
        try:
            from shortener import shorten_all_urls
            body = shorten_all_urls(body, s)
        except ImportError:
            pass  # shortener not yet implemented

    if test_email:
        # Test send: use a placeholder token, no DB send row
        full_html = email_builder.build_email(
            body=body, settings=s,
            unsubscribe_token='test',
            send_id=0,
            recipient_email=test_email,
            secret_key=app.secret_key,
            font=font,
        )
        try:
            send_email(test_email, '', subject, full_html)
            flash(f'Test email sent to {test_email}!', 'success')
        except Exception as e:
            flash(f'Error sending test: {e}', 'error')
        db.close()
        return redirect(url_for('template_detail', slug=slug))

    # Resolve recipients
    if target_group == 'all':
        rows = db.execute(
            "SELECT * FROM contacts WHERE unsubscribed=0"
        ).fetchall()
    else:
        all_rows = db.execute(
            "SELECT * FROM contacts WHERE unsubscribed=0"
        ).fetchall()
        rows = [r for r in all_rows if target_group in json.loads(r['groups'])]

    if not rows:
        flash('No recipients found for that group.', 'error')
        db.close()
        return redirect(url_for('template_detail', slug=slug))

    # Insert sends row BEFORE sending (send_id needed for pixel URLs)
    db.execute(
        "INSERT INTO sends (template_id, subject, body, recipient_count) VALUES (?, ?, ?, 0)",
        (tpl['id'], subject, body)
    )
    db.commit()
    send_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    successes = 0
    errors = []
    for r in rows:
        # Ensure unsubscribe_token exists (lazy backfill for old contacts)
        token = r['unsubscribe_token']
        if not token:
            token = secrets.token_hex(16)
            db.execute(
                "UPDATE contacts SET unsubscribe_token=? WHERE id=?",
                (token, r['id'])
            )
            db.commit()

        full_html = email_builder.build_email(
            body=body, settings=s,
            unsubscribe_token=token,
            send_id=send_id,
            recipient_email=r['email'],
            secret_key=app.secret_key,
            font=font,
        )
        try:
            send_email(r['email'], r['name'], subject, full_html)
            successes += 1
        except Exception as e:
            errors.append((r['email'], str(e)))

    db.execute(
        "UPDATE sends SET recipient_count=? WHERE id=?", (successes, send_id)
    )
    db.commit()
    db.close()

    if errors:
        flash(f'Sent to {successes} recipients. {len(errors)} errors.', 'warning')
    else:
        flash(f'Sent to {successes} recipients!', 'success')

    return redirect(url_for('template_detail', slug=slug))


# ============================================================
# DEAD MAN'S SWITCH
# ============================================================

@app.route('/deadman')
def deadman():
    db = get_db()
    switch = db.execute("SELECT * FROM deadman_switch LIMIT 1").fetchone()
    db.close()
    return render_template('deadman.html', switch=switch)


@app.route('/deadman/checkin', methods=['POST'])
def deadman_checkin():
    db = get_db()
    db.execute("UPDATE deadman_switch SET last_check_in=?", (datetime.utcnow().isoformat(),))
    db.commit()
    db.close()
    flash("Check-in recorded! Timer reset.", 'success')
    return redirect(url_for('deadman'))


@app.route('/deadman/update', methods=['POST'])
def deadman_update():
    active = 1 if request.form.get('active') else 0
    interval = int(request.form.get('check_in_interval_hours', 72))
    recipient_group = request.form.get('recipient_group', 'emergency').strip()
    subject = request.form.get('subject', '').strip()
    trip_details = request.form.get('trip_details', '').strip()
    body = request.form.get('body', '').strip()

    db = get_db()
    if active:
        # Reset check-in time when activating
        db.execute('''UPDATE deadman_switch SET
            active=?, check_in_interval_hours=?, recipient_group=?,
            subject=?, body=?, trip_details=?, last_check_in=?''',
            (active, interval, recipient_group, subject, body, trip_details,
             datetime.utcnow().isoformat()))
    else:
        db.execute('''UPDATE deadman_switch SET
            active=?, check_in_interval_hours=?, recipient_group=?,
            subject=?, body=?, trip_details=?''',
            (active, interval, recipient_group, subject, body, trip_details))
    db.commit()
    db.close()

    status = 'activated' if active else 'deactivated'
    flash(f"Dead man's switch {status}.", 'success')
    return redirect(url_for('deadman'))


@app.route('/deadman/check', methods=['POST'])
def deadman_trigger_check():
    """Manually trigger the dead man's switch check (also called by scheduler)."""
    result = check_deadman_switch()
    if result == 'triggered':
        flash("Switch was triggered! Alert emails sent.", 'warning')
    elif result == 'ok':
        flash("Switch checked — still within check-in window.", 'success')
    else:
        flash("Switch is not active.", 'info')
    return redirect(url_for('deadman'))


def check_deadman_switch():
    """Check if the dead man's switch should fire. Returns 'triggered', 'ok', or 'inactive'."""
    db = get_db()
    switch = db.execute("SELECT * FROM deadman_switch LIMIT 1").fetchone()

    if not switch or not switch['active']:
        db.close()
        return 'inactive'

    last = datetime.fromisoformat(switch['last_check_in'])
    deadline = last + timedelta(hours=switch['check_in_interval_hours'])

    if datetime.utcnow() < deadline:
        db.close()
        return 'ok'

    # Time's up — send the alert
    group = switch['recipient_group']
    rows = db.execute("SELECT email, name, groups FROM contacts WHERE unsubscribed=0").fetchall()
    recipients = [(r['email'], r['name']) for r in rows if group in json.loads(r['groups'])]

    if not recipients:
        db.close()
        return 'triggered'  # no recipients but switch fired

    # Build the email from the deadman switch template
    tpl = db.execute("SELECT * FROM templates WHERE slug='deadman-switch'").fetchone()
    if tpl and switch['trip_details']:
        from jinja2 import Template
        # Parse trip details as JSON if possible, otherwise use as-is
        try:
            values = json.loads(switch['trip_details'])
        except (json.JSONDecodeError, TypeError):
            values = {'trip_details': switch['trip_details']}
        body = Template(tpl['body_template']).render(**values)
    else:
        body = switch['body'] or f"<p>{switch['subject']}</p><p>Trip details: {switch['trip_details']}</p>"

    full_body = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:20px;background:#f5f5f5;">{body}</body></html>'''

    subject = switch['subject'] or "Emergency: Check-in overdue"
    send_bulk(recipients, subject, full_body)

    # Deactivate after sending
    db.execute("UPDATE deadman_switch SET active=0")
    db.commit()
    db.close()
    return 'triggered'


# ============================================================
# SCHEDULER — checks dead man's switch every 15 minutes
# ============================================================

from flask_apscheduler import APScheduler

scheduler = APScheduler()


class SchedulerConfig:
    SCHEDULER_API_ENABLED = False
    JOBS = [
        {
            'id': 'deadman_check',
            'func': 'app:check_deadman_switch',
            'trigger': 'interval',
            'minutes': 15,
        }
    ]


app.config.from_object(SchedulerConfig)
scheduler.init_app(app)
if not os.environ.get('TESTING'):
    scheduler.start()


# ============================================================
# HISTORY
# ============================================================

@app.route('/history')
def history():
    db = get_db()
    sends = db.execute(
        "SELECT s.*, t.name as template_name FROM sends s JOIN templates t ON s.template_id=t.id ORDER BY s.sent_at DESC"
    ).fetchall()
    db.close()
    return render_template('history.html', sends=sends)


@app.route('/history/<int:send_id>')
def history_detail(send_id):
    db = get_db()
    send = db.execute(
        "SELECT s.*, t.name as template_name FROM sends s JOIN templates t ON s.template_id=t.id WHERE s.id=?",
        (send_id,)
    ).fetchone()
    db.close()
    if not send:
        flash('Send not found.', 'error')
        return redirect(url_for('history'))
    return render_template('history_detail.html', send=send)


# ============================================================
# TRACKING PIXEL
# ============================================================

@app.route('/track/<int:send_id>/<token>.gif')
def track_open(send_id, token):
    """
    Serve a 1x1 transparent GIF and increment open_count for the send.

    Token is a 16-char hex string derived from HMAC(send_id:email).
    We accept any 16-char hex token — we can't reverse-verify without the
    recipient email. The token acts as a modest forgery deterrent.
    Always returns the GIF (never reveals whether the send_id is valid).
    """
    if re.fullmatch(r'[0-9a-f]{16}', token):
        db = get_db()
        db.execute(
            "UPDATE sends SET open_count = open_count + 1 WHERE id = ?",
            (send_id,)
        )
        db.commit()
        db.close()

    return Response(
        TRACKING_GIF,
        mimetype='image/gif',
        headers={'Cache-Control': 'no-store, no-cache, must-revalidate'}
    )


# ============================================================
# UNSUBSCRIBE
# ============================================================

@app.route('/unsubscribe/<token>')
def unsubscribe(token):
    """
    One-click unsubscribe. Sets contacts.unsubscribed=1 for the matching token.
    Always renders the confirmation page — no information leaked for invalid tokens.

    KNOWN LIMITATION: Some email security scanners pre-fetch all links, which may
    trigger this route and unsubscribe the recipient before they read the email.
    This is an accepted tradeoff of one-click unsubscribe.
    """
    db = get_db()
    contact = db.execute(
        "SELECT id FROM contacts WHERE unsubscribe_token=?", (token,)
    ).fetchone()
    if contact:
        db.execute(
            "UPDATE contacts SET unsubscribed=1 WHERE id=?", (contact['id'],)
        )
        db.commit()
    db.close()
    return render_template('unsubscribe.html')


# ============================================================
# SETTINGS
# ============================================================

SETTINGS_KEYS = [
    'base_url', 'header_image_url', 'footer_image_url',
    'default_font', 'tracking_pixel_enabled',
    'url_shortener_enabled', 'url_shortener_provider',
    'url_shortener_api_key', 'url_shortener_bitly_group',
]

FONT_OPTIONS = [
    {'value': 'Georgia, serif',         'label': 'Georgia (serif)'},
    {'value': 'Arial, sans-serif',      'label': 'Arial (sans-serif)'},
    {'value': 'Helvetica, sans-serif',  'label': 'Helvetica (sans-serif)'},
    {'value': 'Verdana, sans-serif',    'label': 'Verdana (sans-serif)'},
    {'value': 'Times New Roman, serif', 'label': 'Times New Roman (serif)'},
    {'value': 'Trebuchet MS, sans-serif','label': 'Trebuchet MS (sans-serif)'},
    {'value': 'Courier New, monospace', 'label': 'Courier New (monospace)'},
]


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    db = get_db()
    if request.method == 'POST':
        for key in SETTINGS_KEYS:
            # Checkboxes: if not in form, value is '0'
            if key in ('tracking_pixel_enabled', 'url_shortener_enabled'):
                value = '1' if request.form.get(key) else '0'
            else:
                value = request.form.get(key, '').strip()
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
        db.commit()
        flash('Settings saved.', 'success')
        db.close()
        return redirect(url_for('settings'))

    s = get_settings(db)
    db.close()

    base_url = s.get('base_url', '')
    tracking_enabled = s.get('tracking_pixel_enabled') == '1'
    show_tracking_warning = tracking_enabled and (
        not base_url or base_url.startswith('http://localhost') or
        base_url.startswith('http://127.')
    )

    return render_template('settings.html',
                           settings=s,
                           fonts=FONT_OPTIONS,
                           show_tracking_warning=show_tracking_warning)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
