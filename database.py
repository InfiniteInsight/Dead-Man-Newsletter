import sqlite3
import os
import json
import hashlib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'newsletter.db')


def _body_hash(body):
    return hashlib.sha256(body.encode()).hexdigest()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            groups TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            unsubscribed INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            subject_template TEXT NOT NULL DEFAULT '',
            body_template TEXT NOT NULL,
            fields TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            recipient_count INTEGER NOT NULL DEFAULT 0,
            sent_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (template_id) REFERENCES templates(id)
        );

        CREATE TABLE IF NOT EXISTS deadman_switch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            active INTEGER NOT NULL DEFAULT 0,
            check_in_interval_hours INTEGER NOT NULL DEFAULT 72,
            last_check_in TEXT NOT NULL DEFAULT (datetime('now')),
            recipient_group TEXT NOT NULL DEFAULT 'emergency',
            subject TEXT NOT NULL DEFAULT 'Emergency: I may need help',
            body TEXT NOT NULL DEFAULT '',
            trip_details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY NOT NULL,
            value TEXT NOT NULL DEFAULT ''
        );
    ''')
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")  # executescript() resets this pragma

    # Migrate: add unsubscribe_token to contacts if missing
    existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()]
    if 'unsubscribe_token' not in existing_cols:
        conn.execute("ALTER TABLE contacts ADD COLUMN unsubscribe_token TEXT")
        conn.execute(
            "UPDATE contacts SET unsubscribe_token = lower(hex(randomblob(16))) "
            "WHERE unsubscribe_token IS NULL"
        )
        conn.commit()

    # Migrate: add open_count to sends if missing
    existing_send_cols = [r[1] for r in conn.execute("PRAGMA table_info(sends)").fetchall()]
    if 'open_count' not in existing_send_cols:
        conn.execute(
            "ALTER TABLE sends ADD COLUMN open_count INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()

    # Seed default templates if empty, otherwise refresh unchanged defaults
    if conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0] == 0:
        _seed_templates(conn)
    else:
        _refresh_templates(conn)

    # Seed deadman switch config if empty
    if conn.execute("SELECT COUNT(*) FROM deadman_switch").fetchone()[0] == 0:
        conn.execute('''INSERT INTO deadman_switch
            (active, check_in_interval_hours, body, trip_details)
            VALUES (0, 72, '', '')''')
        conn.commit()

    # Seed default settings if empty
    if conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        defaults = [
            ('base_url', ''),
            ('header_image_url', ''),
            ('footer_image_url', ''),
            ('default_font', 'Georgia, serif'),
            ('tracking_pixel_enabled', '0'),
            ('url_shortener_enabled', '0'),
            ('url_shortener_provider', 'bitly'),
            ('url_shortener_api_key', ''),
            ('url_shortener_bitly_group', ''),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults
        )
        conn.commit()

    conn.close()


def get_settings(conn):
    """Return all settings as a plain dict {key: value}."""
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r['key']: r['value'] for r in rows}


_TEMPLATE_DEFS = [
    {
        'slug': 'newsletter',
        'name': 'Regular Newsletter',
        'description': 'A classic newsletter with a greeting, main content sections, and a sign-off.',
        'subject_template': '{{title}}',
        'fields': json.dumps([
            {'name': 'title', 'label': 'Newsletter Title', 'type': 'text'},
            {'name': 'intro', 'label': 'Introduction', 'type': 'textarea'},
            {'name': 'section1_title', 'label': 'Section 1 Title', 'type': 'text'},
            {'name': 'section1_body', 'label': 'Section 1 Content', 'type': 'textarea'},
            {'name': 'section2_title', 'label': 'Section 2 Title (optional)', 'type': 'text'},
            {'name': 'section2_body', 'label': 'Section 2 Content (optional)', 'type': 'textarea'},
            {'name': 'closing', 'label': 'Closing Message', 'type': 'textarea'},
        ]),
        'body_template': '''<div style="max-width:600px;margin:0 auto;padding:24px 0;">
  <h1 style="color:#1a1a2e;border-bottom:3px solid #e94560;padding-bottom:12px;font-size:28px;margin:0 0 20px;">{{title}}</h1>
  <p style="font-size:16px;line-height:1.7;color:#333;margin:0 0 24px;">{{intro | safe}}</p>
  {% if section1_title %}
  <h2 style="color:#1a1a2e;font-size:20px;margin:0 0 12px;">{{section1_title}}</h2>
  {% endif %}
  <div style="font-size:16px;line-height:1.7;color:#333;margin:0 0 24px;">{{section1_body | safe}}</div>
  {% if section2_title %}
  <h2 style="color:#1a1a2e;font-size:20px;margin:0 0 12px;">{{section2_title}}</h2>
  <div style="font-size:16px;line-height:1.7;color:#333;margin:0 0 24px;">{{section2_body | safe}}</div>
  {% endif %}
  <hr style="border:none;border-top:1px solid #ddd;margin:32px 0;">
  <div style="font-size:16px;line-height:1.7;color:#333;">{{closing | safe}}</div>
