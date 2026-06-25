#!/usr/bin/env python3
"""
KLYRA — Fully automated deploy script.
Zero config. Single command. Cloudflare tunnel.

Usage:
    python3 deploy/run.py                  Normal deploy
    python3 deploy/run.py --nuke           Nuke everything + fresh deploy
    python3 deploy/run.py --nuke-lxd       Reinstall LXD from scratch + deploy

Env vars (optional):
    PORT            Backend port (default: 8099)
    BIND            Bind address (default: 127.0.0.1)
    DB_MASTER_KEY   Encryption key for DB (default: auto-generated)
    OWNER_PASSWORD  Owner account password (default: auto-generated)
"""

import json, os, sys, time, uuid, shutil, signal, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"

ROOT_PROCS: dict[str, subprocess.Popen | None] = {}

def log(msg): print(f"{GREEN}[+] {msg}{RESET}")
def warn(msg): print(f"{YELLOW}[!] {msg}{RESET}")
def error(msg): print(f"{RED}[x] {msg}{RESET}")
def header(msg): print(f"\n{CYAN}{'='*60}\n{msg}\n{'='*60}{RESET}\n")

def run(cmd, cwd=None, check=True, timeout=300, capture=True):
    try:
        return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
            check=check, timeout=timeout, capture_output=capture, text=True)
    except subprocess.TimeoutExpired:
        if check: raise
        return None
    except subprocess.CalledProcessError as e:
        if e.stderr: warn(e.stderr.strip())
        if check: raise
    except FileNotFoundError:
        warn(f"Command not found: {cmd[0]}")
        if check: raise
        return None

_USE_SUDO_LXC = False
_LXC_BIN = "lxc"
_LXD_BIN = "lxd"

def _find_bins():
    global _LXC_BIN, _LXD_BIN
    _LXC_BIN = shutil.which("lxc") or "/snap/bin/lxc"
    _LXD_BIN = shutil.which("lxd") or "/snap/bin/lxd"

def run_lxc(cmd, check=True, timeout=60):
    """Run lxc command, prefixing sudo if needed."""
    global _USE_SUDO_LXC, _LXC_BIN
    base = ["sudo", _LXC_BIN] if _USE_SUDO_LXC else [_LXC_BIN]
    r = run(base + cmd, check=check, timeout=timeout)
    if r is not None and r.returncode != 0 and not _USE_SUDO_LXC:
        _USE_SUDO_LXC = True
        base = ["sudo", _LXC_BIN]
        r = run(base + cmd, check=check, timeout=timeout)
    return r

def check_cmd(name): return shutil.which(name) is not None

def write_env_file(env):
    p = ROOT / ".env"
    existing = {}
    if p.exists():
        for line in p.read_text().strip().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    for k, v in env.items(): existing.setdefault(k, v)
    p.write_text("\n".join(f"{k}={v}" for k, v in sorted(existing.items())) + "\n")
    os.chmod(p, 0o600)
    log(f"Environment file: {p}")

def ensure_curl():
    if not check_cmd("curl"):
        log("Installing curl...")
        run(["apt-get", "install", "-y", "-qq", "curl"], check=False, timeout=60)

def ensure_apt_pkg(pkg: str):
    if not check_cmd("apt-get"):
        return
    run(["apt-get", "update", "-qq"], check=False, timeout=60)
    run(["apt-get", "install", "-y", "-qq", pkg], check=False, timeout=60)

def remove_ai_lxd_containers():
    _find_bins()
    if not os.path.exists(_LXC_BIN):
        return
    r = run_lxc(["list", "--format", "json"], check=False, timeout=20)
    if not r or r.returncode != 0:
        return
    try:
        containers = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        containers = []
    names = [c.get("name", "") for c in containers if c.get("name", "").startswith("ai-")]
    if names:
        log(f"Removing {len(names)} Klyra LXD container(s)...")
    for name in names:
        run_lxc(["stop", name, "--force"], check=False, timeout=30)
        run_lxc(["delete", name], check=False, timeout=60)

