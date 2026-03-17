import json


def _seed_send(db):
    """Insert a template and a send row, return send_id."""
    db.execute(
        "INSERT INTO templates (slug, name, subject_template, body_template, fields) "
        "VALUES ('test', 'Test', 'subj', '<p>body</p>', '[]')"
    )
    db.execute(
        "INSERT INTO sends (template_id, subject, body, recipient_count, open_count) "
        "VALUES (1, 'subj', '<p>body</p>', 1, 0)"
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_pixel_returns_gif(client, db):
    send_id = _seed_send(db)
    resp = client.get(f'/track/{send_id}/abcd1234abcd1234.gif')
    assert resp.status_code == 200
    assert resp.content_type == 'image/gif'


def test_pixel_increments_open_count(client, db):
    send_id = _seed_send(db)
    client.get(f'/track/{send_id}/abcd1234abcd1234.gif')
    count = db.execute(
        "SELECT open_count FROM sends WHERE id=?", (send_id,)
    ).fetchone()['open_count']
    assert count == 1


def test_pixel_unknown_send_id_still_returns_gif(client):
    resp = client.get('/track/99999/abcd1234abcd1234.gif')
    assert resp.status_code == 200
    assert resp.content_type == 'image/gif'


def test_pixel_invalid_token_format_still_returns_gif(client, db):
    send_id = _seed_send(db)
    resp = client.get(f'/track/{send_id}/not-valid-token.gif')
    assert resp.status_code == 200
    assert resp.content_type == 'image/gif'


def test_history_page_shows_open_count(client, db):
    send_id = _seed_send(db)
    db.execute("UPDATE sends SET open_count=7 WHERE id=?", (send_id,))
    db.commit()
    resp = client.get('/history')
    assert b'7' in resp.data
