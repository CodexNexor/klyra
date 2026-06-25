#!/usr/bin/env python3
"""
Klyra Controller Daemon — Manages container lifecycle, idle timeouts, and payment expiry.

Runs in the background and handles:
  - 10 min idle → close OpenCode session (deactivate)
  - 3 days idle → delete entire container + storage + sessions
  - 3 days after subscription expiry → delete container
  - 30 days after subscription expiry → delete account
"""

import os
import sys
import time
import json
import signal
import logging
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    get_db, tx, init_db,
    list_idle_sessions, deactivate_session,
    list_inactive_containers, update_container_status, mark_user_deleted,
    get_user_by_id, get_container_by_user, get_container_by_id,
    delete_session_messages,
)
from isolation import delete_container as delete_lxc_container, ContainerSpec

logger = logging.getLogger("controller")

SLEEP_INTERVAL = 60
SESSION_IDLE_MINUTES = 10
CONTAINER_IDLE_HOURS = 72
PAYMENT_GRACE_DAYS = 3
ACCOUNT_DELETE_DAYS = 30

RUNNING = True


def cleanup_idle_sessions():
    sessions = list_idle_sessions(minutes=SESSION_IDLE_MINUTES)
    for s in sessions:
        logger.info("Closing idle session %s (idle > %d min)", s.id, SESSION_IDLE_MINUTES)
        deactivate_session(s.id)


def _delete_lxc_container(c):
    spec = ContainerSpec(
        user_id=0, username="controller",
        lxc_name=c.lxc_name, bridge=c.bridge or "",
        private_ip=c.private_ip or "", subnet=c.subnet or "",
        status=c.status,
    )
    try:
        delete_lxc_container(spec)
    except Exception as e:
        logger.error("Failed to delete container %s: %s", c.lxc_name, e)
    update_container_status(c.id, "deleted")


def cleanup_idle_containers():
    containers = list_inactive_containers(hours=CONTAINER_IDLE_HOURS)
    for c in containers:
        if c.status in ("deleted", "error"):
            continue
        logger.warning("Container %s deleted (inactive > %d hours)", c.lxc_name, CONTAINER_IDLE_HOURS)
        _delete_lxc_container(c)


def check_payment_expiry():
    """Mark users as expired after 3-day grace, deleting their container."""
    now = time.time()
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM users WHERE is_deleted = 0 AND subscription = 'active' "
            "AND sub_expires_at < ?",
            (now - PAYMENT_GRACE_DAYS * 86400,),
        ).fetchall()
        for row in rows:
            uid = row["id"]
            logger.warning("Subscription expired for user %s (grace period over)", uid)
            db.execute("UPDATE users SET subscription = 'expired' WHERE id = ?", (uid,))

    # Delete containers of expired users
    with tx() as db:
        expired_users = db.execute(
            "SELECT * FROM users WHERE is_deleted = 0 AND subscription = 'expired'"
        ).fetchall()

    for row in expired_users:
        uid = row["id"]
        container = get_container_by_user(uid)
        if container and container.status not in ("deleted", "error"):
            logger.warning("Deleting container for expired user %s", uid)
            _delete_lxc_container(container)
            # Delete their session messages
            with tx() as db:
                sessions = db.execute(
                    "SELECT id FROM sessions WHERE container_id = ?", (container.id,)
                ).fetchall()
                for s in sessions:
                    delete_session_messages(s["id"])
                db.execute(
                    "UPDATE sessions SET is_active = 0 WHERE container_id = ?",
                    (container.id,),
                )


def cleanup_expired_accounts():
    now = time.time()
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM users WHERE is_deleted = 0 AND subscription = 'expired' "
            "AND sub_expires_at < ?",
            (now - ACCOUNT_DELETE_DAYS * 86400,),
        ).fetchall()
        for row in rows:
            uid = row["id"]
            logger.warning("Deleting expired account %s (no payment > %d days)", uid, ACCOUNT_DELETE_DAYS)
            mark_user_deleted(uid)


def main_loop():
    signal.signal(signal.SIGTERM, lambda *a: setattr(sys.modules[__name__], 'RUNNING', False))
    signal.signal(signal.SIGINT, lambda *a: setattr(sys.modules[__name__], 'RUNNING', False))

    logger.info("Controller daemon started (check interval: %ds)", SLEEP_INTERVAL)
    logger.info("  Session idle timeout: %d min", SESSION_IDLE_MINUTES)
    logger.info("  Container idle timeout: %d hours", CONTAINER_IDLE_HOURS)
    logger.info("  Payment grace: %d days", PAYMENT_GRACE_DAYS)
    logger.info("  Account delete after: %d days expired", ACCOUNT_DELETE_DAYS)

    while RUNNING:
        try:
            cleanup_idle_sessions()
            check_payment_expiry()
            cleanup_idle_containers()
            cleanup_expired_accounts()
        except Exception as e:
            logger.error("Controller error: %s", e, exc_info=True)

        time.sleep(SLEEP_INTERVAL)

    logger.info("Controller daemon stopped.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("/tmp/klyra-controller.log"),
        ],
    )

    init_db()

    if "--once" in sys.argv:
        cleanup_idle_sessions()
        check_payment_expiry()
        cleanup_idle_containers()
        cleanup_expired_accounts()
        print("One-time cleanup complete.")
    else:
        main_loop()