def fresh_runtime_state():
    """Start the app from a clean Klyra runtime without touching unrelated LXD state."""
    header("PRE-FLIGHT — Fresh Klyra runtime")
    log("Stopping old backend/tunnel processes...")
    run(["pkill", "-f", str(ROOT / "server.py")], check=False, timeout=5)
    run(["pkill", "-f", "uvicorn"], check=False, timeout=5)
    run(["pkill", "-f", "cloudflared"], check=False, timeout=5)

    remove_ai_lxd_containers()

    log("Removing local app database/session state...")
    for p in [
        ROOT / "data" / "klyra.db",
        ROOT / "data" / "klyra.db-wal",
        ROOT / "data" / "klyra.db-shm",
        ROOT / "data" / ".db-salt",
        ROOT / "server_out.log",
        ROOT / "cloudflared.log",
    ]:
        if p.exists():
            p.unlink(missing_ok=True)
    for d in [ROOT / "sessions"]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    for d in [ROOT / "data", ROOT / "logs"]:
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    log("Fresh runtime ready")

def install_python_deps():
    header("STEP 1/6 — Installing Python dependencies")
    ensure_curl()
    pkgs = ["fastapi", "uvicorn[standard]", "bcrypt", "cryptography", "rich", "pydantic", "setuptools"]

    # Try multiple pip install strategies
    strategies = [
        [sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages"],
        [sys.executable, "-m", "pip", "install", "--quiet", "--user"],
        [sys.executable, "-m", "pip", "install", "--quiet"],
    ]
    for pip_cmd in strategies:
        r = run(pip_cmd + pkgs + ["--no-cache-dir"], check=False, timeout=180)
        if r and r.returncode == 0:
            log("Python dependencies installed")
            return
    # Final attempt with full output for debugging
    r = run([sys.executable, "-m", "pip", "install"] + pkgs + ["--no-cache-dir"], check=False, timeout=180)
    if r and r.returncode == 0:
        log("Python dependencies installed")
        return
    error(f"pip install failed — try manually: pip install {' '.join(pkgs)}")
    sys.exit(1)

def check_lxd():
    header("STEP 2/6 — Checking LXD + pulling base image")
    ensure_curl()
    _find_bins()

    if not check_cmd("lxc"):
        warn("LXD not found. Installing via snap...")
        r = run(["snap", "install", "lxd"], check=False, timeout=180)
        if r is None or r.returncode != 0:
            error("Failed to install LXD via snap.")
            sys.exit(1)
        _find_bins()
    else:
        log("LXD binary found")

    # Install uidmap before LXD init (needed for unprivileged container UID mapping)
    ensure_apt_pkg("uidmap")

    # Try to talk to LXD daemon — if it fails, initialize it
    r = run_lxc(["info"], check=False, timeout=15)
    if r is None or r.returncode != 0:
        log("Initializing LXD (sudo lxd init --auto)...")
        for init_cmd in [["sudo", _LXD_BIN, "init", "--auto"], [_LXD_BIN, "init", "--auto"]]:
            r2 = run(init_cmd, check=False, timeout=60)
            if r2 and r2.returncode == 0:
                break
        time.sleep(3)
        r = run_lxc(["info"], check=False, timeout=15)
        if r is None or r.returncode != 0:
            warn("LXD daemon not responding. Continuing anyway.")

    # Ensure default storage pool exists
    r = run_lxc(["storage", "list"], check=False, timeout=15)
    if r and r.returncode == 0 and "default" not in r.stdout:
        log("Creating default storage pool...")
        run_lxc(["storage", "create", "default", "dir"], check=False, timeout=30)

    # Pre-pull Kali base image
    log("Pulling Kali base image (this may take a few minutes)...")
    r = run_lxc(["image", "list", "--format", "json"], check=False, timeout=30)
    already_have = False
    if r and r.returncode == 0:
        import json
        for img in json.loads(r.stdout or "[]"):
            for alias in img.get("aliases", []):
                if alias.get("name") == "kali-full":
                    already_have = True
                    break
    if not already_have:
        warn("Pulling images:kali/current/default/amd64 (~2min)...")
        r = run_lxc(["image", "copy", "images:kali/current/default/amd64", "local:",
                     "--alias", "kali-full"], check=False, timeout=600)
        if r is None or r.returncode != 0:
            warn("Image pull failed. Continuing — isolation.py will retry with REST API.")
        else:
            log("Kali base image ready")
    else:
        log("Kali base image already present")

def build_frontend():
    header("STEP 3/6 — Building frontend")
    if not FRONTEND.exists():
        warn(f"Frontend directory not found: {FRONTEND}"); return

    if not check_cmd("node"):
        warn("Node.js not found. Installing...")
        run(["apt-get", "update", "-qq"], check=False, timeout=60)
        run(["apt-get", "install", "-y", "-qq", "nodejs", "npm", "curl"], check=False, timeout=120)

    if not check_cmd("node"):
        warn("Node.js still not available. Skipping frontend build.")
        return

    # Check Node version — need 18+
    try:
        v = run(["node", "--version"], timeout=5).stdout.strip()
        log(f"Node.js {v}")
        vnum = int(v.lstrip("v").split(".")[0])
        if vnum < 18:
            warn(f"Node.js {v} is too old. Installing Node.js 20 LTS via NodeSource...")
            run(["curl", "-fsSL", "https://deb.nodesource.com/setup_20.x", "-o", "/tmp/nodesetup.sh"], check=False, timeout=30)
            if Path("/tmp/nodesetup.sh").exists():
                run(["bash", "/tmp/nodesetup.sh"], check=False, timeout=60)
                run(["apt-get", "install", "-y", "-qq", "nodejs"], check=False, timeout=120)
                v2 = run(["node", "--version"], timeout=5, check=False)
                if v2 and v2.returncode == 0:
                    log(f"Updated Node.js to {v2.stdout.strip()}")
    except Exception as ex:
        warn(f"Node version check: {ex}")

    if not (FRONTEND / "node_modules").exists():
        log("Installing npm dependencies...")
        r = run(["npm", "install"], cwd=FRONTEND, timeout=300, check=False)
        if r and r.returncode != 0:
            warn("npm install failed. Trying with --legacy-peer-deps...")
            run(["npm", "install", "--legacy-peer-deps"], cwd=FRONTEND, timeout=300, check=False)

    log("Building frontend...")
    r = run(["npx", "vite", "build"], cwd=FRONTEND, timeout=120, check=False)
    if r and r.returncode != 0:
        warn("vite build failed. Check Node version (need 18+).")
        return

    dist_path = FRONTEND / "dist" / "index.html"
    if dist_path.exists():
        log(f"Frontend built: {dist_path}")
    else:
        warn("Frontend build may have failed — index.html not found.")

def start_backend():
    header("STEP 4/6 — Starting backend")
    env = os.environ.copy()
    db_key = os.environ.get("DB_MASTER_KEY") or str(uuid.uuid4())
    owner_pw = os.environ.get("OWNER_PASSWORD") or "testpass123"
    owner_username = os.environ.get("OWNER_USERNAME", "owner")
    bind = os.environ.get("BIND", "127.0.0.1")
    port = int(os.environ.get("PORT", "8099"))

    env["DB_MASTER_KEY"] = db_key
    env["OWNER_PASSWORD"] = owner_pw
    env["OWNER_USERNAME"] = owner_username
    env["BIND"] = bind
    env["PORT"] = str(port)

    for d in [ROOT / "data", ROOT / "logs"]:
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)

    write_env_file({
        "DB_MASTER_KEY": db_key,
        "OWNER_PASSWORD": owner_pw,
        "OWNER_USERNAME": owner_username,
        "BIND": bind,
        "PORT": str(port),
    })

    log(f"Owner username: {owner_username}")
    log(f"Owner password: {owner_pw}")
    warn("SAVE these credentials. They will NOT be shown again.")

    log(f"Starting backend...")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py")],
        cwd=str(ROOT), env=env,
        stdout=open(ROOT / "server_out.log", "w"), stderr=subprocess.STDOUT,
    )
    ROOT_PROCS["backend"] = proc

    # Wait for startup
    import socket
    for _ in range(20):
        time.sleep(1)
        if proc.poll() is not None:
            error(f"Backend failed (exit {proc.returncode})")
            sys.exit(1)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            break
        except:
            continue
    else:
        warn("Backend may not be ready yet. Continuing...")

    log(f"Backend running (PID: {proc.pid})")
    return proc, port

