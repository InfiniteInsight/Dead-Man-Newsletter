def _add_contact(db, email, token):
    db.execute(
        "INSERT INTO contacts (email, name, groups, unsubscribe_token) "
        "VALUES (?, '', '[]', ?)",
        (email, token)
    )
    db.commit()


def test_valid_token_unsubscribes_contact(client, db):
    _add_contact(db, 'user@example.com', 'validtoken123abc')
    client.get('/unsubscribe/validtoken123abc')
    row = db.execute(
        "SELECT unsubscribed FROM contacts WHERE email='user@example.com'"
    ).fetchone()
    assert row['unsubscribed'] == 1


def test_valid_token_returns_200(client, db):
    _add_contact(db, 'user2@example.com', 'anothertoken456')
    resp = client.get('/unsubscribe/anothertoken456')
    assert resp.status_code == 200


def test_invalid_token_returns_200_no_error(client):
    resp = client.get('/unsubscribe/doesnotexist')
    assert resp.status_code == 200


def test_confirmation_page_contains_message(client, db):
    _add_contact(db, 'user3@example.com', 'confirmtoken789')
    resp = client.get('/unsubscribe/confirmtoken789')
    assert b"unsubscribed" in resp.data.lower()


def test_invalid_token_does_not_leak_info(client):
    resp = client.get('/unsubscribe/doesnotexist')
    # Should render the same confirmation page, not a 404 or error
    assert b"unsubscribed" in resp.data.lower()
