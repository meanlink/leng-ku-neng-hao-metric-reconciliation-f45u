from ..db import db_cursor


def record_action(cur, user_id, action, entity, entity_id=None, detail=""):
    cur.execute("INSERT INTO audit_logs(user_id, action, entity, entity_id, detail) VALUES(%s,%s,%s,%s,%s)",
                (user_id, action, entity, str(entity_id) if entity_id else None, detail[:500]))


def log_action(user_id, action, entity, entity_id=None, detail=""):
    with db_cursor(commit=True) as cur:
        record_action(cur, user_id, action, entity, entity_id, detail)
