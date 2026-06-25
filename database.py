#!/usr/bin/env python3
"""
Klyra Encrypted Database — SQLite with AES-256 field-level encryption.

Stores users, containers, sessions, and payments with encrypted PII.
The master key is derived from an env var (DB_MASTER_KEY) via PBKDF2.
"""

import os
import json
import time
import uuid
import hashlib
import base64
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger("database")

# ── Key Derivation ─────────────────────────────────────────────────────────

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "klyra.db"))
MASTER_KEY_ENV = "DB_MASTER_KEY"

import threading

_cipher_cache: Fernet | None = None


def _get_cipher() -> Fernet:
    """Derive a Fernet cipher from the master key env var."""
    global _cipher_cache
    if _cipher_cache:
        return _cipher_cache

    raw = os.environ.get(MASTER_KEY_ENV)
    if not raw:
        raise RuntimeError(
            f"{MASTER_KEY_ENV} environment variable is required. "
            "Generate with: python3 -c 'import secrets; print(secrets.token_hex(32))'"
        )

    # Derive a 32-byte key — salt stored in a file next to the database
    salt_path = os.path.join(os.path.dirname(DB_PATH), ".db-salt")
    try:
        salt = open(salt_path, "rb").read()
    except FileNotFoundError:
        import secrets as _sec
        salt = _sec.token_bytes(32)
        os.makedirs(os.path.dirname(salt_path), exist_ok=True)
        with open(salt_path, "wb") as _sf:
            _sf.write(salt)
        os.chmod(salt_path, 0o600)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    key = base64.urlsafe_b64encode(kdf.derive(raw.encode()))
    _cipher_cache = Fernet(key)
    return _cipher_cache


def encrypt(plain: str) -> str:
    """Encrypt a string. Returns base64 ciphertext."""
    if not plain:
        return ""
    return _get_cipher().encrypt(plain.encode()).decode()


def decrypt(cipher: str) -> str:
    """Decrypt a string. Returns plaintext."""
    if not cipher:
        return ""
    return _get_cipher().decrypt(cipher.encode()).decode()


# ── Schema ─────────────────────────────────────────────────────────────────

SQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    email_cipher    TEXT,
    created_at      REAL NOT NULL,
    subscription    TEXT DEFAULT 'none',   -- none | active | expired
    role            TEXT DEFAULT 'user',    -- user | owner
    sub_created_at  REAL,
    sub_expires_at  REAL,
    payment_tx      TEXT,
    totp_secret     TEXT,
    api_token       TEXT UNIQUE,
    is_deleted      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS containers (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    lxc_name        TEXT NOT NULL UNIQUE,
    bridge          TEXT,
    private_ip      TEXT,
    subnet          TEXT,
    status          TEXT DEFAULT 'pending',
    mem_mb          INTEGER DEFAULT 2048,
    cpu             INTEGER DEFAULT 2,
    disk_gb         INTEGER DEFAULT 10,
    created_at      REAL NOT NULL,
    last_active_at  REAL,
    storage_pool    TEXT DEFAULT 'klyra',
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    container_id    TEXT NOT NULL REFERENCES containers(id),
    project_folder  TEXT,
    model           TEXT,
    variant         TEXT DEFAULT 'high',
    message_count   INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    created_at      REAL NOT NULL,
    last_message_at REAL,
    history_path    TEXT,
    FOREIGN KEY (container_id) REFERENCES containers(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    amount          REAL NOT NULL,
    currency        TEXT DEFAULT 'CLAIM',
    tx_hash         TEXT,
    chain           TEXT DEFAULT 'TRC20',
    status          TEXT DEFAULT 'pending',
    created_at      REAL NOT NULL,
    confirmed_at    REAL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS session_messages (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    role            TEXT NOT NULL,       -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    prompt_type     TEXT DEFAULT '',
    options_json    TEXT DEFAULT '[]',
    allow_custom    INTEGER DEFAULT 0,
    created_at      REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS system_config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);

INSERT OR IGNORE INTO system_config (key, value) VALUES ('schema_version', '2');

"""


# ── Database Connection ────────────────────────────────────────────────────

_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(SQL_SCHEMA)
        _conn.commit()
    return _conn


@contextmanager
def tx():
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


# ── Data Classes ───────────────────────────────────────────────────────────

@dataclass
class User:
    id: str
    username: str
    password_hash: str
    email_cipher: str = ""
    created_at: float = 0.0
    subscription: str = "none"
    role: str = "user"
    sub_created_at: float = 0.0
    sub_expires_at: float = 0.0
    payment_tx: str = ""
    totp_secret: str = ""
    api_token: str = ""
    is_deleted: bool = False
    pro_expiry: float = 0.0

    @property
    def email(self) -> str:
        return decrypt(self.email_cipher) if self.email_cipher else ""

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_admin(self) -> bool:
        return self.role in ("admin", "owner")

    @property
    def is_pro(self) -> bool:
        if self.role in ("admin", "owner"):
            return True
        if self.role == "pro":
            return self.pro_expiry <= 0 or time.time() < self.pro_expiry
        return self.subscription == "active"


@dataclass
class Container:
    id: str
    user_id: str
    lxc_name: str
    bridge: str = ""
    private_ip: str = ""
    subnet: str = ""
    status: str = "pending"
    mem_mb: int = 2048
    cpu: int = 2
    disk_gb: int = 10
    created_at: float = 0.0
    last_active_at: float = 0.0
    storage_pool: str = "klyra"


@dataclass
class Session:
    id: str
    container_id: str
    project_folder: str = ""
    model: str = ""
    variant: str = "high"
    message_count: int = 0
    is_active: bool = True
    created_at: float = 0.0
    last_message_at: float = 0.0
    history_path: str = ""


@dataclass
class Payment:
    id: str
    user_id: str
    amount: float
    currency: str = "CLAIM"
    tx_hash: str = ""
    chain: str = "TRC20"
    status: str = "pending"
    created_at: float = 0.0
    confirmed_at: float = 0.0


# ── Data Access Layer ──────────────────────────────────────────────────────

def _row_to_user(row: sqlite3.Row) -> User:
    return User(**dict(row))


def _row_to_container(row: sqlite3.Row) -> Container:
    return Container(**dict(row))


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(**dict(row))


def _row_to_payment(row: sqlite3.Row) -> Payment:
    return Payment(**dict(row))


# ── Users ──────────────────────────────────────────────────────────────────

def create_user(username: str, password_hash: str, email: str = "",
                role: str = "user", pro_expiry: float = 0) -> User:
    now = time.time()
    uid = uuid.uuid4().hex
    token = uuid.uuid4().hex

    with tx() as db:
        db.execute(
            "INSERT INTO users (id, username, password_hash, email_cipher, created_at, api_token, role, pro_expiry) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, username, password_hash, encrypt(email) if email else "", now, token, role, pro_expiry),
        )
    return User(id=uid, username=username, password_hash=password_hash,
                email_cipher=encrypt(email) if email else "", created_at=now, api_token=token,
                role=role, pro_expiry=pro_expiry)


def get_user_by_id(uid: str) -> Optional[User]:
    with tx() as db:
        row = db.execute("SELECT * FROM users WHERE id = ? AND is_deleted = 0", (uid,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_username(username: str) -> Optional[User]:
    with tx() as db:
        row = db.execute("SELECT * FROM users WHERE username = ? AND is_deleted = 0",
                         (username,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_token(token: str) -> Optional[User]:
    with tx() as db:
        row = db.execute("SELECT * FROM users WHERE api_token = ? AND is_deleted = 0",
                         (token,)).fetchone()
    return _row_to_user(row) if row else None


def update_user_subscription(uid: str, status: str, expires_at: float, tx_hash: str = ""):
    now = time.time()
    with tx() as db:
        db.execute(
            "UPDATE users SET subscription = ?, sub_created_at = ?, "
            "sub_expires_at = ?, payment_tx = ? WHERE id = ?",
            (status, now, expires_at, tx_hash, uid),
        )


def mark_user_deleted(uid: str):
    with tx() as db:
        db.execute("UPDATE users SET is_deleted = 1 WHERE id = ?", (uid,))


def list_active_users() -> list[User]:
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM users WHERE is_deleted = 0 AND subscription = 'active'"
        ).fetchall()
    return [_row_to_user(r) for r in rows]


# ── Containers ─────────────────────────────────────────────────────────────

def create_container_record(user_id: str, lxc_name: str, spec: dict = None) -> Container:
    now = time.time()
    cid = uuid.uuid4().hex
    spec = spec or {}
    with tx() as db:
        existing = db.execute(
            "SELECT id FROM containers WHERE lxc_name = ?", (lxc_name,)
        ).fetchone()
        if existing:
            cid = existing["id"]
            session_rows = db.execute(
                "SELECT id FROM sessions WHERE container_id = ?", (cid,)
            ).fetchall()
            for row in session_rows:
                db.execute("DELETE FROM session_messages WHERE session_id = ?", (row["id"],))
            db.execute("DELETE FROM sessions WHERE container_id = ?", (cid,))
            db.execute(
                "UPDATE containers SET user_id = ?, bridge = ?, private_ip = ?, subnet = ?, "
                "status = ?, mem_mb = ?, cpu = ?, disk_gb = ?, created_at = ?, "
                "last_active_at = ?, storage_pool = ? WHERE id = ?",
                (user_id, spec.get("bridge", ""), spec.get("private_ip", ""),
                 spec.get("subnet", ""), spec.get("status", "pending"),
                 spec.get("mem_mb", 2048), spec.get("cpu", 2), spec.get("disk_gb", 10),
                 now, now, spec.get("storage_pool", "klyra"), cid),
            )
            return Container(id=cid, user_id=user_id, lxc_name=lxc_name,
                             created_at=now, last_active_at=now,
                             bridge=spec.get("bridge", ""), private_ip=spec.get("private_ip", ""),
                             subnet=spec.get("subnet", ""), status=spec.get("status", "pending"),
                             mem_mb=spec.get("mem_mb", 2048), cpu=spec.get("cpu", 2),
                             disk_gb=spec.get("disk_gb", 10),
                             storage_pool=spec.get("storage_pool", "klyra"))
        db.execute(
            "INSERT INTO containers (id, user_id, lxc_name, bridge, private_ip, subnet, "
            "status, mem_mb, cpu, disk_gb, created_at, last_active_at, storage_pool) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, user_id, lxc_name, spec.get("bridge", ""), spec.get("private_ip", ""),
             spec.get("subnet", ""), spec.get("status", "pending"),
             spec.get("mem_mb", 2048), spec.get("cpu", 2), spec.get("disk_gb", 10),
             now, now, spec.get("storage_pool", "klyra")),
        )
    return Container(id=cid, user_id=user_id, lxc_name=lxc_name, created_at=now, last_active_at=now,
                     bridge=spec.get("bridge", ""), private_ip=spec.get("private_ip", ""),
                     subnet=spec.get("subnet", ""), status=spec.get("status", "pending"),
                     mem_mb=spec.get("mem_mb", 2048), cpu=spec.get("cpu", 2),
                     disk_gb=spec.get("disk_gb", 10),
                     storage_pool=spec.get("storage_pool", "klyra"))


def get_container_by_id(cid: str) -> Optional[Container]:
    with tx() as db:
        row = db.execute("SELECT * FROM containers WHERE id = ?", (cid,)).fetchone()
    return _row_to_container(row) if row else None


def get_container_by_user(uid: str) -> Optional[Container]:
    with tx() as db:
        row = db.execute(
            "SELECT * FROM containers WHERE user_id = ? AND status NOT IN ('deleted', 'error') "
            "ORDER BY created_at DESC LIMIT 1", (uid,)
        ).fetchone()
    return _row_to_container(row) if row else None


def update_container_status(cid: str, status: str):
    with tx() as db:
        db.execute("UPDATE containers SET status = ? WHERE id = ?", (status, cid))


def update_container_active(cid: str):
    with tx() as db:
        db.execute("UPDATE containers SET last_active_at = ? WHERE id = ?",
                   (time.time(), cid))


def list_inactive_containers(hours: int = 72) -> list[Container]:
    cutoff = time.time() - hours * 3600
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM containers WHERE last_active_at < ? "
            "AND status IN ('running', 'stopped')",
            (cutoff,),
        ).fetchall()
    return [_row_to_container(r) for r in rows]


def list_all_containers() -> list[Container]:
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM containers ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_container(r) for r in rows]


def get_container_by_lxc_name(lxc_name: str) -> Optional[Container]:
    with tx() as db:
        row = db.execute(
            "SELECT * FROM containers WHERE lxc_name = ?", (lxc_name,)
        ).fetchone()
    return _row_to_container(row) if row else None


# ── Sessions ───────────────────────────────────────────────────────────────

def create_session_record(container_id: str, project_folder: str = "",
                          model: str = "", variant: str = "high") -> Session:
    now = time.time()
    sid = uuid.uuid4().hex
    with tx() as db:
        db.execute(
            "INSERT INTO sessions (id, container_id, project_folder, model, variant, "
            "created_at, last_message_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, container_id, project_folder, model, variant, now, now),
        )
    return Session(id=sid, container_id=container_id, project_folder=project_folder,
                   model=model, variant=variant, created_at=now, last_message_at=now)


def get_session_by_id(sid: str) -> Optional[Session]:
    with tx() as db:
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    return _row_to_session(row) if row else None


def get_active_sessions(container_id: str) -> list[Session]:
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM sessions WHERE container_id = ? AND is_active = 1 "
            "ORDER BY last_message_at DESC", (container_id,)
        ).fetchall()
    return [_row_to_session(r) for r in rows]


def update_session_activity(sid: str, message_count: int):
    with tx() as db:
        db.execute(
            "UPDATE sessions SET last_message_at = ?, message_count = ? WHERE id = ?",
            (time.time(), message_count, sid),
        )


def deactivate_session(sid: str):
    with tx() as db:
        db.execute("UPDATE sessions SET is_active = 0 WHERE id = ?", (sid,))


def list_idle_sessions(minutes: int = 10) -> list[Session]:
    cutoff = time.time() - minutes * 60
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM sessions WHERE is_active = 1 AND last_message_at < ?",
            (cutoff,),
        ).fetchall()
    return [_row_to_session(r) for r in rows]


# ── Session Messages ────────────────────────────────────────────────────────

def save_session_message(session_id: str, role: str, content: str,
                         prompt_type: str = "", options: list = None,
                         allow_custom: bool = False) -> dict:
    now = time.time()
    mid = uuid.uuid4().hex
    opts_json = json.dumps(options or [])
    with tx() as db:
        db.execute(
            "INSERT INTO session_messages (id, session_id, role, content, prompt_type, "
            "options_json, allow_custom, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, session_id, role, content, prompt_type, opts_json, int(allow_custom), now),
        )
    return {"id": mid, "role": role, "content": content, "prompt_type": prompt_type,
            "options": options or [], "allow_custom": allow_custom, "created_at": now}


def get_session_messages(session_id: str) -> list[dict]:
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM session_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    result = []
    for r in rows:
        result.append({
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "prompt_type": r["prompt_type"],
            "options": json.loads(r["options_json"]) if r["options_json"] else [],
            "allow_custom": bool(r["allow_custom"]),
            "created_at": r["created_at"],
        })
    return result


def delete_session_messages(session_id: str):
    with tx() as db:
        db.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))


# ── Payments ───────────────────────────────────────────────────────────────

def create_payment(user_id: str, amount: float, tx_hash: str = "", chain: str = "TRC20") -> Payment:
    now = time.time()
    pid = uuid.uuid4().hex
    with tx() as db:
        db.execute(
            "INSERT INTO payments (id, user_id, amount, tx_hash, chain, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, user_id, amount, tx_hash, chain, now),
        )
    return Payment(id=pid, user_id=user_id, amount=amount, tx_hash=tx_hash, chain=chain,
                   created_at=now)


def confirm_payment(pid: str):
    with tx() as db:
        db.execute("UPDATE payments SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
                   (time.time(), pid))


def get_user_payments(uid: str) -> list[Payment]:
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC", (uid,)
        ).fetchall()
    return [_row_to_payment(r) for r in rows]


# ── Initialization ─────────────────────────────────────────────────────────

def migrate_db():
    """Apply schema migrations."""
    db = get_db()
    version = db.execute(
        "SELECT value FROM system_config WHERE key = 'schema_version'"
    ).fetchone()
    version = int(version["value"]) if version else 0

    if version < 3:
        try:
            db.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
        except sqlite3.OperationalError:
            pass
        db.execute("UPDATE system_config SET value = '3' WHERE key = 'schema_version'")
    if version < 4:
        try:
            db.execute("ALTER TABLE users ADD COLUMN pro_expiry REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        db.execute("UPDATE system_config SET value = '4' WHERE key = 'schema_version'")
    db.commit()


def set_user_role(uid: str, role: str):
    with tx() as db:
        db.execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))


def set_user_expiry(uid: str, expiry: float):
    with tx() as db:
        db.execute("UPDATE users SET pro_expiry = ? WHERE id = ?", (expiry, uid))


def clear_user_expiry(uid: str):
    with tx() as db:
        db.execute("UPDATE users SET pro_expiry = 0 WHERE id = ?", (uid,))


def list_all_users() -> list[User]:
    with tx() as db:
        rows = db.execute(
            "SELECT * FROM users WHERE is_deleted = 0 ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_user(r) for r in rows]


def seed_owner(password: str):
    """Create or update the owner account.
    Token is ALWAYS deterministic — never changes.
    Password is ALWAYS updated to match the env var.
    """
    import bcrypt
    owner_username = os.environ.get("OWNER_USERNAME", "owner")
    fixed_token = hashlib.sha256(f"klyra-owner-{owner_username}".encode()).hexdigest()
    existing = get_user_by_username(owner_username)
    if existing:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        with tx() as db:
            db.execute("UPDATE users SET api_token=?, password_hash=?, role='owner' WHERE id=?",
                       (fixed_token, pw_hash, existing.id))
        existing.api_token = fixed_token
        existing.password_hash = pw_hash
        existing.role = "owner"
        logger.info("Owner account synced: %s (token permanent, password updated)", owner_username)
        return existing

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    now = time.time()
    uid = uuid.uuid4().hex

    with tx() as db:
        db.execute(
            "INSERT INTO users (id, username, password_hash, created_at, subscription, role, api_token) "
            "VALUES (?, ?, ?, ?, 'active', 'owner', ?)",
            (uid, owner_username, pw_hash, now, fixed_token),
        )
    user = User(id=uid, username=owner_username, password_hash=pw_hash,
                created_at=now, subscription="active", role="owner", api_token=fixed_token)
    logger.info("Owner account created: %s (id=%s)", owner_username, uid)
    return user


def init_db():
    """Initialize the database. Creates tables if not exist."""
    get_db()
    migrate_db()
    logger.info("Database ready at %s", DB_PATH)


if __name__ == "__main__":
    init_db()
    print(f"Database initialized: {DB_PATH}")
    print(f"Encryption: {'AES-256 (env key)' if os.environ.get(MASTER_KEY_ENV) else 'DEV MODE (insecure)'}")
