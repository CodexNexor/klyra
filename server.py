#!/usr/bin/env python3
"""
Klyra API Server — Full HTTP API with auth, container lifecycle, session proxy.

Endpoints:
  POST /api/register          — Create account
  POST /api/login             — Authenticate, get token
  POST /api/provision         — Create isolated LXC container
  POST /api/chat              — Send message to OpenCode (runs inside container)
  GET  /api/sessions          — List active sessions
  POST /api/payment/verify    — Record an access activation claim
  GET  /api/user              — Get user info
  GET  /api/status            — Health check
"""

import sys
import os
import json
import time
import uuid
import html
import logging
import shlex
import threading
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel, Field
import uvicorn
import bcrypt

from database import (
    init_db, create_user, get_user_by_username, get_user_by_token,
    get_user_by_id, get_container_by_user, get_container_by_id,
    create_container_record, update_container_status, update_container_active,
    create_session_record, get_session_by_id, get_active_sessions,
    update_session_activity, create_payment, confirm_payment, get_user_payments,
    save_session_message, get_session_messages, delete_session_messages,
    set_user_role, seed_owner, set_user_expiry, clear_user_expiry,
    list_all_users, list_all_containers, get_container_by_lxc_name,
    create_user as db_create_user,
    Container, User,
)
from isolation import (
    ContainerSpec, create_container as lxc_create,
    start_container as lxc_start,
    stop_container as lxc_stop,
    delete_container as lxc_delete,
    exec_in_container, container_running,
)

# ── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "logs", "server.log"
        )),
    ],
)
logger = logging.getLogger("server")

# ── App ────────────────────────────────────────────────────────────────────

_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-XSS-Protection": "1; mode=block",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

app = FastAPI(title="Klyra API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    for h, v in _SECURITY_HEADERS.items():
        response.headers[h] = v
    return response


# Simple IP-based rate limiter
_rate_limit_store: dict[str, list[float]] = {}

def _check_rate_limit(ip: str, max_reqs: int = 30, window: int = 60):
    now = time.time()
    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = []
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < window]
    if len(_rate_limit_store[ip]) >= max_reqs:
        raise HTTPException(429, "Too many requests — slow down")
    _rate_limit_store[ip].append(now)


# User sessions (in-memory map: token -> user_id)
_active_tokens: dict[str, str] = {}

# ── Auth Dependency ────────────────────────────────────────────────────────

