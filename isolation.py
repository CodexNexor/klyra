#!/usr/bin/env python3
"""Klyra Isolation Layer — LXD REST API (no lxc CLI needed)."""

import json, logging, os, shutil, socket, subprocess, sys, time, uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("isolation")

LXD_SOCKET = os.environ.get("LXD_SOCKET") or ""
_LXD_SOCKETS = [
    "/var/snap/lxd/common/lxd/unix.socket",
    "/var/lib/lxd/unix.socket",
    "/run/lxd/unix.socket",
]


def _find_socket():
    global LXD_SOCKET
    if LXD_SOCKET and os.path.exists(LXD_SOCKET):
        return
    for s in _LXD_SOCKETS:
        if os.path.exists(s):
            LXD_SOCKET = s
            logger.info("LXD socket: %s", s)
            return
    raise RuntimeError("LXD socket not found (checked: %s)" % ", ".join(_LXD_SOCKETS))


def _http_body(raw: bytes) -> bytes:
    hdr_end = raw.index(b"\r\n\r\n") + 4
    header_text = raw[:hdr_end].decode(errors="replace")
    body = raw[hdr_end:]
    headers = {}
    for line in header_text.split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip().lower()

    if headers.get("transfer-encoding") == "chunked":
        decoded = bytearray()
        pos = 0
        while pos < len(body):
            line_end = body.find(b"\r\n", pos)
            if line_end < 0:
                break
            size_text = body[pos:line_end].split(b";", 1)[0].strip()
            try:
                size = int(size_text, 16)
            except ValueError:
                break
            pos = line_end + 2
            if size == 0:
                break
            decoded += body[pos:pos + size]
            pos += size + 2
        return bytes(decoded)

    if "content-length" in headers:
        try:
            return body[:int(headers["content-length"])]
        except ValueError:
            return body
    return body


def _lxd_raw(method: str, path: str, body: dict | None = None, timeout: int = 30):
    _find_socket()
    body_bytes = json.dumps(body).encode() if body else None
    http_req = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
    if body_bytes:
        http_req += f"Content-Type: application/json\r\nContent-Length: {len(body_bytes)}\r\n"
    http_req += "Connection: close\r\n\r\n"
    wire = http_req.encode()
    if body_bytes:
        wire += body_bytes
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(LXD_SOCKET)
        sock.sendall(wire)
        raw = b""
        while True:
            chunk = sock.recv(16384)
            if not chunk:
                break
            raw += chunk
    finally:
        sock.close()
    return json.loads(_http_body(raw).decode())


def _lxd(method: str, path: str, body=None, timeout=30, wait=True):
    data = _lxd_raw(method, path, body, timeout)
    if data.get("type") == "error":
        raise RuntimeError(f"LXD error: {data.get('error', 'unknown')}")
    if wait and data.get("type") == "async":
        op_url = data.get("operation", "")
        if op_url:
            _wait_op(op_url, timeout=timeout)
        return data.get("metadata")
    return data.get("metadata")


def _lxd_get(path: str, timeout=30): return _lxd("GET", path, timeout=timeout)
def _lxd_post(path: str, body=None, timeout=30): return _lxd("POST", path, body, timeout)
def _lxd_put(path: str, body=None, timeout=30): return _lxd("PUT", path, body, timeout)
def _lxd_delete(path: str, timeout=30): return _lxd("DELETE", path, timeout=timeout)


