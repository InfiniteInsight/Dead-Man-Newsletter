import hmac
import hashlib


def _make_pixel_token(send_id, recipient_email, secret_key):
    """Generate a 16-char hex HMAC token for the tracking pixel URL."""
    key = secret_key.encode() if isinstance(secret_key, str) else secret_key
    msg = f"{send_id}:{recipient_email}".encode()
    return hmac.new(key, msg, digestmod=hashlib.sha256).hexdigest()[:16]


def build_email(body, settings, unsubscribe_token, send_id, recipient_email,
                secret_key, font=None):
    """
    Compose a complete HTML email document.

    Args:
        body: Rendered HTML body content from the template.
        settings: Dict of app settings (from get_settings()).
        unsubscribe_token: Contact's unsubscribe UUID.
        send_id: Row ID of the sends table entry.
        recipient_email: Recipient's email address (used for HMAC).
        secret_key: App secret key for HMAC generation.
        font: Optional font override. If None, uses settings['default_font'].

    Returns:
        Complete <!DOCTYPE html> string ready to send.
    """
    chosen_font = font or settings.get('default_font', 'Georgia, serif')
    header_url = settings.get('header_image_url', '').strip()
    footer_url = settings.get('footer_image_url', '').strip()
    base_url = settings.get('base_url', '').strip()
    tracking_enabled = settings.get('tracking_pixel_enabled') == '1'

    parts = []

    # Header image
    if header_url:
        parts.append(
            f'<img src="{header_url}" '
            f'style="width:100%;max-width:600px;display:block;" alt="">'
        )

    # Body content
    parts.append(body)

    # Footer image
    if footer_url:
        parts.append(
            f'<img src="{footer_url}" '
            f'style="width:100%;max-width:600px;display:block;" alt="">'
        )

    # Unsubscribe footer (link only works if base_url is configured)
    if base_url:
        unsubscribe_url = f'{base_url}/unsubscribe/{unsubscribe_token}'
        unsub_html = f'<a href="{unsubscribe_url}" style="color:#999;">Unsubscribe</a>'
    else:
        unsub_html = 'Unsubscribe'
    parts.append(
        f'<div style="text-align:center;padding:20px;font-size:12px;color:#999;">'
        f'{unsub_html}'
        f'&nbsp;&middot;&nbsp; Sent by NewsLetterGo'
        f'</div>'
    )

    # Tracking pixel (only if enabled and base_url is set)
    if tracking_enabled and base_url:
        token = _make_pixel_token(send_id, recipient_email, secret_key)
        parts.append(
            f'<img src="{base_url}/track/{send_id}/{token}.gif" '
            f'width="1" height="1" style="display:none;" alt="">'
        )

    content = '\n'.join(parts)

    return f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:20px;background:#f5f5f5;">
  <div style="max-width:600px;margin:0 auto;font-family:{chosen_font};">
    {content}
  </div>
</body>
</html>'''