def require_auth(authorization: str = Header("")) -> User:
    """Validate Bearer token and return the user.
    Owners/admins bypass the subscription check."""
    if not authorization:
        raise HTTPException(401, "Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(401, "Invalid token")
    if user.is_deleted:
        raise HTTPException(403, "Account deleted")
    if not user.is_pro:
        raise HTTPException(402, "Access required — ask this instance administrator to enable your account")
    return user


def require_auth_only(authorization: str = Header("")) -> User:
    """Validate token only — no subscription check."""
    if not authorization:
        raise HTTPException(401, "Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(401, "Invalid token")
    if user.is_deleted:
        raise HTTPException(403, "Account deleted")
    return user


def optional_auth(authorization: str = Header("")) -> Optional[User]:
    """Optional auth — used for login/register."""
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return get_user_by_token(token)


def require_admin(authorization: str = Header("")) -> User:
    """Validate token and require admin/owner role."""
    if not authorization:
        raise HTTPException(401, "Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(401, "Invalid token")
    if user.is_deleted:
        raise HTTPException(403, "Account deleted")
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


# ── Request Models ─────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r'^[a-zA-Z0-9_]+$')
    password: str = Field(min_length=8, max_length=128)
    email: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    model: str = ""
    variant: str = "high"
    session_id: str | None = None


class PaymentVerifyRequest(BaseModel):
    tx_hash: str
    amount: float
    chain: str = "TRC20"


class ProvisionRequest(BaseModel):
    mem_mb: int = 2048
    cpu: int = 2
    disk_gb: int = 10


class SetExpiryRequest(BaseModel):
    timestamp: float  # unix epoch expiry time


class PromoteRequest(BaseModel):
    role: str = "pro"  # "pro" | "restricted"
    days: int = 30


# ── Response Models ────────────────────────────────────────────────────────

class AuthResponse(BaseModel):
    token: str
    user_id: str
    username: str
    subscription: str


class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_count: int
    prompt_type: str = ""  # "always" | "run" | "question" | "text"
    options: list[str] = []  # for question prompts — the model's multiple choice options
    allow_custom: bool = False  # for question prompts — whether user can type custom answer
    commands: list[dict] = []  # tool commands run by the AI


class ProvisionResponse(BaseModel):
    container_id: str
    lxc_name: str
    private_ip: str
    status: str
    message: str


def _opencode_shell_cmd(project_dir: str, model: str, variant: str, message: str,
                        continue_session: bool) -> list[str]:
    args = ["opencode", "run", "--format", "json", "-p", project_dir]
    if model:
        args.extend(["-m", model])
    if variant:
        args.extend(["--variant", variant])
    if continue_session:
        args.append("--continue")
    args.append(message)

    quoted_args = " ".join(shlex.quote(a) for a in args)
    script = f"""
set -e
export HOME=/root
export PATH="/root/.opencode/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
if ! command -v opencode >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq >/dev/null
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates git bash tar gzip unzip >/dev/null
    fi
    curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path
fi
command -v opencode >/dev/null 2>&1
exec {quoted_args}
""".strip()
    return ["/bin/bash", "-lc", script]


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/api/status")
def health():
    assets = []
    if _frontend_has_build:
        for f in (_frontend_dist_resolved / "assets").iterdir():
            assets.append(f.name)
    return {
        "status": "ok",
        "service": "klyra",
        "version": "2.0.0",
        "frontend_built": _frontend_has_build,
        "assets": assets,
        "dist_path": str(_frontend_dist_resolved),
    }


@app.get("/api/models")
def list_models():
    """Return available AI models and variants from models.json."""
    models_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models.json")
    try:
        with open(models_path) as f:
            data = json.load(f)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "models": ["opencode/deepseek-v4-flash-free"],
            "variants": ["low", "medium", "high", "max"],
            "updated_at": "",
        }


@app.get("/api/config")
def get_config(user: User = Depends(require_auth_only)):
    """Return user-specific configuration."""
    return {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "subscription": user.subscription,
        "sub_expires_at": user.sub_expires_at,
        "pro_expiry": user.pro_expiry,
        "is_pro": user.is_pro,
    }


@app.post("/api/register")
def register(req: RegisterRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip, max_reqs=5, window=300)
    existing = get_user_by_username(req.username)
    if existing:
        raise HTTPException(400, "Registration failed")

    pw_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    user = create_user(req.username, pw_hash, req.email)
    _active_tokens[user.api_token] = user.id

    logger.info("User registered: %s (id=%s)", user.username, user.id)
    return AuthResponse(token=user.api_token, user_id=user.id,
                        username=user.username, subscription=user.subscription)


@app.post("/api/login")
def login(req: LoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip, max_reqs=10, window=300)
    user = get_user_by_username(req.username)
    if not user or user.is_deleted:
        raise HTTPException(401, "Invalid credentials")

    if not bcrypt.checkpw(req.password.encode(), user.password_hash.encode()):
        raise HTTPException(401, "Invalid credentials")

    _active_tokens[user.api_token] = user.id
    logger.info("User logged in: %s", user.username)
    return AuthResponse(token=user.api_token, user_id=user.id,
                        username=user.username, subscription=user.subscription)


@app.post("/api/chat")
async def chat(req: ChatRequest, user: User = Depends(require_auth)):
    """Send a message to OpenCode running inside the user's container.
    Returns SSE stream with keepalive to prevent Cloudflare 524 timeout."""
    container = get_container_by_user(user.id)
    if not container:
        raise HTTPException(400, "No container provisioned — call /api/provision first")
    if container.status != "running":
        raise HTTPException(503, "Container not running — reprovision")
    update_container_active(container.id)

    # Get or create session record
    sid = req.session_id
    short_id = uuid.uuid4().hex[:6]
    if sid:
        session = get_session_by_id(sid)
        if not session or session.container_id != container.id:
            session = create_session_record(
                container.id,
                f"/root/projects/{user.username}_{short_id}",
                req.model, req.variant,
            )
    else:
        session = create_session_record(
            container.id,
            f"/root/projects/{user.username}_{short_id}",
            req.model, req.variant,
        )

    project_dir = session.project_folder or f"/root/projects/{user.username}_{uuid.uuid4().hex[:6]}"

    # Save user message
    save_session_message(session.id, "user", req.message)

    cmd = _opencode_shell_cmd(
        project_dir,
        req.model,
        req.variant,
        req.message,
        session.message_count > 0,
    )

    logger.info("Chat exec starting user=%s session=%s msg_len=%d continue=%s",
                user.username, session.id, len(req.message), session.message_count > 0)

    spec = container_id_to_spec(container)

    async def stream_events():
        loop = asyncio.get_event_loop()
        response_text = ""
        prompt_type = "text"
        commands = []

        def run_exec():
            return exec_in_container(spec, cmd, timeout=600)

        future = loop.run_in_executor(None, run_exec)

        # Wait with keepalive (prevent Cloudflare 524)
        while not future.done():
            try:
                r = await asyncio.wait_for(asyncio.shield(future), timeout=25)
            except asyncio.TimeoutError:
                yield "event: heartbeat\ndata: \n\n"
                continue
            except Exception as e:
                logger.error("Chat exec FAILED user=%s session=%s err=%s",
                             user.username, session.id, e, exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'detail': str(e)[:200]})}\n\n"
                return

        # Exec completed
        logger.info("Chat exec OK user=%s session=%s stdout_len=%d",
                    user.username, session.id, len(r.stdout or ""))

        # Parse NDJSON and stream each event
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            event = {}
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            yield f"data: {line}\n\n"

            part = event.get("part", {})
            evt_type = event.get("type", "")

            if evt_type == "text":
                response_text += part.get("text", "")
            elif evt_type == "tool_use":
                tool = part.get("tool", "")
                state = part.get("state", {})
                inp = state.get("input", {})
                status = state.get("status", "")

                cmd_entry = {"tool": tool, "status": status}
                if tool == "bash":
                    prompt_type = "run"
                    cmd_entry["command"] = inp.get("command", "")
                elif tool == "write":
                    prompt_type = "always"
                    cmd_entry["filePath"] = inp.get("filePath", "")
                elif tool == "webfetch":
                    cmd_entry["url"] = inp.get("url", "") or inp.get("query", "")
                elif tool == "websearch":
                    cmd_entry["query"] = inp.get("query", "")
                if status == "completed":
                    output = state.get("output", "")
                    if output and output.strip():
                        cmd_entry["output"] = output.strip()[:1000]
                commands.append(cmd_entry)

        # Save to DB
        session.message_count += 1
        update_session_activity(session.id, session.message_count)
        msg_data = json.dumps({"text": response_text.strip(), "commands": commands})
        save_session_message(session.id, "assistant", msg_data, prompt_type, [], False)

        # Send completion event
        result = {
            "response": response_text.strip(),
            "session_id": session.id,
            "message_count": session.message_count,
            "prompt_type": prompt_type,
            "commands": commands,
        }
        yield f"event: done\ndata: {json.dumps(result)}\n\n"

    return StreamingResponse(stream_events(), media_type="text/event-stream")