def _wait_op(url: str, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = _lxd_raw("GET", url)
        if data.get("type") == "error":
            raise RuntimeError(f"LXD operation failed: {data.get('error', 'unknown')}")
        meta = data.get("metadata", {})
        if meta.get("status") == "Success":
            return meta.get("metadata")
        if meta.get("status") == "Failure":
            raise RuntimeError(f"LXD operation failed: {meta.get('err', 'unknown')}")
        time.sleep(0.5)
    raise TimeoutError(f"LXD operation timed out: {url}")


@dataclass
class ContainerSpec:
    user_id: int = 0
    username: str = ""
    lxc_name: str = ""
    bridge: str = ""
    private_ip: str = ""
    subnet: str = ""
    status: str = "pending"
    mem_mb: int = 2048
    cpu: int = 2
    disk_gb: int = 10


def ensure_lxd():
    info = _lxd_get("/1.0")
    logger.info("LXD %s connected", info.get("environment", {}).get("server_version", "?"))


def create_managed_bridge(bridge_name: str = "lxdbr0") -> dict:
    nets = _lxd_get("/1.0/networks?recursion=1")
    for n in nets:
        if n["name"] == bridge_name:
            return {"bridge": bridge_name, "gateway": ""}
    logger.info("Creating bridge %s...", bridge_name)
    _lxd_post("/1.0/networks", {
        "name": bridge_name,
        "type": "bridge",
        "config": {
            "ipv4.address": "10.99.0.1/24",
            "ipv4.nat": "true",
            "ipv4.dhcp": "true",
            "ipv6.address": "none",
            "dns.mode": "managed",
        },
    }, timeout=30)
    return {"bridge": bridge_name, "gateway": ""}


def destroy_bridge(br: str):
    pass


def _get_ip(cid: str) -> str:
    try:
        state = _lxd_get(f"/1.0/instances/{cid}/state", timeout=10)
    except Exception:
        return ""
    for _, iface in state.get("network", {}).items():
        for addr in iface.get("addresses", []):
            if addr["family"] == "inet" and not addr["address"].startswith("127"):
                return addr["address"]
    return ""


def _wait_network(cid: str, timeout: int = 60):
    for i in range(timeout):
        ip = _get_ip(cid)
        if ip:
            return
        time.sleep(1)
    raise TimeoutError(f"Container {cid} network not ready")


def _exec(cid: str, cmd: list[str], timeout: int = 30, check: bool = True) -> str:
    """Run a command inside a container via LXD exec API (blocking)."""
    body = {
        "command": cmd,
        "environment": {"HOME": "/root", "USER": "root"},
        "wait-for-websocket": False,
        "record-output": True,
        "interactive": False,
    }
    data = _lxd_raw("POST", f"/1.0/instances/{cid}/exec", body, timeout=timeout)
    if data.get("type") == "error":
        raise RuntimeError(f"LXD exec error: {data.get('error', 'unknown')}")
    op_url = data.get("operation", "")
    if not op_url:
        raise RuntimeError(f"No operation URL from exec (container {cid} may not be running)")
    meta = _wait_op(op_url, timeout=timeout)
    output = meta.get("output", {})
    raw = output.get("1", "") or output.get("stdout", "")
    if not raw:
        return ""
    import base64
    if raw.startswith("/1.0/"):
        try:
            sock2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock2.settimeout(timeout)
            sock2.connect(LXD_SOCKET)
            try:
                req = f"GET {raw} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                sock2.sendall(req.encode())
                r2 = b""
                while True:
                    c = sock2.recv(16384)
                    if not c:
                        break
                    r2 += c
            finally:
                sock2.close()
            return _http_body(r2).decode(errors="replace").strip()
        except Exception:
            return raw
    try:
        return base64.b64decode(raw).decode("utf-8", errors="replace")
    except Exception:
        return raw


def _file_push(cid: str, src: str, dst: str, timeout: int = 30):
    """Push a file into the container."""
    _find_socket()
    with open(src, "rb") as f:
        data = f.read()
    http_req = (
        f"POST /1.0/instances/{cid}/files?path={dst} HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/octet-stream\r\n"
        f"Content-Length: {len(data)}\r\n"
        f"Connection: close\r\n\r\n"
    )
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(LXD_SOCKET)
        sock.sendall(http_req.encode() + data)
        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
    finally:
        sock.close()


def create_hardened_container(spec: ContainerSpec) -> ContainerSpec:
    ensure_lxd()
    ensure_storage_pool()
    ensure_base_image()

    cid = spec.lxc_name

    # A provision request must produce a clean user environment. If a stale
    # instance with the same deterministic name is present, purge it first.
    try:
        instances = _lxd_get("/1.0/instances?recursion=1", timeout=15)
        for c in instances:
            if c["name"] == cid:
                logger.info("Removing existing container %s before fresh provision", cid)
                delete_container(spec)
                break
    except Exception:
        pass

    net = create_managed_bridge()
    spec.bridge = net["bridge"]
    logger.info("Creating container %s (user %s)...", cid, spec.username)

    config = {
        "name": cid,
        "source": {"type": "image", "alias": "kali-full"},
        "storage": "klyra",
        "config": {
            "security.privileged": "false",
            "security.nesting": "false",
            "limits.memory": f"{spec.mem_mb}MB",
            "limits.cpu": str(spec.cpu),
            "limits.processes": "256",
        },
        "devices": {
            "root": {
                "type": "disk",
                "path": "/",
                "pool": "klyra",
                "size": f"{spec.disk_gb}GB",
            },
            "eth0": {
                "type": "nic",
                "nictype": "bridged",
                "parent": net["bridge"],
                "name": "eth0",
            },
        },
    }
    _lxd_post("/1.0/instances", config, timeout=600)
    _lxd_put(f"/1.0/instances/{cid}/state", {"action": "start"}, timeout=60)
    _wait_network(cid)
    spec.private_ip = _get_ip(cid)
    _provision(cid)

    spec.status = "running"
    logger.info("Container %s ready — IP: %s", cid, spec.private_ip)
    return spec


def _provision(cid: str):
    logger.info("Provisioning %s...", cid)
    script = rf"""#!/bin/bash
set -e
export HOME=/root
echo "root ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/opencode 2>/dev/null || true
chmod 440 /etc/sudoers.d/opencode 2>/dev/null || true
rm -rf /root/.opencode /root/.local/share/opencode /root/.config/opencode /root/projects
mkdir -p /root/.opencode/bin /root/projects
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates git bash tar gzip unzip >/dev/null
fi
curl -fsSL https://opencode.ai/install | bash -s -- --no-modify-path
grep -qxF 'export PATH="/root/.opencode/bin:$PATH"' /root/.bashrc 2>/dev/null || echo 'export PATH="/root/.opencode/bin:$PATH"' >> /root/.bashrc
export PATH="/root/.opencode/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
OPENCODE_BIN="$(command -v opencode)"
test -x "$OPENCODE_BIN"
"$OPENCODE_BIN" --version
echo PROVISION_DONE
"""
    script_path = "/tmp/prov.sh"
    Path(script_path).write_text(script)
    try:
        _file_push(cid, script_path, "/root/prov.sh", timeout=30)
    except Exception as e:
        logger.warning("Failed to push provision script: %s", e)
        raise RuntimeError(f"Failed to push provision script: {e}") from e
    try:
        out = _exec(cid, ["bash", "/root/prov.sh"], timeout=180)
    except Exception as e:
        logger.warning("Provision exec failed (container may still be usable): %s", e)
        raise RuntimeError(f"Provision exec failed: {e}") from e
    if "PROVISION_DONE" not in out:
        raise RuntimeError(f"Provision failed: {out[:300]}")
    logger.info("Provision complete")

    agents_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "OPENCODE.md")
    if os.path.exists(agents_path):
        try:
            _exec(cid, ["mkdir", "-p", "/root/.config/opencode"], timeout=10)
            _file_push(cid, agents_path, "/root/.config/opencode/AGENTS.md", timeout=30)
        except Exception as e:
            logger.warning("Failed to push AGENTS.md: %s", e)


