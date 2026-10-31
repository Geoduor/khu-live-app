"""
backup.py — off-site backups and frozen season snapshots.

Why: the database is the only live copy of results, agents, tournaments and
history. A nightly copy to a DIFFERENT provider (any S3-compatible bucket:
Cloudflare R2, Backblaze B2, AWS S3) protects against a paused/deleted
database, a bad deploy or a hijacked account. Turn on bucket versioning /
object lock there so old copies cannot be overwritten or deleted.

Configure with environment variables (all optional — nothing runs without them):
  BACKUP_S3_ENDPOINT   e.g. https://<account>.r2.cloudflarestorage.com
  BACKUP_S3_BUCKET     bucket name
  BACKUP_S3_KEY_ID     access key id (give it WRITE-ONLY permission if you can)
  BACKUP_S3_SECRET     secret access key
  BACKUP_S3_PREFIX     folder inside the bucket (default "khu-backups")
"""
import json
import logging
import os
from datetime import datetime, timezone

import database as db

logger = logging.getLogger(__name__)

_last = {"time": None, "ok": None, "detail": "No backup has run since the server started."}


def is_configured() -> bool:
    return all(os.environ.get(k, "").strip() for k in
               ("BACKUP_S3_ENDPOINT", "BACKUP_S3_BUCKET", "BACKUP_S3_KEY_ID", "BACKUP_S3_SECRET"))


def build_backup() -> dict:
    """Same shape as the admin page's 'Download backup' (restorable with
    /api/admin/restore), plus finished season snapshots."""
    db.init_tournament_tables()
    return {
        "agents": db.export_agents_raw(),
        "results": db.load_manual_results(),
        "stats": db.load_team_stats(),
        "players": db.load_player_stats(),
        "tournaments": db.load_tournaments(),
        "matches": db.load_tournament_matches(),
        "seasons": db.load_season_snapshots(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def upload_backup() -> dict:
    """Build a backup and store it under a dated key. Never deletes anything."""
    if not is_configured():
        raise RuntimeError("Off-site backup is not configured (BACKUP_S3_* variables missing).")
    import boto3  # imported here so the app still starts if it is not installed
    from botocore.config import Config

    body = json.dumps(build_backup(), ensure_ascii=False).encode("utf-8")
    now = datetime.now(timezone.utc)
    prefix = os.environ.get("BACKUP_S3_PREFIX", "khu-backups").strip("/ ")
    key = f"{prefix}/{now:%Y}/{now:%m}/khu-backup-{now:%Y-%m-%dT%H%M%SZ}.json"
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["BACKUP_S3_ENDPOINT"].strip(),
        aws_access_key_id=os.environ["BACKUP_S3_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["BACKUP_S3_SECRET"].strip(),
        region_name=os.environ.get("BACKUP_S3_REGION", "auto"),
        config=Config(retries={"max_attempts": 3}, connect_timeout=10, read_timeout=30),
    )
    s3.put_object(Bucket=os.environ["BACKUP_S3_BUCKET"].strip(), Key=key, Body=body,
                  ContentType="application/json")
    return {"key": key, "bytes": len(body)}


def run_scheduled_backup():
    """Called by the scheduler. Never raises — a failed backup must not take the app down."""
    if not is_configured():
        return
    try:
        info = upload_backup()
        _last.update(time=datetime.now(timezone.utc).isoformat(), ok=True,
                     detail=f"Saved {info['key']} ({info['bytes']} bytes).")
        logger.info(f"Off-site backup saved: {info['key']}")
    except Exception as e:  # noqa: BLE001
        _last.update(time=datetime.now(timezone.utc).isoformat(), ok=False,
                     detail=f"Backup failed: {type(e).__name__}")
        logger.error(f"Off-site backup failed: {type(e).__name__}: {e}")


def status() -> dict:
    return {"configured": is_configured(), **_last}