def _do_provision(user: User) -> dict:
    """Internal provision helper — called by payment verify and provision endpoint."""
    lxc_name = f"ai-{user.id[:12]}"
    spec = ContainerSpec(
        user_id=hash(user.id) % 9999 + 1,
        username=user.username,
        lxc_name=lxc_name,
        bridge="", private_ip="", subnet="",
        mem_mb=2048, cpu=2, disk_gb=10,
    )
    created = lxc_create(spec)
    record = create_container_record(user.id, lxc_name, {
        "bridge": created.bridge, "private_ip": created.private_ip,
        "subnet": created.subnet, "status": created.status,
        "mem_mb": spec.mem_mb, "cpu": spec.cpu, "disk_gb": spec.disk_gb,
    })
    return {
        "container_id": record.id,
        "lxc_name": lxc_name,
        "private_ip": created.private_ip,
        "status": created.status,
    }


@app.post("/api/provision")
def provision(user: User = Depends(require_auth)):
    """Provision an LXC container for the user. Idempotent — returns existing if any."""
    existing = get_container_by_user(user.id)
    if existing and existing.status in ("running", "stopped"):
        lxc_name = existing.lxc_name
        from isolation import _lxd_get
        alive = False
        try:
            state = _lxd_get(f"/1.0/instances/{lxc_name}/state", timeout=10)
            alive = state.get("status") == "Running"
        except Exception:
            pass
        if not alive:
            update_container_status(existing.id, "deleted")
            logger.info("Removed stale container record for %s (LXC missing)", user.username)
        else:
            return ProvisionResponse(
                container_id=existing.id,
                lxc_name=lxc_name,
                private_ip=existing.private_ip or "",
                status=existing.status,
                message="Container already exists",
            )
    try:
        result = _do_provision(user)
        logger.info("Container provisioned for %s: %s (%s)", user.username, result["lxc_name"], result["private_ip"])
        return ProvisionResponse(**result, message="Container provisioned successfully")
    except Exception as e:
        logger.error("Provision failed for %s: %s", user.username, e)
        raise HTTPException(500, "Provisioning failed — check server logs")