</div>''',
    },
    {
        'slug': 'job-seeking',
        'name': "I'm Looking for Work",
        'description': 'Let your network know you\'re available. Highlight your skills, experience, and what you\'re looking for.',
        'subject_template': "{{name}} is looking for new opportunities",
        'fields': json.dumps([
            {'name': 'name', 'label': 'Your Name', 'type': 'text'},
            {'name': 'current_status', 'label': 'Current Status (e.g. "Recently laid off", "Wrapping up a contract")', 'type': 'text'},
            {'name': 'looking_for', 'label': 'What You\'re Looking For', 'type': 'textarea'},
            {'name': 'skills', 'label': 'Key Skills & Experience', 'type': 'textarea'},
            {'name': 'portfolio_url', 'label': 'Portfolio / LinkedIn URL', 'type': 'text'},
            {'name': 'personal_note', 'label': 'Personal Note', 'type': 'textarea'},
        ]),
        'body_template': '''<div style="max-width:600px;margin:0 auto;padding:24px 0;font-family:-apple-system,Helvetica,Arial,sans-serif;">
  <h1 style="color:#2d3436;font-size:26px;margin:0 0 16px;">Hey, I\'m looking for work 👋</h1>
  <p style="font-size:16px;line-height:1.6;background:#f8f9fa;padding:16px;border-radius:8px;border-left:4px solid #0984e3;margin:0 0 24px;">
    <strong>Status:</strong> {{current_status}}
  </p>
  <h2 style="color:#2d3436;font-size:18px;margin:0 0 10px;">What I\'m Looking For</h2>
  <div style="font-size:16px;line-height:1.7;color:#333;margin:0 0 24px;">{{looking_for | safe}}</div>
  <h2 style="color:#2d3436;font-size:18px;margin:0 0 10px;">Skills &amp; Experience</h2>
  <div style="font-size:16px;line-height:1.7;color:#333;margin:0 0 24px;">{{skills | safe}}</div>
  {% if portfolio_url %}
  <p style="margin:0 0 24px;">
    <a href="{{portfolio_url}}" style="display:inline-block;background:#0984e3;color:#fff;padding:10px 22px;border-radius:6px;text-decoration:none;font-weight:bold;">View my work →</a>
  </p>
  {% endif %}
  {% if personal_note %}
  <hr style="border:none;border-top:1px solid #ddd;margin:24px 0;">
  <div style="font-size:16px;line-height:1.7;color:#555;font-style:italic;">{{personal_note | safe}}</div>
  {% endif %}
  <p style="font-size:14px;color:#636e72;margin:24px 0 0;">If you know of anything or can make an introduction, I\'d really appreciate it. Feel free to forward this along!</p>
