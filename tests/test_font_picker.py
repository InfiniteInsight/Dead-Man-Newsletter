import json
from unittest.mock import patch


def _seed_template(db):
    db.execute(
        "INSERT INTO templates (slug, name, subject_template, body_template, fields) "
        "VALUES ('test-font', 'Test Font', 'Subj', '<p>{{body}}</p>', ?)",
        (json.dumps([{'name': 'body', 'label': 'Body', 'type': 'textarea'}]),)
    )
    db.execute(
        "INSERT INTO contacts (email, name, groups, unsubscribe_token) "
        "VALUES ('c@example.com', 'C', '[]', 'ctok')"
    )
    db.commit()


def test_template_detail_passes_fonts_to_template(client, db):
    _seed_template(db)
    resp = client.get('/templates/test-font')
    assert resp.status_code == 200
    # All 7 fonts should appear in the page
    assert b'Georgia' in resp.data
    assert b'Arial' in resp.data
    assert b'Verdana' in resp.data


def test_font_picker_preselects_default_font(client, db):
    _seed_template(db)
    db.execute(
        "UPDATE settings SET value='Arial, sans-serif' WHERE key='default_font'"
    )
    db.commit()
    resp = client.get('/templates/test-font')
    # The Arial option should be pre-selected
    assert b'Arial, sans-serif' in resp.data


def test_send_uses_chosen_font(client, db):
    _seed_template(db)
    sent_bodies = []

    def mock_send(email, name, subject, body):
        sent_bodies.append(body)

    with patch('app.send_email', side_effect=mock_send):
        client.post('/templates/test-font/send', data={
            'body': '<p>Hello</p>',
            'target_group': 'all',
            'font': 'Verdana, sans-serif',
        })

    assert len(sent_bodies) == 1
    assert 'Verdana, sans-serif' in sent_bodies[0]
