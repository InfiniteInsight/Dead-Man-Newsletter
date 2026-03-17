import hashlib
import database as db_module


def test_templates_use_safe_filter_for_textarea_vars(db):
    """All textarea-sourced variables in template bodies must use | safe filter."""
    import json
    templates = db.execute("SELECT slug, body_template, fields FROM templates").fetchall()
    for tpl in templates:
        fields = json.loads(tpl['fields'])
        textarea_fields = [f['name'] for f in fields if f.get('type') == 'textarea']
        body = tpl['body_template']
        for fname in textarea_fields:
            # Variable should be rendered with | safe
            assert f'{{{{{fname} | safe}}}}' in body or f'{{{{{ fname }|safe}}}}' in body or \
                   f'{{{{{fname}|safe}}}}' in body, \
                f"Template '{tpl['slug']}': textarea field '{fname}' missing | safe filter"


def test_migration_does_not_overwrite_customised_templates(db):
    """If a template body has been changed, migration should not overwrite it."""
    db.execute(
        "UPDATE templates SET body_template='CUSTOMISED' WHERE slug='newsletter'"
    )
    db.commit()
    # Re-running init_db should NOT overwrite the customised template
    db_module.init_db()
    row = db.execute(
        "SELECT body_template FROM templates WHERE slug='newsletter'"
    ).fetchone()
    assert row['body_template'] == 'CUSTOMISED'