</div>''',
    },
    {
        'slug': 'social-roundup',
        'name': 'Social Media Roundup',
        'description': "Recap what you posted this week across platforms. Great for influencers and creators.",
        'subject_template': "{{creator_name}}'s Weekly Roundup — {{week_label}}",
        'fields': json.dumps([
            {'name': 'creator_name', 'label': 'Your Name / Handle', 'type': 'text'},
            {'name': 'week_label', 'label': 'Week Label (e.g. "March 10-16")', 'type': 'text'},
            {'name': 'intro_note', 'label': 'Quick Intro Note', 'type': 'textarea'},
            {'name': 'highlights', 'label': 'Top Posts / Highlights (use links!)', 'type': 'textarea'},
            {'name': 'stats', 'label': 'Stats / Milestones (optional)', 'type': 'textarea'},
            {'name': 'upcoming', 'label': 'Coming Up Next Week', 'type': 'textarea'},
        ]),
        'body_template': '''<div style="max-width:600px;margin:0 auto;">
  <div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:32px;border-radius:12px 12px 0 0;color:white;">
    <h1 style="margin:0;font-size:26px;">📱 Weekly Roundup</h1>
    <p style="margin:6px 0 0;opacity:0.9;font-size:15px;">{{creator_name}} — {{week_label}}</p>
  </div>
  <div style="padding:24px;background:#f8f9fa;border-radius:0 0 12px 12px;">
    <div style="font-size:16px;line-height:1.7;color:#333;margin:0 0 20px;">{{intro_note | safe}}</div>
    <h2 style="color:#667eea;font-size:18px;margin:0 0 12px;">🔥 Highlights</h2>
    <div style="font-size:16px;line-height:1.8;color:#333;margin:0 0 20px;">{{highlights | safe}}</div>
    {% if stats %}
    <h2 style="color:#667eea;font-size:18px;margin:0 0 12px;">📊 Stats &amp; Milestones</h2>
    <div style="font-size:16px;line-height:1.7;color:#333;margin:0 0 20px;">{{stats | safe}}</div>
    {% endif %}
    {% if upcoming %}
    <h2 style="color:#667eea;font-size:18px;margin:0 0 12px;">👀 Coming Up</h2>
    <div style="font-size:16px;line-height:1.7;color:#333;">{{upcoming | safe}}</div>
    {% endif %}
  </div>
</div>''',
    },
    {
        'slug': 'new-videos',
        'name': 'New Videos',
        'description': 'Announce your latest video releases with thumbnails and links.',
        'subject_template': '🎬 New from {{channel_name}}: {{video1_title}}',
        'fields': json.dumps([
            {'name': 'channel_name', 'label': 'Channel / Creator Name', 'type': 'text'},
            {'name': 'intro', 'label': 'Quick Intro', 'type': 'textarea'},
            {'name': 'video1_title', 'label': 'Video 1 Title', 'type': 'text'},
            {'name': 'video1_url', 'label': 'Video 1 URL', 'type': 'text'},
            {'name': 'video1_description', 'label': 'Video 1 Description', 'type': 'textarea'},
            {'name': 'video2_title', 'label': 'Video 2 Title (optional)', 'type': 'text'},
            {'name': 'video2_url', 'label': 'Video 2 URL (optional)', 'type': 'text'},
            {'name': 'video2_description', 'label': 'Video 2 Description (optional)', 'type': 'textarea'},
            {'name': 'outro', 'label': 'Closing Note', 'type': 'textarea'},
        ]),
        'body_template': '''<div style="max-width:600px;margin:0 auto;background:#0f0f0f;padding:32px;border-radius:12px;">
  <h1 style="color:#ff0000;font-size:26px;margin:0 0 12px;">🎬 {{channel_name}}</h1>
  <div style="color:#aaa;font-size:16px;line-height:1.7;margin:0 0 20px;">{{intro | safe}}</div>
  <div style="background:#1a1a1a;border-radius:8px;padding:22px;margin:0 0 16px;">
    <h2 style="color:#fff;font-size:18px;margin:0 0 10px;">{{video1_title}}</h2>
    <div style="color:#aaa;font-size:15px;line-height:1.6;margin:0 0 16px;">{{video1_description | safe}}</div>
    <a href="{{video1_url}}" style="display:inline-block;background:#ff0000;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">▶ Watch Now</a>
  </div>
  {% if video2_title %}
  <div style="background:#1a1a1a;border-radius:8px;padding:22px;margin:0 0 16px;">
    <h2 style="color:#fff;font-size:18px;margin:0 0 10px;">{{video2_title}}</h2>
    <div style="color:#aaa;font-size:15px;line-height:1.6;margin:0 0 16px;">{{video2_description | safe}}</div>
    <a href="{{video2_url}}" style="display:inline-block;background:#ff0000;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">▶ Watch Now</a>
  </div>
  {% endif %}
  {% if outro %}
  <hr style="border:none;border-top:1px solid #333;margin:24px 0;">
  <div style="color:#aaa;font-size:15px;line-height:1.6;">{{outro | safe}}</div>
  {% endif %}