@app.get("/api/sessions/{session_id}/messages")
def get_session_messages_endpoint(session_id: str, user: User = Depends(require_auth)):
    """Get full message history for a session."""
    container = get_container_by_user(user.id)
    if not container:
        raise HTTPException(400, "No container")
    session = get_session_by_id(session_id)
    if not session or session.container_id != container.id:
        raise HTTPException(404, "Session not found")
    messages = get_session_messages(session_id)
    return {"messages": messages, "session_id": session_id,
            "project_folder": session.project_folder}


def _resolve_container_path(path: str) -> str:
    """Resolve a path relative to /root/projects, ensuring no escape."""
    base = "/root/projects"
    if path.startswith(base):
        target = os.path.normpath(path)
    else:
        target = os.path.normpath(os.path.join(base, path.lstrip("/")))
    if not target.startswith(base):
        raise HTTPException(400, "Access denied")
    return target


@app.get("/api/files")
def list_files(path: str = "", user: User = Depends(require_auth)):
    """List files and folders in the user's container project directory."""
    container = get_container_by_user(user.id)
    if not container:
        raise HTTPException(400, "No container")
    if not container.status == "running":
        raise HTTPException(503, "Container not running")

    target = _resolve_container_path(path)

    # Use stat to get file info reliably
    r = exec_in_container(
        container_id_to_spec(container),
        ["bash", "-c", "ls -1a -- \"$1\" 2>/dev/null", "_", target],
        timeout=15, check=False,
    )
    if r.returncode != 0:
        return {"files": [], "path": target}

    entries = [e.strip() for e in r.stdout.strip().split("\n") if e.strip()]

    files = []
    for e in entries:
        if e in (".", ".."):
            continue
        full_path = os.path.join(target, e)
        # Get file type and size
        stat_r = exec_in_container(
            container_id_to_spec(container),
            ["stat", "-c", "%F %s", full_path],
            timeout=5, check=False,
        )
        is_dir = stat_r.returncode == 0 and "directory" in stat_r.stdout
        size = 0
        if stat_r.returncode == 0 and not is_dir:
            try:
                size = int(stat_r.stdout.strip().split()[-1])
            except (ValueError, IndexError):
                size = 0
        files.append({
            "name": e,
            "path": full_path,
            "is_dir": is_dir,
            "size": size,
        })

    return {"files": files, "path": target}


@app.get("/api/files/download")
def download_file(path: str, user: User = Depends(require_auth)):
    """Download a file from the container."""
    container = get_container_by_user(user.id)
    if not container or container.status != "running":
        raise HTTPException(400, "Container not available")

    target = _resolve_container_path(path)

    r = exec_in_container(
        container_id_to_spec(container),
        ["cat", target], timeout=15, check=False,
    )
    if r.returncode != 0:
        raise HTTPException(404, "File not found")

    from fastapi.responses import Response
    return Response(
        content=r.stdout,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(target)}"'},
    )


@app.get("/api/files/read")
def read_file(path: str, user: User = Depends(require_auth)):
    """Read a file content from container (inline display, not download)."""
    container = get_container_by_user(user.id)
    if not container or container.status != "running":
        raise HTTPException(400, "Container not available")

    target = _resolve_container_path(path)

    r = exec_in_container(
        container_id_to_spec(container),
        ["cat", target], timeout=15, check=False,
    )
    if r.returncode != 0:
        raise HTTPException(404, "File not found")

    return {"content": r.stdout, "path": target, "name": os.path.basename(target)}