def delete_container(spec: ContainerSpec):
    cid = spec.lxc_name
    logger.warning("Purging %s...", cid)
    try:
        _lxd_put(f"/1.0/instances/{cid}/state", {"action": "stop"}, timeout=30)
    except Exception:
        pass
    try:
        _lxd_delete(f"/1.0/instances/{cid}", timeout=60)
    except Exception:
        pass
    spec.status = "deleted"
    logger.warning("Purged %s", cid)


def exec_in(spec: ContainerSpec, cmd, timeout=120):
    out = _exec(spec.lxc_name, cmd, timeout=timeout)
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr="")


def exec_in_container(spec: ContainerSpec, cmd: list, timeout=120, check=True):
    out = _exec(spec.lxc_name, cmd, timeout=timeout)
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr="")


def container_running(spec: ContainerSpec) -> bool:
    try:
        state = _lxd_get(f"/1.0/instances/{spec.lxc_name}/state", timeout=10)
        return state.get("status") == "Running"
    except Exception:
        return False


def ensure_storage_pool():
    pools = _lxd_get("/1.0/storage-pools?recursion=1", timeout=15)
    for p in pools:
        if p["name"] == "klyra":
            logger.info("Storage pool klyra already exists")
            return
    _lxd_post("/1.0/storage-pools", {"name": "klyra", "driver": "dir"}, timeout=60)