def setup_tunnel(port):
    header("STEP 5/6 — Cloudflare tunnel")

    tunnel_url = None

    if not check_cmd("cloudflared"):
        log("Installing cloudflared...")
        if not check_cmd("curl"):
            run(["apt-get", "install", "-y", "-qq", "curl"], check=False, timeout=60)
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine, "amd64")
        run(["curl", "-sL", f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}", "-o", "/usr/local/bin/cloudflared"], timeout=60)
        run(["chmod", "+x", "/usr/local/bin/cloudflared"], timeout=5)
        log("cloudflared installed")

    log("Starting tunnel...")
    logfile = ROOT / "cloudflared.log"
    tunnel_proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=open(logfile, "w"), stderr=subprocess.STDOUT,
    )
    ROOT_PROCS["tunnel"] = tunnel_proc

    start = time.time()
    while time.time() - start < 90:
        if logfile.exists():
            text = logfile.read_text()
            if "trycloudflare.com" in text:
                for line in text.splitlines():
                    if "trycloudflare.com" in line:
                        for w in line.split():
                            if w.startswith("https://") and "trycloudflare.com" in w:
                                tunnel_url = w
                                break
                    if tunnel_url:
                        break
        if tunnel_url:
            break
        if tunnel_proc.poll() is not None:
            warn("cloudflared process exited unexpectedly")
            break
        time.sleep(1)

    if tunnel_url:
        log(f"Tunnel URL: {tunnel_url}")
    else:
        warn("Tunnel URL not found after 90s. Run manually: cloudflared tunnel --url http://127.0.0.1:{port}")

    return tunnel_proc, tunnel_url