@app.post("/api/sessions/{session_id}/delete")
def delete_session_endpoint(session_id: str, user: User = Depends(require_auth)):
    """Delete a session and its project folder."""
    container = get_container_by_user(user.id)
    if not container:
        raise HTTPException(400, "No container")
    session = get_session_by_id(session_id)
    if not session or session.container_id != container.id:
        raise HTTPException(404, "Session not found")

    # Delete project folder in container
    if session.project_folder:
        exec_in_container(
            container_id_to_spec(container),
            ["rm", "-rf", session.project_folder],
            timeout=15, check=False,
        )

    delete_session_messages(session_id)
    deactivate_session_on_delete(session_id)

    return {"status": "deleted"}


def deactivate_session_on_delete(sid: str):
    from database import deactivate_session as _ds
    _ds(sid)


def _chat_local(req: ChatRequest):
    """Fallback: run locally without container (for dev/testing)."""
    from backend import SessionManager, DEFAULT_MODEL
    sm = SessionManager()
    sessions_map = {}

    if req.session_id and req.session_id in sessions_map:
        meta = sessions_map[req.session_id]
    else:
        name = req.session_id or f"web-{uuid.uuid4().hex[:8]}"
        meta = sm.create_session(name, req.model or DEFAULT_MODEL, req.variant)
        sessions_map[meta.id] = meta

    events = list(sm.send_message(meta, req.message))
    response_text = ""
    prompt_type = "text"
    for event in events:
        if not isinstance(event, dict):
            continue
        part = event.get("part", {})
        evt_type = event.get("type", "")

        if evt_type == "text":
            response_text += part.get("text", "")
        elif evt_type == "tool_use":
            tool = part.get("tool", "")
            state = part.get("state", {})
            inp = state.get("input", {})
            status = state.get("status", "")

            if tool == "bash":
                prompt_type = "run"
                cmd = html.escape(inp.get("command", ""))
                response_text += f"\n\n**[RUN]** `{cmd}`"
            elif tool == "write":
                prompt_type = "always"
                path = html.escape(inp.get("filePath", ""))
                response_text += f"\n\n**[ALWAYS]** `{path}`"
            if status == "completed":
                output = state.get("output", "")
                if output and output.strip():
                    preview = html.escape(output.strip()[:300])
                    if len(output.strip()) > 300:
                        preview += "..."
                    response_text += f"\n<details><summary>Output ({len(output.strip())} bytes)</summary>\n```\n{preview}\n```\n</details>"

            if status == "skipped":
                response_text += "\n_skipped_"

    return ChatResponse(
        response=response_text.strip(),
        session_id=meta.id,
        message_count=meta.message_count,
        prompt_type=prompt_type,
        options=[],
        allow_custom=False,
    )


@app.get("/api/sessions")
def list_sessions(user: User = Depends(require_auth)):
    container = get_container_by_user(user.id)
    if not container:
        return []
    sessions = get_active_sessions(container.id)
    result = []
    for s in sessions:
        folder_name = os.path.basename(s.project_folder or "") if s.project_folder else f"session-{s.id[:8]}"
        result.append({
            "id": s.id,
            "title": folder_name,
            "project": s.project_folder,
            "model": s.model,
            "messages": s.message_count,
            "last_active": s.last_message_at,
        })
    return result


@app.post("/api/payment/verify")
def verify_payment(req: PaymentVerifyRequest, user: User = Depends(require_auth_only)):
    """Record an access activation claim for manual admin verification.
    Claims are NOT auto-confirmed — admin must verify via the admin panel."""
    if req.amount < 20:
        raise HTTPException(400, "Minimum claim amount is 20")

    payment = create_payment(user.id, req.amount, req.tx_hash, req.chain)

    logger.info("Activation claim recorded for %s: %.2f (tx: %s) — awaiting admin verification",
                user.username, req.amount, req.tx_hash)

    return {
        "status": "pending",
        "payment_id": payment.id,
        "amount": req.amount,
        "tx_hash": req.tx_hash,
        "message": "Payment claim recorded. An instance administrator must verify and activate the account.",
    }


@app.get("/api/user")
def get_user(user: User = Depends(require_auth_only)):
    return {
        "id": user.id,
        "username": user.username,
        "subscription": user.subscription,
        "sub_expires_at": user.sub_expires_at,
        "pro_expiry": user.pro_expiry,
        "role": user.role,
        "is_pro": user.is_pro,
        "created_at": user.created_at,
    }