def ensure_base_image():
    images = _lxd_get("/1.0/images?recursion=1", timeout=30)
    for img in images:
        for alias in img.get("aliases", []):
            if alias["name"] == "kali-full":
                logger.info("Base image kali-full already exists")
                return
    logger.info("Pulling Kali base image (this may take a few minutes)...")
    source = {"type": "image", "mode": "pull", "server": "https://images.lxd.canonical.com",
              "protocol": "simplestreams", "alias": "kali"}
    _lxd_post("/1.0/images", {"source": source, "aliases": [{"name": "kali-full"}]}, timeout=600)


def audit(spec: ContainerSpec) -> list[str]:
    findings = []
    try:
        info = _lxd_get(f"/1.0/instances/{spec.lxc_name}", timeout=10)
        cfg = info.get("config", {})
    except Exception:
        return ["ERROR: cannot inspect container"]
    if cfg.get("security.privileged") == "true":
        findings.append("CRITICAL: privileged mode enabled")
    if cfg.get("security.nesting") == "true":
        findings.append("MEDIUM: nesting enabled")
    tests = [
        ("dmesg", ["dmesg"]), ("lsmod", ["lsmod"]),
        ("read /proc/1/environ", ["cat", "/proc/1/environ"]),
        ("sysctl modify", ["sysctl", "-w", "kernel.hostname=escape_test"]),
    ]
    for name, cmd in tests:
        try:
            out = _exec(spec.lxc_name, cmd, timeout=10)
            if name == "dmesg" and out.strip():
                findings.append("HIGH: dmesg accessible")
            if name == "lsmod" and out.strip():
                findings.append("MEDIUM: lsmod works")
            if name == "read /proc/1/environ" and out.strip():
                findings.append("CRITICAL: /proc/1/environ readable")
            if name == "sysctl modify":
                findings.append("CRITICAL: sysctl modification succeeded")
        except Exception:
            pass
    return findings


def selftest():
    test_name = f"ai-test-{uuid.uuid4().hex[:8]}"
    spec = ContainerSpec(user_id=9999, username="selftest", lxc_name=test_name)
    print(f"\n{'='*60}")
    print("  KLYRA HARDENED ISOLATION — SELFTEST")
    print(f"{'='*60}")
    try:
        print("\n  [1/4] Creating hardened container...")
        spec = create_hardened_container(spec)
        print(f"         ✓ Running | IP: {spec.private_ip}")
        print("\n  [2/4] Security audit...")
        findings = audit(spec)
        if findings:
            print(f"         ✗ {len(findings)} finding(s):")
            for f in findings:
                print(f"           ⚠ {f}")
        else:
            print("         ✓ All checks passed")
        print("\n  [3/4] OpenCode...")
        out = _exec(spec.lxc_name, ["/root/.opencode/bin/opencode", "--version"], timeout=30)
        if out.strip():
            print(f"         ✓ OpenCode version: {out.strip()[:60]}")
        else:
            print("         ✗ No output")
        print("\n  [4/4] Cleaning up...")
        delete_container(spec)
        print("         ✓ Purged")
        print(f"\n{'='*60}")
        print(f"  RESULT: {'PASS' if not findings else 'PASS WITH WARNINGS'}")
        print(f"{'='*60}\n")
        return len(findings)
    except Exception as e:
        print(f"\n  ✗ FAILED: {e}")
        import traceback; traceback.print_exc()
        delete_container(spec)
        return 99


def create_container(spec: ContainerSpec, **_) -> ContainerSpec:
    return create_hardened_container(spec)


def start_container(spec: ContainerSpec):
    _lxd_put(f"/1.0/instances/{spec.lxc_name}/state", {"action": "start"})


def stop_container(spec: ContainerSpec):
    try:
        _lxd_put(f"/1.0/instances/{spec.lxc_name}/state", {"action": "stop"})
    except Exception:
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    else:
        print("Usage: python3 isolation.py selftest")
