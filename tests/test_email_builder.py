import email_builder


BASE_SETTINGS = {
    'base_url': 'https://example.com',
    'header_image_url': '',
    'footer_image_url': '',
    'default_font': 'Georgia, serif',
    'tracking_pixel_enabled': '0',
}


def test_returns_complete_html_document():
    html = email_builder.build_email(
        body='<p>Hello</p>',
        settings=BASE_SETTINGS,
        unsubscribe_token='abc123',
        send_id=1,
        recipient_email='user@example.com',
        secret_key='secret',
    )
    assert html.startswith('<!DOCTYPE html>')
    assert '<p>Hello</p>' in html


def test_applies_font_to_wrapper():
    settings = {**BASE_SETTINGS, 'default_font': 'Arial, sans-serif'}
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    assert 'Arial, sans-serif' in html


def test_font_parameter_overrides_settings():
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=BASE_SETTINGS,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
        font='Verdana, sans-serif',
    )
    assert 'Verdana, sans-serif' in html
    # 'Georgia' now appears in the ql-font CSS block; check the wrapper div uses Verdana, not Georgia
    assert 'font-family:Georgia' not in html.replace(' ', '')


def test_header_image_included_when_set():
    settings = {**BASE_SETTINGS, 'header_image_url': 'https://img.example.com/h.png'}
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    assert 'https://img.example.com/h.png' in html


def test_header_image_omitted_when_blank():
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=BASE_SETTINGS,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    # No img tags other than potentially the pixel
    assert 'header' not in html.lower() or 'img' not in html


def test_footer_image_included_when_set():
    settings = {**BASE_SETTINGS, 'footer_image_url': 'https://img.example.com/f.png'}
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    assert 'https://img.example.com/f.png' in html


def test_unsubscribe_link_always_present():
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=BASE_SETTINGS,
        unsubscribe_token='mytoken123', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    assert '/unsubscribe/mytoken123' in html


def test_tracking_pixel_omitted_when_disabled():
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=BASE_SETTINGS,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    assert '/track/' not in html


def test_tracking_pixel_omitted_when_no_base_url():
    settings = {**BASE_SETTINGS, 'tracking_pixel_enabled': '1', 'base_url': ''}
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    assert '/track/' not in html


def test_tracking_pixel_present_when_enabled_with_base_url():
    settings = {**BASE_SETTINGS, 'tracking_pixel_enabled': '1'}
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=42,
        recipient_email='u@example.com', secret_key='s',
    )
    assert '/track/42/' in html
    assert '.gif' in html


def test_pixel_token_is_16_hex_chars():
    settings = {**BASE_SETTINGS, 'tracking_pixel_enabled': '1'}
    html = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=1,
        recipient_email='u@example.com', secret_key='s',
    )
    import re
    match = re.search(r'/track/1/([0-9a-f]+)\.gif', html)
    assert match, "pixel URL should be in html"
    assert len(match.group(1)) == 16


def test_different_recipients_get_different_pixel_tokens():
    settings = {**BASE_SETTINGS, 'tracking_pixel_enabled': '1'}
    html1 = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=1,
        recipient_email='alice@example.com', secret_key='s',
    )
    html2 = email_builder.build_email(
        body='<p>Hi</p>', settings=settings,
        unsubscribe_token='tok', send_id=1,
        recipient_email='bob@example.com', secret_key='s',
    )
    import re
    t1 = re.search(r'/track/1/([0-9a-f]+)\.gif', html1).group(1)
    t2 = re.search(r'/track/1/([0-9a-f]+)\.gif', html2).group(1)
    assert t1 != t2