# ── Admin Endpoints ────────────────────────────────────────────────────────


@app.get("/api/admin/users")
def admin_list_users(admin: User = Depends(require_admin)):
    """List all users with full details. Admin only."""
    users = list_all_users()
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "subscription": u.subscription,
                "pro_expiry": u.pro_expiry,
                "sub_expires_at": u.sub_expires_at,
                "created_at": u.created_at,
                "is_pro": u.is_pro,
            }
            for u in users
        ],
        "total": len(users),
    }


@app.post("/api/admin/users/{uid}/promote")
def admin_promote_user(uid: str, req: PromoteRequest, admin: User = Depends(require_admin)):
    """Promote a user to pro or restricted. Admin only."""
    user = get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "User not found")
    if user.is_admin:
        raise HTTPException(400, "Cannot modify admin users")
    if req.role == "pro":
        days = max(1, min(int(req.days or 30), 3650))
        expiry = time.time() + days * 86400
        set_user_role(uid, "pro")
        set_user_expiry(uid, expiry)
        logger.info("Admin %s promoted user %s for %d days", admin.username, user.username, days)
        return {
            "status": "ok",
            "user_id": uid,
            "role": "pro",
            "pro_expiry": expiry,
            "expires_at": datetime.fromtimestamp(expiry, tz=timezone.utc).isoformat(),
        }

    clear_user_expiry(uid)
    set_user_role(uid, "user")
    logger.info("Admin %s restricted user %s", admin.username, user.username)
    return {"status": "ok", "user_id": uid, "role": "user", "pro_expiry": 0}


@app.post("/api/admin/users/{uid}/set-expiry")
def admin_set_expiry(uid: str, req: SetExpiryRequest, admin: User = Depends(require_admin)):
    """Set a user's pro expiry timestamp. Auto-calculates 30 days if 0 passed. Admin only."""
    user = get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "User not found")
    expiry = req.timestamp
    if expiry <= 0:
        expiry = time.time() + 30 * 86400
    set_user_role(uid, "pro")
    set_user_expiry(uid, expiry)
    logger.info("Admin %s set expiry for %s to %s", admin.username, user.username, expiry)
    return {
        "status": "ok",
        "user_id": uid,
        "pro_expiry": expiry,
        "expires_at": datetime.fromtimestamp(expiry, tz=timezone.utc).isoformat(),
    }


@app.post("/api/admin/users/{uid}/unset-expiry")
def admin_unset_expiry(uid: str, admin: User = Depends(require_admin)):
    """Remove expiry and demote user to restricted. Admin only."""
    user = get_user_by_id(uid)
    if not user:
        raise HTTPException(404, "User not found")
    clear_user_expiry(uid)
    set_user_role(uid, "user")
    logger.info("Admin %s removed expiry for %s, set to restricted", admin.username, user.username)
    return {"status": "ok", "user_id": uid, "role": "user", "pro_expiry": 0}


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r'^[a-zA-Z0-9_]+$')
    password: str = Field(min_length=8, max_length=128)
    pro_expiry_days: int = 365


@app.post("/api/admin/users/create")
def admin_create_user(req: AdminCreateUserRequest, admin: User = Depends(require_admin)):
    """Create a pro account directly (no payment). Admin only."""
    existing = get_user_by_username(req.username)
    if existing:
        raise HTTPException(400, "Username already taken")
    pw_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    expiry = time.time() + req.pro_expiry_days * 86400
    user = db_create_user(req.username, pw_hash, role="pro", pro_expiry=expiry)
    logger.info("Admin %s created pro account: %s (expiry: %d days)",
                admin.username, user.username, req.pro_expiry_days)
    return {
        "status": "ok",
        "user_id": user.id,
        "username": user.username,
        "role": "pro",
        "pro_expiry": expiry,
        "token": user.api_token,
    }


