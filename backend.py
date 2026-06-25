#!/usr/bin/env python3
"""
Klyra Backend — OpenCode Multi-Session Orchestrator
Manages isolated OpenCode sessions, each with its own project dir and AGENTS.md (jailbreak prompt).
CLI: colorful, interactive, session history, idle timeout, model switching.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Generator

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.layout import Layout
from rich.live import Live
from rich.box import ROUNDED, HEAVY
from rich.align import Align
from rich import box
import readline  # better input handling

# ─── Paths ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
SESSIONS_DIR = BASE_DIR / "sessions"
OPENCODE_MD = BASE_DIR / "OPENCODE.md"
OPENCODE_BIN = "opencode"

# ─── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_MODEL = ""  # empty = let opencode decide
MODEL_VARIANTS = ["auto", "none", "minimal", "low", "medium", "high", "max", "xhigh"]
IDLE_TIMEOUT_MINUTES = 10

console = Console()

# ─── Helpers ──────────────────────────────────────────────────────────────

def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def short_id() -> str:
    return "sess_" + uuid.uuid4().hex[:12]

def find_opencode() -> str:
    """Locate the opencode binary."""
    which = shutil.which(OPENCODE_BIN)
    if which:
        return which
    # check common locations
    candidates = [
        Path.home() / ".opencode/bin/opencode",
        Path.home() / ".local/bin/opencode",
        Path("/usr/local/bin/opencode"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    console.print("[red]✗ opencode not found. Install: curl -fsSL https://opencode.ai/install | bash[/red]")
    sys.exit(1)

OPENCODE_PATH = find_opencode()

# ─── Data ─────────────────────────────────────────────────────────────────

@dataclass
class Message:
    role: str        # "user" | "assistant"
    content: str
    timestamp: str = field(default_factory=timestamp)

@dataclass
class SessionMeta:
    id: str
    name: str
    model: str = DEFAULT_MODEL
    variant: str = "high"
    created_at: str = field(default_factory=timestamp)
    last_active: str = field(default_factory=timestamp)
    message_count: int = 0
    total_cost: float = 0.0
    opencode_session_id: Optional[str] = None

    @property
    def project_dir(self) -> Path:
        return SESSIONS_DIR / self.id / "project"

    @property
    def meta_path(self) -> Path:
        return SESSIONS_DIR / self.id / "meta.json"

    @property
    def history_path(self) -> Path:
        return SESSIONS_DIR / self.id / "history.json"


# ─── Session Manager ─────────────────────────────────────────────────────

class SessionManager:
    """Creates, tracks, and manages isolated OpenCode sessions."""

    def __init__(self):
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._timeout_thread = threading.Thread(target=self._timeout_loop, daemon=True)
        self._timeout_thread.start()

    # ── CRUD ────────────────────────────────────────────────────────────

    def create_session(self, name: str, model: str = DEFAULT_MODEL,
                       variant: str = "high") -> SessionMeta:
        sid = short_id()
        meta = SessionMeta(id=sid, name=name, model=model, variant=variant)
        session_dir = SESSIONS_DIR / sid
        session_dir.mkdir(parents=True)

        # project dir for opencode
        meta.project_dir.mkdir(parents=True, exist_ok=True)

        # copy OPENCODE.md as AGENTS.md
        if OPENCODE_MD.exists():
            shutil.copy2(str(OPENCODE_MD), str(meta.project_dir / "AGENTS.md"))
        else:
            (meta.project_dir / "AGENTS.md").write_text(
                "# Klyra Session\nYou are an autonomous penetration testing agent."
            )

        self._save_meta(meta)
        return meta

    def get_session(self, sid: str) -> Optional[SessionMeta]:
        meta_path = SESSIONS_DIR / sid / "meta.json"
        if not meta_path.exists():
            return None
        with open(meta_path) as f:
            data = json.load(f)
        return SessionMeta(**data)

    def list_sessions(self) -> list[SessionMeta]:
        if not SESSIONS_DIR.exists():
            return []
        sessions = []
        for entry in sorted(SESSIONS_DIR.iterdir(), key=os.path.getmtime, reverse=True):
            if entry.is_dir():
                meta = self.get_session(entry.name)
                if meta:
                    sessions.append(meta)
        return sessions

    def delete_session(self, sid: str) -> bool:
        session_dir = SESSIONS_DIR / sid
        if session_dir.exists():
            shutil.rmtree(session_dir)
            return True
        return False

    def _save_meta(self, meta: SessionMeta):
        with self._lock:
            meta.meta_path.parent.mkdir(parents=True, exist_ok=True)
            with open(meta.meta_path, "w") as f:
                json.dump(asdict(meta), f, indent=2)

    def _save_history(self, meta: SessionMeta, messages: list[Message]):
        with self._lock:
            with open(meta.history_path, "w") as f:
                json.dump([asdict(m) for m in messages], f, indent=2)

    def load_history(self, meta: SessionMeta) -> list[Message]:
        if meta.history_path.exists():
            with open(meta.history_path) as f:
                return [Message(**m) for m in json.load(f)]
        return []

    def touch_session(self, meta: SessionMeta):
        meta.last_active = timestamp()
        self._save_meta(meta)

    # ── Send Message ───────────────────────────────────────────────────

    def send_message(self, meta: SessionMeta, text: str) -> Generator[dict, None, list[Message]]:
        """
        Send a message to the OpenCode session.
        Yields events (dicts) from the JSON stream.
        Returns the updated message list.
        """
        messages = self.load_history(meta)

        # save user message
        user_msg = Message(role="user", content=text)
        messages.append(user_msg)
        self._save_history(meta, messages)

        self.touch_session(meta)

        # build command
        cmd = [
            OPENCODE_PATH, "run",
            "--dir", str(meta.project_dir),
            "--dangerously-skip-permissions",
            "--format", "json",
        ]
        if meta.model:
            cmd.extend(["--model", meta.model])
        if meta.variant and meta.variant != "auto":
            cmd.extend(["--variant", meta.variant])
        # continue existing session (each project dir has exactly one)
        if meta.message_count > 0:
            cmd.append("--continue")
        cmd.append(text)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        assistant_parts = []
        session_ids = set()
        stderr_lines = []

        def read_stderr():
            for line in process.stderr:
                stderr_lines.append(line)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        # read stdout (JSON events)
        step_finished_ok = False
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            sid = event.get("sessionID")
            if sid:
                session_ids.add(sid)

            event_type = event.get("type")
            part = event.get("part", {})

            yield event

            if event_type == "text":
                txt = part.get("text", "")
                if txt:
                    assistant_parts.append(txt)

            if event_type == "tool_use":
                state = part.get("state", {})
                output = state.get("output", "")
                if output:
                    assistant_parts.append(f"\n```\n{output}\n```\n")

            if event_type == "step_finish" and part.get("reason") == "stop":
                step_finished_ok = True

        process.wait()

        # update meta
        if session_ids:
            meta.opencode_session_id = list(session_ids)[-1]

        err_text = "".join(stderr_lines)

        # check for auth/model errors
        if process.returncode != 0 and not assistant_parts:
            err_msg = "Unknown error"
            for kw in ["not found", "no provider", "auth", "api key", "unauthorized", "not configured"]:
                if kw in err_text.lower():
                    err_msg = f"Model/auth error: run `opencode auth login` first"
                    break
                if kw in str(stderr_lines).lower():
                    err_msg = f"Model/auth error: run `opencode auth login` first"
                    break
            err_msg = err_text[:300] if not err_msg else err_msg
            assistant_parts.append(f"[error] {err_text[:500]}")

        # save assistant response (always, even if just step finish)
        if step_finished_ok or assistant_parts:
            assistant_content = "\n".join(assistant_parts) if assistant_parts else "[no text response]"
            if len(assistant_content) > 10000:
                assistant_content = assistant_content[:10000] + "\n\n[output truncated]"
            assistant_msg = Message(role="assistant", content=assistant_content)
            messages.append(assistant_msg)

        meta.message_count = len([m for m in messages if m.role == "user"])
        self._save_meta(meta)
        self._save_history(meta, messages)
        self.touch_session(meta)

        return messages

    # ── Idle Timeout ───────────────────────────────────────────────────

    def _timeout_loop(self):
        """Background thread: close sessions idle > IDLE_TIMEOUT_MINUTES."""
        while True:
            time.sleep(30)
            now = datetime.now(timezone.utc)
            for meta in self.list_sessions():
                try:
                    last = datetime.fromisoformat(meta.last_active)
                    delta = (now - last).total_seconds() / 60
                    if delta > IDLE_TIMEOUT_MINUTES:
                        self.delete_session(meta.id)
                        console.print(
                            f"[dim]⏰ Session [cyan]{meta.name}[/cyan] "
                            f"auto-closed after {IDLE_TIMEOUT_MINUTES}m idle[/dim]"
                        )
                except Exception:
                    pass


# ─── CLI ─────────────────────────────────────────────────────────────────

class CLI:
    """Interactive terminal UI for session management."""

    def __init__(self):
        self.sm = SessionManager()

    def banner(self):
        console.clear()
        console.print(Panel(
            Text.from_markup(
                "[bold bright_red]🎯 Klyra Backend[/bold bright_red]\n"
                "[italic dim]OpenCode Multi-Session Orchestrator[/italic dim]\n"
                f"[dim]{OPENCODE_PATH}[/dim]"
            ),
            box=HEAVY,
            border_style="bright_red",
            padding=(1, 2),
        ))
        console.print()

    def main_menu(self):
        while True:
            self.banner()
            sessions = self.sm.list_sessions()
            active_count = len(sessions)

            model_display = DEFAULT_MODEL if DEFAULT_MODEL else "[italic]auto (opencode default)[/italic]"
            console.print(Panel(
                Text.from_markup(
                    "[bold]Active Sessions:[/bold] "
                    f"[cyan]{active_count}[/cyan]\n"
                    f"[dim]Idle timeout: {IDLE_TIMEOUT_MINUTES}m  |  "
                    f"Default model: [/dim]{model_display}"
                ),
                box=ROUNDED,
                border_style="blue",
            ))
            console.print()

            table = Table(box=ROUNDED, header_style="bold cyan", border_style="dim")
            table.add_column("#", style="dim", width=3)
            table.add_column("Session", style="bold")
            table.add_column("Model", style="yellow")
            table.add_column("Msgs", justify="right")
            table.add_column("Cost", justify="right")
            table.add_column("Last Active", style="dim")
            table.add_column("Status", justify="center")

            if not sessions:
                table.add_row("", "[dim]No sessions yet[/dim]", "", "", "", "", "")
            else:
                for i, s in enumerate(sessions, 1):
                    status = "[green]● Active[/green]" if self._is_active(s) else "[dim]● Idle[/dim]"
                    model_name = s.model.split("/")[-1][:20] if s.model else "default"
                    table.add_row(
                        str(i),
                        s.name,
                        model_name,
                        str(s.message_count),
                        f"${s.total_cost:.4f}" if s.total_cost else "-",
                        s.last_active.split("T")[1][:8] if "T" in s.last_active else "-",
                        status,
                    )

            console.print(table)
            console.print()

            choices = Text.from_markup(
                "[bold cyan][1][/bold cyan] New Session    "
                "[bold cyan][2][/bold cyan] Open Session    "
                "[bold cyan][3][/bold cyan] Delete Session\n"
                "[bold cyan][4][/bold cyan] Set Model      "
                "[bold cyan][5][/bold cyan] Session Stats  "
                "[bold cyan][6][/bold cyan] List Models\n"
                "[bold cyan][7][/bold cyan] Exit"
            )
            console.print(Panel(choices, box=ROUNDED, border_style="bright_blue"))

            action = Prompt.ask("\n[bold]>[/bold]", default="1").strip()

            if action == "1":
                self.new_session_flow()
            elif action == "2":
                self.open_session_flow()
            elif action == "3":
                self.delete_session_flow()
            elif action == "4":
                self.set_model_flow()
            elif action == "5":
                self.stats_flow()
            elif action == "6":
                self.list_models_flow()
            elif action == "7":
                console.print("[yellow]Session closed.[/yellow]")
                break

    def _is_active(self, meta: SessionMeta) -> bool:
        try:
            last = datetime.fromisoformat(meta.last_active)
            delta = (datetime.now(timezone.utc) - last).total_seconds() / 60
            return delta < 5
        except Exception:
            return False

    def new_session_flow(self):
        self.banner()
        console.print("[bold cyan]╔══ New Session ══╗[/bold cyan]\n")
        name = Prompt.ask("[bold]Session name[/bold]", default=f"target-{uuid.uuid4().hex[:6]}")
        model = Prompt.ask(
            "[bold]Model[/bold]",
            default=DEFAULT_MODEL,
        )
        variant = Prompt.ask(
            "[bold]Variant[/bold]",
            default="high",
            choices=MODEL_VARIANTS,
        )

        with console.status("[bold green]Creating session...[/bold green]"):
            meta = self.sm.create_session(name, model, variant)

        console.print(f"\n[green]✓[/green] Session [bold cyan]{meta.name}[/bold cyan] created")
        console.print(f"  [dim]ID:[/dim] {meta.id}")
        console.print(f"  [dim]Project:[/dim] {meta.project_dir}")
        console.print(f"  [dim]Model:[/dim] {meta.model} [dim]({meta.variant})[/dim]")

        if Confirm.ask("\n[bold]Enter chat mode now?[/bold]", default=True):
            self.chat_loop(meta)

    def chat_loop(self, meta: SessionMeta):
        """Interactive chat with a session."""
        messages = self.sm.load_history(meta)

        while True:
            self.banner()
            # session header
            stat_line = (
                f"[dim]Model:[/dim] {meta.model} "
                f"[dim]Variant:[/dim] {meta.variant} "
                f"[dim]Msgs:[/dim] {meta.message_count} "
                f"[dim]OC Session:[/dim] {meta.opencode_session_id or 'new'}"
            )
            console.print(Panel(
                Text.from_markup(
                    f"[bold cyan]💬 Session: {meta.name}[/bold cyan]\n"
                    f"{stat_line}"
                ),
                box=ROUNDED,
                border_style="cyan",
            ))

            # show history (last 20 messages)
            if messages:
                console.print()
                console.print("[bold underline]Recent History:[/bold underline]")
                for m in messages[-10:]:
                    prefix = "[bold green]You >[/bold green]" if m.role == "user" else "[bold]Klyra >[/bold]"
                    # truncate long messages for history display
                    display = m.content[:200] + "..." if len(m.content) > 200 else m.content
                    console.print(f"  {prefix} {display}")
            console.print()

            # input
            console.print("[dim]Type [/dim][bold]/help[/bold][dim] for commands, [/dim][bold]/back[/bold][dim] to return[/dim]")
            msg = Prompt.ask("[bold green]You[/bold green]").strip()

            if msg.lower() == "/back":
                break
            elif msg.lower() == "/help":
                self._chat_help()
                continue
            elif msg.lower() == "/history":
                self._show_full_history(messages)
                continue
            elif msg.lower() == "/clear":
                messages.clear()
                self.sm._save_history(meta, messages)
                meta.message_count = 0
                self.sm._save_meta(meta)
                console.print("[green]✓ Conversation cleared[/green]")
                continue
            elif msg.lower().startswith("/model "):
                meta.model = msg[7:].strip()
                self.sm._save_meta(meta)
                console.print(f"[green]✓ Model changed to {meta.model}[/green]")
                continue
            elif msg.lower().startswith("/variant "):
                meta.variant = msg[9:].strip()
                self.sm._save_meta(meta)
                console.print(f"[green]✓ Variant changed to {meta.variant}[/green]")
                continue

            if not msg:
                continue

            # send message
            console.print()
            with console.status("[bold yellow]OpenCode is working...[/bold yellow]"):
                try:
                    for event in self.sm.send_message(meta, msg):
                        self._display_event(event)
                except Exception as e:
                    console.print(f"[red]✗ Error: {e}[/red]")

            # reload messages
            messages = self.sm.load_history(meta)

    def _display_event(self, event: dict):
        """Render a single JSON event to the terminal."""
        etype = event.get("type", "unknown")
        part = event.get("part", {})

        if etype == "step_start":
            pass

        elif etype == "step_finish":
            reason = part.get("reason", "")
            tokens = part.get("tokens", {})
            cost = part.get("cost", 0)
            if tokens:
                total_t = tokens.get("total", 0)
                cache_info = ""
                if tokens.get("cache", {}).get("read", 0):
                    cache_info = f" [dim](cache hit {tokens['cache']['read']})[/dim]"
                console.print(
                    f"  [dim]━━ {reason} — "
                    f"{total_t}t ${cost:.4f}{cache_info}[/dim]"
                )

        elif etype == "text":
            text = part.get("text", "")
            if text:
                console.print(Text.from_markup(f"[bold]Klyra >[/bold] {text}"))

        elif etype == "tool_use":
            tool = part.get("tool", "?")
            state = part.get("state", {})
            inp = state.get("input", {})
            output = state.get("output", "")

            if tool == "bash":
                cmd = inp.get("command", "")
                if cmd:
                    console.print(f"  [bold yellow]└─ $ {cmd}[/bold yellow]")
                if output:
                    lines = output.strip().split("\n")
                    if len(lines) <= 12 and len(output) < 600:
                        for l in lines:
                            console.print(f"  [dim]{l}[/dim]")
                    else:
                        console.print(f"  [dim]   ── {len(lines)} lines, {len(output)} chars ──[/dim]")

            elif tool in ("read", "write", "edit"):
                fp = inp.get("filePath", inp.get("file_path", ""))
                if fp:
                    icon = "📖" if tool == "read" else "✏️"
                    console.print(f"  [dim]{icon} {tool} {fp}[/dim]")

            elif tool in ("grep", "glob", "websearch", "webfetch"):
                icon = "🔍" if tool in ("grep", "glob") else "🌐"
                pat = inp.get("pattern", "") or inp.get("query", "") or ""
                if pat:
                    console.print(f"  [dim]{icon} {tool} {pat}[/dim]")
                if output and len(output) < 400:
                    console.print(f"  [dim]{output.strip()[:400]}[/dim]")
                elif output:
                    console.print(f"  [dim]   ({len(output)} chars returned)[/dim]")

            else:
                console.print(f"  [dim]🔧 {tool}[/dim]")

        elif etype == "error":
            console.print(f"  [red]✗ {part.get('text', 'error')}[/red]")

    def _chat_help(self):
        console.print(Panel(
            Text.from_markup(
                "[bold]/back[/bold]       — Return to main menu\n"
                "[bold]/history[/bold]    — Show full conversation\n"
                "[bold]/clear[/bold]      — Clear conversation history\n"
                "[bold]/model <id>[/bold] — Switch model (e.g., /model anthropic/claude-sonnet-4-5)\n"
                "[bold]/variant <v>[/bold]— Switch variant (low/medium/high/max)\n"
                "[bold]/help[/bold]       — This message\n\n"
                "[dim]Any other text is sent as a message to OpenCode.[/dim]"
            ),
            title="Chat Commands",
            box=ROUNDED,
            border_style="blue",
        ))
        Prompt.ask("\n[dim]Press Enter to continue[/dim]")

    def _show_full_history(self, messages: list):
        self.banner()
        console.print("[bold underline]Full Conversation History:[/bold underline]\n")
        if not messages:
            console.print("[dim]No messages yet.[/dim]")
        for i, m in enumerate(messages, 1):
            prefix = "[bold green]You >[/bold green]" if m.role == "user" else "[bold]Klyra >[/bold]"
            console.print(f"[dim]{i}.[/dim] {prefix}")
            console.print(f"   {m.content}")
            console.print()
        Prompt.ask("\n[dim]Press Enter to continue[/dim]")

    def open_session_flow(self):
        sessions = self.sm.list_sessions()
        if not sessions:
            console.print("[yellow]No sessions to open.[/yellow]")
            Prompt.ask("\n[dim]Press Enter[/dim]")
            return

        self.banner()
        console.print("[bold cyan]╔══ Open Session ══╗[/bold cyan]\n")

        for i, s in enumerate(sessions, 1):
            console.print(f"  [bold]{i}.[/bold] [cyan]{s.name}[/cyan] — {s.model.split('/')[-1][:20]} — {s.message_count} msgs")
        console.print()

        choice = Prompt.ask("[bold]Select session[/bold]", default="1")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                self.chat_loop(sessions[idx])
            else:
                console.print("[red]Invalid selection[/red]")
        except ValueError:
            console.print("[red]Invalid number[/red]")
        Prompt.ask("\n[dim]Press Enter[/dim]")

    def delete_session_flow(self):
        sessions = self.sm.list_sessions()
        if not sessions:
            console.print("[yellow]No sessions to delete.[/yellow]")
            Prompt.ask("\n[dim]Press Enter[/dim]")
            return

        self.banner()
        console.print("[bold red]╔══ Delete Session ══╗[/bold red]\n")

        for i, s in enumerate(sessions, 1):
            console.print(f"  [bold]{i}.[/bold] [cyan]{s.name}[/cyan] — {s.message_count} msgs — {s.id[:12]}...")
        console.print()

        choice = Prompt.ask("[bold]Delete #[/bold] (or 'all')", default="")
        if choice.lower() == "all":
            if Confirm.ask("[bold red]Delete ALL sessions?[/bold red]", default=False):
                for s in sessions:
                    self.sm.delete_session(s.id)
                console.print(f"[green]✓ Deleted {len(sessions)} sessions[/green]")
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(sessions):
                    s = sessions[idx]
                    if Confirm.ask(f"Delete [cyan]{s.name}[/cyan]?", default=False):
                        self.sm.delete_session(s.id)
                        console.print(f"[green]✓ Deleted {s.name}[/green]")
            except (ValueError, IndexError):
                console.print("[red]Invalid selection[/red]")
        Prompt.ask("\n[dim]Press Enter[/dim]")

    def set_model_flow(self):
        global DEFAULT_MODEL
        self.banner()
        console.print("[bold yellow]╔══ Model Configuration ══╗[/bold yellow]\n")
        console.print("[dim]Format: provider/model (empty = opencode default)[/dim]")
        console.print("[dim]Available opencode models:[/dim]")
        console.print("[dim]  opencode/deepseek-v4-flash-free, opencode/nemotron-3-ultra-free[/dim]")
        console.print("[dim]  opencode/north-mini-code-free, opencode/mimo-v2.5-free[/dim]")
        console.print("[dim]External: anthropic/claude-sonnet-4-5, openai/gpt-5, etc.[/dim]\n")

        model = Prompt.ask("[bold]Default model[/bold]", default=DEFAULT_MODEL or "opencode/deepseek-v4-flash-free")
        variant = Prompt.ask(
            "[bold]Default variant[/bold]",
            default="high",
            choices=MODEL_VARIANTS,
        )

        DEFAULT_MODEL = model

        console.print(f"\n[green]✓ Default model set to {model} ({variant})[/green]")
        Prompt.ask("\n[dim]Press Enter[/dim]")

    def list_models_flow(self):
        self.banner()
        console.print("[bold cyan]╔══ Available Models ══╗[/bold cyan]\n")
        with console.status("[bold green]Fetching models..."):
            try:
                result = subprocess.run(
                    [OPENCODE_PATH, "models", "opencode"],
                    capture_output=True, text=True, timeout=15,
                    env={**os.environ, "PATH": os.environ.get("PATH", "")},
                )
                if result.returncode == 0:
                    models = [m.strip() for m in result.stdout.strip().split("\n") if m.strip()]
                    if models:
                        table = Table(box=ROUNDED, header_style="bold cyan")
                        table.add_column("Provider", style="yellow")
                        table.add_column("Model", style="bold")
                        for m in models:
                            parts = m.split("/", 1)
                            prov = parts[0] if len(parts) > 1 else "opencode"
                            model_name = parts[1] if len(parts) > 1 else m
                            table.add_row(prov, model_name)
                        console.print(table)
                    else:
                        console.print("[dim]No models found for opencode provider.[/dim]")
                else:
                    console.print(f"[red]Error fetching models: {result.stderr[:200]}[/red]")
            except subprocess.TimeoutExpired:
                console.print("[red]Timed out fetching models.[/red]")
            except FileNotFoundError:
                console.print("[red]opencode binary not found.[/red]")

        console.print("\n[dim]Use option [bold]4[/bold] to set a default model.[/dim]")
        console.print("[dim]Provider/model format:[/dim] [italic]anthropic/claude-sonnet-4-5[/italic]")
        Prompt.ask("\n[dim]Press Enter[/dim]")

    def stats_flow(self):
        sessions = self.sm.list_sessions()
        self.banner()
        console.print("[bold cyan]╔══ Statistics ══╗[/bold cyan]\n")

        total_cost = sum(s.total_cost for s in sessions)
        total_msgs = sum(s.message_count for s in sessions)

        table = Table(box=ROUNDED, header_style="bold cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value")

        table.add_row("Total Sessions", str(len(sessions)))
        table.add_row("Total Messages", str(total_msgs))
        table.add_row("Total Cost", f"${total_cost:.4f}")
        table.add_row("Active (last 5m)", str(sum(1 for s in sessions if self._is_active(s))))
        table.add_row("Sessions Dir", str(SESSIONS_DIR))
        table.add_row("Model Default", DEFAULT_MODEL)

        console.print(table)

        if sessions:
            console.print("\n[bold underline]Per-Session Breakdown:[/bold underline]")
            for s in sessions:
                console.print(
                    f"  [cyan]{s.name}[/cyan] — {s.message_count} msgs, "
                    f"${s.total_cost:.4f}, last active {s.last_active.split('T')[1][:8]}"
                )

        Prompt.ask("\n[dim]Press Enter[/dim]")


# ─── Entry ───────────────────────────────────────────────────────────────

def main():
    try:
        cli = CLI()
        cli.main_menu()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Session closed.[/yellow]")
        sys.exit(0)

if __name__ == "__main__":
    main()
