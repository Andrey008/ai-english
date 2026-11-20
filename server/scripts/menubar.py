"""macOS menu-bar control for the ai-english server.

    cd server && uv run --group menubar python scripts/menubar.py

Start / Stop / Restart the server (under `caffeinate -i`, so the Mac
doesn't idle-sleep mid-conversation), with its log in
`server/logs/server.log`. Before a start it can unload every *other*
Ollama model from memory (gemma2:27b needs ~16GB, a second 27B model
next to it pushes the Mac into swap and turns 1.5s replies into 20-30s).
It also lists the processes using the most memory, for information only;
it never kills anything except the server it controls.

`scripts/install_menubar.sh` registers it as a login item (LaunchAgent).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil
import rumps

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
from app.config import load_config  # noqa: E402

HOST, PORT = "0.0.0.0", 8000
HEALTH_URL = f"http://127.0.0.1:{PORT}/healthz"
OLLAMA_URL = "http://127.0.0.1:11434"
LOG_DIR = SERVER_DIR / "logs"
LOG_PATH = LOG_DIR / "server.log"
REFRESH_S = 3.0
STOP_GRACE_S = 15.0
# Processes above this resident size show up under "Memory".
BIG_PROCESS_BYTES = 1_000_000_000

ICONS = {"stopped": "⚪", "starting": "🟡", "warming": "🟡", "ready": "🟢", "error": "🔴"}


def notify(subtitle: str, message: str) -> None:
    """A banner if macOS lets this (bundle-less) Python show one, else the log."""
    try:
        rumps.notification("ai-english", subtitle, message)
    except Exception:
        print(f"{subtitle}: {message}", flush=True)


def gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB"


def our_models() -> set[str]:
    llm = load_config().get("llm", {})
    return {m for m in (llm.get("model"), llm.get("learning_layer_model")) if m}


def _same_model(a: str, b: str) -> bool:
    norm = lambda m: m if ":" in m else f"{m}:latest"  # noqa: E731
    return norm(a) == norm(b)


def ollama_loaded() -> list[dict] | None:
    """Models Ollama has in memory, or None if Ollama isn't running."""
    try:
        return httpx.get(f"{OLLAMA_URL}/api/ps", timeout=1.0).json().get("models", [])
    except Exception:
        return None