</div>''',
    },
    {
        'slug': 'deadman-switch',
        'name': "Dead Man's Switch (Safety Alert)",
        'description': "Automatically sent if you don't check in. For solo travel, backpacking, etc.",
        'subject_template': '🚨 SAFETY ALERT: {{traveler_name}} has not checked in',
        'fields': json.dumps([
            {'name': 'traveler_name', 'label': 'Your Name', 'type': 'text'},
            {'name': 'trip_name', 'label': 'Trip Name / Location', 'type': 'text'},
            {'name': 'last_known_location', 'label': 'Last Known Location / Trailhead', 'type': 'text'},
            {'name': 'trip_dates', 'label': 'Trip Dates', 'type': 'text'},
            {'name': 'itinerary', 'label': 'Planned Itinerary / Route', 'type': 'textarea'},
            {'name': 'gear_description', 'label': 'Gear / What I\'m Wearing', 'type': 'textarea'},
            {'name': 'vehicle_info', 'label': 'Vehicle Info (parked at trailhead)', 'type': 'text'},
            {'name': 'emergency_contacts', 'label': 'Emergency Contacts / Who to Call', 'type': 'textarea'},
            {'name': 'instructions', 'label': 'What To Do (call ranger station, etc.)', 'type': 'textarea'},
        ]),
        'body_template': '''<div style="max-width:600px;margin:0 auto;">
  <div style="background:#d63031;padding:24px;border-radius:8px 8px 0 0;color:white;text-align:center;">
    <h1 style="margin:0;font-size:26px;">🚨 SAFETY ALERT</h1>
    <p style="margin:8px 0 0;font-size:18px;">{{traveler_name}} has not checked in</p>
  </div>
  <div style="background:#fff3f3;padding:28px;border:2px solid #d63031;border-top:none;border-radius:0 0 8px 8px;">
    <p style="font-size:16px;line-height:1.7;margin:0 0 20px;">
      This is an automated safety message. <strong>{{traveler_name}}</strong> set up this alert
      before going on a trip and has not checked in within the expected timeframe.
      <strong>This may mean they need help.</strong>
    </p>
    <h2 style="color:#d63031;font-size:18px;margin:0 0 12px;">📍 Trip Details</h2>
    <table style="width:100%;font-size:15px;line-height:1.7;margin:0 0 20px;">
      <tr><td style="padding:4px 10px;font-weight:bold;white-space:nowrap;vertical-align:top;">Trip:</td><td style="padding:4px 10px;">{{trip_name}}</td></tr>
      <tr style="background:#fff;"><td style="padding:4px 10px;font-weight:bold;white-space:nowrap;vertical-align:top;">Dates:</td><td style="padding:4px 10px;">{{trip_dates}}</td></tr>
      <tr><td style="padding:4px 10px;font-weight:bold;white-space:nowrap;vertical-align:top;">Last Known Location:</td><td style="padding:4px 10px;">{{last_known_location}}</td></tr>
      {% if vehicle_info %}
      <tr style="background:#fff;"><td style="padding:4px 10px;font-weight:bold;white-space:nowrap;vertical-align:top;">Vehicle:</td><td style="padding:4px 10px;">{{vehicle_info}}</td></tr>
      {% endif %}
    </table>
    {% if itinerary %}
    <h2 style="color:#d63031;font-size:18px;margin:0 0 10px;">🗺️ Planned Route / Itinerary</h2>
    <div style="font-size:15px;line-height:1.7;background:#fff;padding:16px;border-radius:6px;border:1px solid #eee;margin:0 0 20px;">{{itinerary | safe}}</div>
    {% endif %}
    {% if gear_description %}
    <h2 style="color:#d63031;font-size:18px;margin:0 0 10px;">🎒 Gear / Appearance</h2>
    <div style="font-size:15px;line-height:1.7;margin:0 0 20px;">{{gear_description | safe}}</div>
    {% endif %}
    {% if emergency_contacts %}
    <h2 style="color:#d63031;font-size:18px;margin:0 0 10px;">📞 Emergency Contacts</h2>
    <div style="font-size:15px;line-height:1.7;margin:0 0 20px;">{{emergency_contacts | safe}}</div>
    {% endif %}
    {% if instructions %}
    <h2 style="color:#d63031;font-size:18px;margin:0 0 10px;">⚠️ What To Do</h2>
    <div style="font-size:16px;line-height:1.7;font-weight:bold;background:#fff;padding:16px;border-radius:6px;border:2px solid #d63031;margin:0 0 20px;">{{instructions | safe}}</div>
    {% endif %}
    <hr style="border:none;border-top:2px solid #d63031;margin:24px 0;">
    <p style="font-size:13px;color:#666;text-align:center;margin:0;">
      This message was sent automatically because {{traveler_name}} did not check in.
      If you have confirmed they are safe, no further action is needed.
    </p>
  </div>
