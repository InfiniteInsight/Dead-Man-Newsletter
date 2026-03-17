import json
from unittest.mock import patch, call


def _seed_template_and_contact(db):
    db.execute(
        "INSERT INTO templates (slug, name, subject_template, body_template, fields) "
        "VALUES ('test-tpl', 'Test', '{{title}}', '<p>{{body}}</p>', ?)",
        (json.dumps([
            {'name': 'title', 'label': 'Title', 'type': 'text'},
            {'name': 'body',  'label': 'Body',  'type': 'textarea'},
        ]),)
    )
    db.execute(
        "INSERT INTO contacts (email, name, groups, unsubscribe_token) "
        "VALUES ('alice@example.com', 'Alice', '[]', 'alicetoken123456')"
    )
    db.commit()


def test_send_creates_sends_row(client, db):
    _seed_template_and_contact(db)
    with patch('app.send_email'):
        client.post('/templates/test-tpl/send', data={
            'title': 'Hello', 'body': 'World', 'target_group': 'all',
        })
    count = db.execute("SELECT COUNT(*) FROM sends").fetchone()[0]
    assert count == 1


def test_send_inserts_sends_row_before_sending(client, db):
    """send_id must exist before email is built (needed for pixel URL)."""
    _seed_template_and_contact(db)
    captured_send_ids = []

    def mock_send(email, name, subject, body):
        # At the time send_email is called, the sends row should exist
        import database as db_module
        conn = db_module.get_db()
        rows = conn.execute("SELECT id FROM sends").fetchall()
        captured_send_ids.extend([r['id'] for r in rows])
        conn.close()

    with patch('app.send_email', side_effect=mock_send):
        client.post('/templates/test-tpl/send', data={
            'title': 'Hello', 'body': 'World', 'target_group': 'all',
        })

    assert len(captured_send_ids) > 0, "sends row should exist when send_email is called"


def test_send_updates_recipient_count(client, db):
    _seed_template_and_contact(db)
    with patch('app.send_email'):
        client.post('/templates/test-tpl/send', data={
            'title': 'Hello', 'body': 'World', 'target_group': 'all',
        })
    row = db.execute("SELECT recipient_count FROM sends").fetchone()
    assert row['recipient_count'] == 1


def test_send_uses_email_builder_output(client, db):
    _seed_template_and_contact(db)
    sent_bodies = []

    def mock_send(email, name, subject, body):
        sent_bodies.append(body)

    with patch('app.send_email', side_effect=mock_send):
        client.post('/templates/test-tpl/send', data={
            'title': 'Hello', 'body': 'World', 'target_group': 'all',
        })

    assert len(sent_bodies) == 1
    assert '<!DOCTYPE html>' in sent_bodies[0]
    assert '/unsubscribe/alicetoken123456' in sent_bodies[0]


def test_test_send_to_single_address(client, db):
    _seed_template_and_contact(db)
    with patch('app.send_email') as mock_send:
        resp = client.post('/templates/test-tpl/send', data={
            'title': 'Hello', 'body': 'World',
            'test_email': 'test@example.com',
        }, follow_redirects=True)
    assert resp.status_code == 200
    mock_send.assert_called_once()
    args = mock_send.call_args[0]
    assert args[0] == 'test@example.com'