def ollama_unload(name: str) -> None:
    httpx.post(f"{OLLAMA_URL}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30.0)


def server_healthy() -> bool:
    try:
        return httpx.get(HEALTH_URL, timeout=0.5).status_code == 200
    except Exception:
        return False


def find_server_pids() -> list[int]:
    """uvicorn processes serving this app, also ones started from a terminal."""
    pids = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if "uvicorn" in cmd and "app.main:app" in cmd and "caffeinate" not in cmd and " uv run" not in f" {cmd}":
            pids.append(p.info["pid"])
    return pids


def big_processes(limit: int = 6) -> list[tuple[str, int]]:
    rows = []
    for p in psutil.process_iter(["name", "memory_info"]):
        mem = p.info["memory_info"]
        if mem and mem.rss >= BIG_PROCESS_BYTES:
            rows.append((p.info["name"] or "?", mem.rss))
    rows.sort(key=lambda r: -r[1])
    return rows[:limit]


class ServerApp(rumps.App):
    def __init__(self):
        super().__init__("ai-english", title=ICONS["stopped"], quit_button=None)
        self.proc: subprocess.Popen | None = None
        self.log_file = None
        self.state = "stopped"
        self.busy = False  # a start/stop is in progress on a worker thread

        self.status_item = rumps.MenuItem("Server: stopped")
        self.model_item = rumps.MenuItem("Model: —")
        self.start_item = rumps.MenuItem("Start", callback=self.on_start)
        self.stop_item = rumps.MenuItem("Stop", callback=self.on_stop)
        self.restart_item = rumps.MenuItem("Restart", callback=self.on_restart)
        self.free_item = rumps.MenuItem("Unload other models before start", callback=self.on_toggle_free)
        self.free_item.state = 1
        self.unload_item = rumps.MenuItem("Unload other models now", callback=self.on_unload_now)
        self.memory_menu = rumps.MenuItem("Memory")
        self.memory_menu.add(rumps.MenuItem("…"))
        self.menu = [
            self.status_item, self.model_item, None,
            self.start_item, self.stop_item, self.restart_item, None,
            self.free_item, self.unload_item, self.memory_menu, None,
            rumps.MenuItem("Open log", callback=self.on_open_log),
            rumps.MenuItem("Quit (stops the server)", callback=self.on_quit),
        ]
        self.timer = rumps.Timer(self.refresh, REFRESH_S)
        self.timer.start()
        self.refresh(None)

    # --- status -------------------------------------------------------

    def refresh(self, _):
        loaded = ollama_loaded()
        wanted = our_models()
        healthy = server_healthy()
        running = bool(self.proc and self.proc.poll() is None) or bool(find_server_pids())
        ours_loaded = loaded is not None and any(_same_model(m["name"], w) for m in loaded for w in wanted)

        if self.busy:
            pass
        elif not running:
            self.state = "error" if self.proc and self.proc.poll() not in (None, 0, -2, -15) else "stopped"
        elif not healthy:
            self.state = "starting"
        else:
            self.state = "ready" if ours_loaded else "warming"
        self.title = ICONS[self.state]

        external = running and not (self.proc and self.proc.poll() is None)
        self.status_item.title = {
            "stopped": "Server: stopped",
            "starting": "Server: starting…",
            "warming": "Server: up, loading the model…",
            "ready": "Server: ready",
            "error": f"Server: exited with code {self.proc.returncode if self.proc else '?'} (see log)",
        }[self.state] + (" (started from a terminal)" if external else "")

        if loaded is None:
            self.model_item.title = "Ollama: not running"
        else:
            parts = [f"{m['name']} {gb(m.get('size', 0))}" for m in loaded]
            self.model_item.title = "Ollama: " + (", ".join(parts) if parts else "nothing loaded")
        others = [m for m in (loaded or []) if not any(_same_model(m["name"], w) for w in wanted)]
        self.unload_item.title = f"Unload other models now ({len(others)})"
        self.unload_item.set_callback(self.on_unload_now if others else None)

        self.start_item.set_callback(None if running or self.busy else self.on_start)
        self.stop_item.set_callback(self.on_stop if running and not self.busy else None)
        self.restart_item.set_callback(self.on_restart if running and not self.busy else None)
        self._refresh_memory()

    def _refresh_memory(self):
        vm = psutil.virtual_memory()
        self.memory_menu.title = f"Memory: {gb(vm.available)} free of {gb(vm.total)}"
        self.memory_menu.clear()
        for name, rss in big_processes():
            self.memory_menu.add(rumps.MenuItem(f"{name} — {gb(rss)}"))
        if not self.memory_menu.keys():
            self.memory_menu.add(rumps.MenuItem("no process over 1 GB"))

    # --- actions ------------------------------------------------------

    def _in_background(self, state: str, fn):
        if self.busy:
            return
        self.busy, self.state, self.title = True, state, ICONS[state]

        def run():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 — shown to the user
                notify("Action failed", str(exc))
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    def _unload_others(self) -> list[str]:
        wanted = our_models()
        unloaded = []
        for m in ollama_loaded() or []:
            if not any(_same_model(m["name"], w) for w in wanted):
                ollama_unload(m["name"])
                unloaded.append(m["name"])
        return unloaded

    def _start(self):
        if self.free_item.state:
            if unloaded := self._unload_others():
                notify("Freed memory", "Unloaded: " + ", ".join(unloaded))
        LOG_DIR.mkdir(exist_ok=True)
        if LOG_PATH.exists():
            LOG_PATH.replace(LOG_DIR / "server.prev.log")
        self.log_file = LOG_PATH.open("ab", buffering=0)
        self.proc = subprocess.Popen(
            ["caffeinate", "-i", sys.executable, "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", str(PORT)],
            cwd=SERVER_DIR, stdout=self.log_file, stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group: Stop reaches whisper-server too
        )

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            pgid = os.getpgid(self.proc.pid)
            os.killpg(pgid, signal.SIGINT)  # uvicorn shuts down cleanly on Ctrl+C
            try:
                self.proc.wait(STOP_GRACE_S)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                self.proc.wait()
        for pid in find_server_pids():  # one started from a terminal
            try:
                proc = psutil.Process(pid)
                proc.send_signal(signal.SIGINT)
                proc.wait(STOP_GRACE_S)
            except psutil.TimeoutExpired:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def on_start(self, _):
        self._in_background("starting", self._start)

    def on_stop(self, _):
        self._in_background("starting", self._stop)

    def on_restart(self, _):
        self._in_background("starting", lambda: (self._stop(), self._start()))

    def on_toggle_free(self, item):
        item.state = 0 if item.state else 1

    def on_unload_now(self, _):
        def run():
            unloaded = self._unload_others()
            notify("Freed memory", "Unloaded: " + (", ".join(unloaded) or "nothing"))
        threading.Thread(target=run, daemon=True).start()

    def on_open_log(self, _):
        LOG_DIR.mkdir(exist_ok=True)
        LOG_PATH.touch()
        subprocess.Popen(["open", "-a", "Console", str(LOG_PATH)])

    def on_quit(self, _):
        self._stop()
        rumps.quit_application()


def main() -> None:
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    # Menu bar only: no Dock icon, no app switcher entry.
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    ServerApp().run()


if __name__ == "__main__":
    main()
