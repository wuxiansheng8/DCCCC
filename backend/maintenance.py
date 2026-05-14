from datetime import datetime, timedelta

import models

LOG_RETENTION_HOURS = 24
FORWARDED_MESSAGE_RETENTION_HOURS = 1


def prune_old_logs(db) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=LOG_RETENTION_HOURS)
    deleted = db.query(models.SystemLog).filter(models.SystemLog.created_at < cutoff).delete()
    db.commit()
    return deleted


def prune_old_forwarded_messages(db) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=FORWARDED_MESSAGE_RETENTION_HOURS)
    deleted = db.query(models.ForwardedMessage).filter(models.ForwardedMessage.created_at < cutoff).delete()
    db.commit()
    return deleted