</div>''',
    },
]

_ORIGINAL_TEMPLATE_HASHES = {
    'newsletter': 'eb167c8eba6960c0b6d192c30062f2a48a76fdd831ac8b48db193cb80e8acd69',
    'job-seeking': '3ae9e00b78cd5415f9f09478f88e95cfdf0d128de5389898bbc4430e4d268f12',
    'social-roundup': '73fbb9cf96ae9cc78f8a67c6dccfcf9c43c09990d3d7d172766247c08a18f549',
    'new-videos': '0e8dc7369d89538435e26851b04f0a383a2ecd002179a207e1048180deb767c1',
    'deadman-switch': '6baadfb85b3fb4b075c218a7f75c07d5b2ed755605a522ff94e8ed11714a8bd5',
}


def _get_new_template_bodies():
    """Return {slug: new_body_template} for all default templates."""
    return {t['slug']: t['body_template'] for t in _TEMPLATE_DEFS}


def _refresh_templates(conn):
    """Re-seed template bodies that still match their original defaults.
    Templates customised by the user are left untouched."""
    new_bodies = _get_new_template_bodies()
    for slug, new_body in new_bodies.items():
        row = conn.execute(
            "SELECT body_template FROM templates WHERE slug=?", (slug,)
        ).fetchone()
        if not row:
            continue
        current_hash = _body_hash(row['body_template'])
        original_hash = _ORIGINAL_TEMPLATE_HASHES.get(slug, '')
        if current_hash == original_hash:
            # Matches original default — safe to update
            conn.execute(
                "UPDATE templates SET body_template=? WHERE slug=?",
                (new_body, slug)
            )
    conn.commit()


def _seed_templates(conn):
    for t in _TEMPLATE_DEFS:
        conn.execute(
            '''INSERT INTO templates (slug, name, description, subject_template, body_template, fields)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (t['slug'], t['name'], t['description'], t['subject_template'], t['body_template'], t['fields'])
        )
    conn.commit()
