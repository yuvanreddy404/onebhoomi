#!/usr/bin/env python3
"""
Script to update Kaggle/Colab OCR URL and automatically refresh/restart web_app.py.

Usage:
    python update_ocr_url.py <URL>
    python update_ocr_url.py
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
COLAB_TXT_PATH = BASE_DIR / "colab_url.txt"
WEB_APP_PY = BASE_DIR / "web_app.py"
PORT = int(os.environ.get("PORT", 8001))

venv_candidates = [
    BASE_DIR / ".venv" / "Scripts" / "python.exe",
    BASE_DIR / ".venv" / "bin" / "python3",
    BASE_DIR / ".venv" / "bin" / "python",
]
VENV_PYTHON = next((p for p in venv_candidates if p.exists()), None)
PYTHON_BIN = str(VENV_PYTHON) if VENV_PYTHON else sys.executable


def extract_url(text: str) -> str:
    text = text.strip().strip("'\"")
    match = re.search(r"https?://[^\s'\"]+", text)
    if match:
        return match.group(0).rstrip("/")
    if "." in text and not text.startswith("http"):
        return f"https://{text.rstrip('/')}"
    return text.rstrip("/")


def check_remote_ocr(url: str, timeout: int = 5) -> dict:
    status_url = f"{url}/status"
    try:
        resp = requests.get(status_url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            gpu_name = data.get("gpu_name", "GPU Online")
            return {"ok": True, "gpu_name": gpu_name, "status_code": 200}
        return {"ok": False, "status_code": resp.status_code, "error": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_running_server_pids() -> list[int]:
    pids = []
    my_pid = os.getpid()

    # 1. Cross-platform using psutil if available
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == PORT:
                if conn.pid and conn.pid != my_pid and conn.pid not in pids:
                    pids.append(conn.pid)
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                cmdline_str = " ".join(cmdline).lower()
                if "web_app.py" in cmdline_str and proc.info["pid"] != my_pid:
                    if proc.info["pid"] not in pids:
                        pids.append(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if pids:
            return pids
    except Exception:
        pass

    # 2. Windows fallback
    if sys.platform == "win32":
        try:
            res = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 5 and parts[0].upper() == "TCP":
                        local_addr = parts[1]
                        state = parts[3]
                        pid_str = parts[4]
                        if local_addr.endswith(f":{PORT}") and state.upper() in ("LISTENING", "ESTABLISHED") and pid_str.isdigit():
                            p = int(pid_str)
                            if p not in pids and p != my_pid:
                                pids.append(p)
        except Exception:
            pass
    else:
        # 3. Unix fallback
        try:
            res = subprocess.run(["lsof", "-t", f"-i:{PORT}"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().splitlines():
                    if line.isdigit():
                        p = int(line)
                        if p not in pids and p != my_pid:
                            pids.append(p)
        except Exception:
            pass

        try:
            res = subprocess.run(["pgrep", "-f", "web_app.py"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().splitlines():
                    if line.isdigit():
                        p = int(line)
                        if p not in pids and p != my_pid:
                            pids.append(p)
        except Exception:
            pass

    return pids


def stop_server() -> None:
    pids = get_running_server_pids()
    for pid in pids:
        try:
            if sys.platform == "win32":
                killed = False
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    killed = True
                except Exception:
                    pass
                if not killed:
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            print(f"Warning stopping PID {pid}: {e}")
    if pids:
        time.sleep(0.6)


def start_server() -> subprocess.Popen:
    log_file = BASE_DIR / "server.log"
    out_f = open(log_file, "a", encoding="utf-8", errors="replace")
    kwargs = {
        "cwd": str(BASE_DIR),
        "stdout": out_f,
        "stderr": out_f,
    }
    if sys.platform == "win32":
        # 0x00000008 DETACHED_PROCESS + 0x00000200 CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        [PYTHON_BIN, "-u", str(WEB_APP_PY)],
        **kwargs,
    )
    return proc


def wait_for_server(timeout: float = 6.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"http://localhost:{PORT}/", timeout=1)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


DEFAULT_CHANNEL = "onebhoomi_ocr_tunnel"


def fetch_url_from_channel(channel: str = DEFAULT_CHANNEL) -> str | None:
    endpoint = f"https://ntfy.sh/{channel}/raw?poll=1"
    print(f"📡 Querying sync channel: {endpoint}...")
    try:
        resp = requests.get(endpoint, timeout=8)
        if resp.status_code == 200 and resp.text.strip():
            # Get latest line
            lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
            for line in reversed(lines):
                url = extract_url(line)
                if url.startswith("http"):
                    return url
    except Exception as exc:
        print(f"      ⚠️  Error contacting sync channel: {exc}")
    return None


def update_server_in_place(ocr_url: str) -> bool:
    """Hot-updates running web_app.py without restart."""
    try:
        resp = requests.get(f"http://localhost:{PORT}/set_ocr_url", params={"url": ocr_url}, timeout=3)
        if resp.status_code == 200:
            return True
    except Exception:
        pass
    return False


def main():
    print("=" * 60)
    print(" 🚀 Kaggle / Colab OCR URL Updater & Web App Manager")
    print("=" * 60)

    sync_mode = False
    channel = DEFAULT_CHANNEL
    target_arg = None

    args = sys.argv[1:]
    if "--sync" in args or "-s" in args:
        sync_mode = True
        # Check if channel name provided after --sync
        for i, a in enumerate(args):
            if a in ("--sync", "-s") and i + 1 < len(args) and not args[i + 1].startswith("-"):
                channel = args[i + 1]
    elif args and not args[0].startswith("-"):
        target_arg = " ".join(args)

    if sync_mode:
        print(f"🔄 Headless Sync Mode: Fetching URL from '{channel}'...")
        fetched = fetch_url_from_channel(channel)
        if not fetched:
            print(f"❌ Could not retrieve URL from channel https://ntfy.sh/{channel}")
            print("   Make sure your Kaggle notebook has started (Cell 3).")
            return 1
        raw_input = fetched
        print(f"   ✓ Received URL: {raw_input}")
    elif target_arg:
        raw_input = target_arg
    else:
        try:
            print(f"Options:")
            print(f" [1] Type or paste a Kaggle/Colab URL (e.g. https://xxxx.trycloudflare.com)")
            print(f" [2] Type 's' or press ENTER to sync automatically from '{channel}'")
            choice = input("\n👉 Enter URL (or 's' to auto-sync): ").strip()
            if not choice or choice.lower() in ("s", "sync"):
                fetched = fetch_url_from_channel(channel)
                if not fetched:
                    print(f"❌ Could not retrieve URL from channel https://ntfy.sh/{channel}")
                    return 1
                raw_input = fetched
                print(f"   ✓ Received URL: {raw_input}")
            else:
                raw_input = choice
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 1

    ocr_url = extract_url(raw_input)
    parsed = urlparse(ocr_url)
    if not parsed.scheme or not parsed.netloc:
        print(f"❌ Error: Invalid URL format: '{ocr_url}'")
        return 1

    print(f"\n[1/4] Target OCR URL: {ocr_url}")

    # 2. Test Remote OCR Connectivity
    print("[2/4] Testing connection to remote OCR endpoint...")
    status = check_remote_ocr(ocr_url)
    if status.get("ok"):
        gpu_name = status.get("gpu_name", "Remote GPU")
        print(f"      ✅ Connection Verified! Remote GPU: {gpu_name}")
    else:
        err = status.get("error", "Unreachable")
        print(f"      ⚠️  Warning: Remote /status check failed ({err})")
        print("         The URL will still be saved. Ensure your Kaggle notebook is running.")

    # 3. Save to colab_url.txt
    print(f"[3/4] Writing URL to {COLAB_TXT_PATH.name}...")
    COLAB_TXT_PATH.write_text(ocr_url, encoding="utf-8")
    print("      ✅ Saved successfully.")

    # 4. Refresh / Restart web_app.py
    print("[4/4] Updating web_app.py...")
    # Try hot-update first (zero downtime)
    hot_updated = update_server_in_place(ocr_url)
    if hot_updated:
        print("      ⚡ Live Hot-Update Successful! No restart needed.")
        is_ready = True
    else:
        running_pids = get_running_server_pids()
        if running_pids:
            print(f"      Restarting running server process (PID: {running_pids})...")
            stop_server()
        else:
            print("      Starting web_app.py server...")

        start_server()
        is_ready = wait_for_server(timeout=6.0)

    print("\n" + "=" * 60)
    if is_ready:
        print(" ✅ SUCCESS: Server synced and active with Remote GPU!")
    else:
        print(" ⚠️  Server updated, but local port verification timed out.")

    print(f" • Local Web App:     http://localhost:{PORT}")
    print(f" • Active OCR Tunnel: {ocr_url}")
    print(f" • Config File:       {COLAB_TXT_PATH}")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