@app.get("/api/admin/containers")
def admin_list_containers(admin: User = Depends(require_admin)):
    """List all containers with owner info. Admin only."""
    containers = list_all_containers()
    result = []
    for c in containers:
        owner = get_user_by_id(c.user_id)
        result.append({
            "id": c.id,
            "lxc_name": c.lxc_name,
            "user_id": c.user_id,
            "username": owner.username if owner else "unknown",
            "private_ip": c.private_ip,
            "status": c.status,
            "mem_mb": c.mem_mb,
            "cpu": c.cpu,
            "disk_gb": c.disk_gb,
            "created_at": c.created_at,
            "last_active_at": c.last_active_at,
        })
    return {"containers": result, "total": len(result)}


@app.post("/api/admin/containers/{lxc_name}/stop")
def admin_stop_container(lxc_name: str, admin: User = Depends(require_admin)):
    """Stop a container by LXC name. Admin only."""
    container = get_container_by_lxc_name(lxc_name)
    if not container:
        raise HTTPException(404, "Container not found")
    spec = container_id_to_spec(container)
    try:
        lxc_stop(spec)
    except Exception as e:
        logger.error("Admin %s failed to stop container %s: %s", admin.username, lxc_name, e)
        raise HTTPException(500, f"Failed to stop: {e}")
    update_container_status(container.id, "stopped")
    logger.info("Admin %s stopped container %s", admin.username, lxc_name)
    return {"status": "stopped", "lxc_name": lxc_name}


@app.post("/api/admin/containers/{lxc_name}/delete")
def admin_delete_container(lxc_name: str, admin: User = Depends(require_admin)):
    """Delete a container by LXC name. Admin only."""
    container = get_container_by_lxc_name(lxc_name)
    if not container:
        raise HTTPException(404, "Container not found")
    spec = container_id_to_spec(container)
    try:
        lxc_delete(spec)
    except Exception as e:
        logger.error("Admin %s failed to delete container %s: %s", admin.username, lxc_name, e)
        raise HTTPException(500, f"Failed to delete: {e}")
    update_container_status(container.id, "deleted")
    logger.info("Admin %s deleted container %s", admin.username, lxc_name)
    return {"status": "deleted", "lxc_name": lxc_name}


# ── Helpers ────────────────────────────────────────────────────────────────

def container_id_to_spec(container: Container) -> ContainerSpec:
    return ContainerSpec(
        user_id=hash(container.user_id) % 9999 + 1,
        username="",
        lxc_name=container.lxc_name,
        bridge=container.bridge or "",
        private_ip=container.private_ip or "",
        subnet=container.subnet or "",
        status=container.status,
    )


# ── Static Files (Production Frontend) ─────────────────────────────────────

_frontend_dist = Path(os.path.dirname(os.path.abspath(__file__))) / "frontend" / "dist"
_frontend_dist_resolved = _frontend_dist.resolve()
_frontend_index = _frontend_dist_resolved / "index.html"
_frontend_has_build = _frontend_index.is_file()


_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/")
async def serve_root():
    if _frontend_has_build:
        return FileResponse(str(_frontend_index), headers=_NO_CACHE_HEADERS)
    raise HTTPException(404, "Frontend not built — run: cd frontend && npm install && npm run build")


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    if full_path.startswith("api/") or not _frontend_has_build:
        raise HTTPException(404)
    requested = (_frontend_dist / full_path).resolve()
    if not str(requested).startswith(str(_frontend_dist_resolved)):
        raise HTTPException(400)
    if requested.is_file():
        return FileResponse(str(requested), headers=_NO_CACHE_HEADERS)
    # If it looks like a file (has extension), return 404 instead of index.html
    if "." in full_path.replace("/", ""):
        raise HTTPException(404)
    return FileResponse(str(_frontend_index), headers=_NO_CACHE_HEADERS)


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    # Seed owner account — OWNER_PASSWORD env var is REQUIRED
    owner_pw = os.environ.get("OWNER_PASSWORD")
    if not owner_pw:
        print("[x] OWNER_PASSWORD environment variable is required")
        print("    Set it before running: export OWNER_PASSWORD='your-strong-password'")
        sys.exit(1)
    seed_owner(owner_pw)

    port = int(len(sys.argv) > 1 and sys.argv[1] or os.environ.get("PORT") or "8099")
    bind = os.environ.get("BIND", "0.0.0.0")
    print(f"⚡ Klyra API v2 — http://{bind}:{port}")
    print(f"   Isolated containers: LXC")
    print(f"   Database encryption: AES-256")
    uvicorn.run(app, host=bind, port=port)