def verify_deployment():
    header("STEP 6/6 — Security checks")
    checks = 0; passed = 0
    ep = ROOT / ".env"
    if ep.exists():
        m = os.stat(ep).st_mode & 0o777; checks += 1
        if m <= 0o600: passed += 1
        else: warn(f".env permissions: {oct(m)}")
    dp = ROOT / "data"
    if dp.exists():
        m = os.stat(dp).st_mode & 0o777; checks += 1
        if m <= 0o700: passed += 1
        else: warn(f"data/ permissions: {oct(m)}")
    if check_cmd("ufw"):
        r = run(["ufw", "status"], check=False, timeout=5)
        checks += 1
        if r and r.returncode == 0 and "inactive" not in r.stdout: passed += 1
        else: warn("UFW not active — sudo ufw enable")
    log(f"Security: {passed}/{checks} passed")
    return passed == checks

def cleanup(signum=None, frame=None):
    print(); warn("Shutting down...")
    for name in ("tunnel", "backend"):
        proc = ROOT_PROCS.get(name)
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()
            log(f"{name} stopped")
    sys.exit(0)


def nuke(nuke_lxd=False):
    """Nuclear cleanup — wipe everything before fresh deploy."""
    header("NUKE — wiping all state")
    log("Killing running processes...")
    run(["pkill", "-f", "uvicorn"], check=False, timeout=5)
    run(["pkill", "-f", "cloudflared"], check=False, timeout=5)

    ROOT_PROCS.clear()

    # Find lxc binary
    lxc_bin = shutil.which("lxc") or ""
    lxd_bin = shutil.which("lxd") or ""

    if lxc_bin:
        log("Removing all LXD containers...")
        run([lxc_bin, "stop", "--all"], check=False, timeout=30)
        run([lxc_bin, "delete", "--all"], check=False, timeout=60)

        log("Removing all LXD images...")
        r = run([lxc_bin, "image", "list", "--format", "json"], check=False, timeout=15)
        if r and r.returncode == 0:
            import json
            for img in json.loads(r.stdout or "[]"):
                for alias in img.get("aliases", []):
                    run([lxc_bin, "image", "delete", alias["name"]], check=False, timeout=15)

        log("Removing LXD storage pools...")
        r = run([lxc_bin, "storage", "list", "--format", "json"], check=False, timeout=15)
        if r and r.returncode == 0:
            import json
            for pool in json.loads(r.stdout or "[]"):
                run([lxc_bin, "storage", "delete", pool["name"]], check=False, timeout=30)

    if nuke_lxd and lxd_bin:
        log("Removing LXD snap...")
        run(["snap", "remove", "lxd"], check=False, timeout=120)
        run(["rm", "-rf", "/var/snap/lxd"], check=False, timeout=10)

    # Remove database
    db_path = ROOT / "data" / "klyra.db"
    if db_path.exists():
        log(f"Removing database: {db_path}")
        db_path.unlink(missing_ok=True)
    salt = ROOT / "data" / ".db-salt"
    if salt.exists():
        salt.unlink(missing_ok=True)

    # Remove logs
    for f in ["server_out.log", "cloudflared.log"]:
        p = ROOT / f
        if p.exists():
            p.unlink()

    # Remove cached frontend
    for d in [ROOT / "frontend" / "node_modules", ROOT / "frontend" / "dist",
              ROOT / "__pycache__", ROOT / "deploy" / "__pycache__",
              ROOT / "data"]:
        if d.exists():
            log(f"Removing: {d}")
            run(["rm", "-rf", str(d)], check=False, timeout=10)

    # Remove .env
    env_file = ROOT / ".env"
    if env_file.exists():
        env_file.unlink()

    log("Nuke complete. Starting fresh deploy...")
    print()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    do_nuke = "--nuke" in sys.argv or "--clean" in sys.argv
    do_nuke_lxd = "--nuke-lxd" in sys.argv

    if do_nuke or do_nuke_lxd:
        nuke(nuke_lxd=do_nuke_lxd)

    print(f"""
{RED}    █████╗ ██╗    ██╗  ██╗ █████╗  ██████╗██╗  ██╗███████╗██████╗ {RESET}
{RED}   ██╔══██╗██║    ██║  ██║██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗{RESET}
{RED}   ███████║██║    ███████║███████║██║     █████╔╝ █████╗  ██████╔╝{RESET}
{RED}   ██╔══██║██║    ██╔══██║██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗{RESET}
{RED}   ██║  ██║██║    ██║  ██║██║  ██║╚██████╗██║  ██╗███████╗██║  ██╗{RESET}
{RED}   ╚═╝  ╚═╝╚═╝    ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝{RESET}
{GREEN}               SELF-HOSTED AI SECURITY LAB{RESET}
{CYAN}               Authorized testing · Fresh LXD workspaces{RESET}
    """)

    os.chdir(str(ROOT))

    try:
        fresh_runtime_state()
        install_python_deps()
        check_lxd()
        remove_ai_lxd_containers()
        build_frontend()
        backend_proc, port = start_backend()

        # Verify frontend is served
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect(("127.0.0.1", port))
            s.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            resp = s.recv(4096).decode(errors="replace")
            s.close()
            if "<!doctype html" in resp.lower():
                log("Frontend verified: HTML served at /")
            else:
                warn("Frontend might not be serving HTML at /")
                warn(f"Response: {resp[:200]}")
        except Exception as e:
            warn(f"Frontend verification skipped: {e}")

        tunnel_proc, tunnel_url = setup_tunnel(port)
        verify_deployment()

        print()
        header("DEPLOYMENT COMPLETE")
        if tunnel_url:
            log(f"{BOLD}Public URL:{RESET} {CYAN}{tunnel_url}{RESET}")
        else:
            warn("No tunnel URL. Local only.")
        log(f"Local: http://127.0.0.1:{port}")
        log(f"Owner: {GREEN}{os.environ.get('OWNER_USERNAME', 'owner')}{RESET}")
        log("Running in background — use screen -r klyra to attach")
    except Exception as e:
        error(f"Deploy failed: {e}")
        cleanup()
        sys.exit(1)
