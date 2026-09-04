#!/usr/bin/env python3
import os
import re
import sys
import time
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TXT_PATH = BASE_DIR / "web_tunnel_url.txt"
PORT = int(os.environ.get("PORT", 8001))

def find_cloudflared() -> str:
    import shutil
    candidates = [
        BASE_DIR / "cloudflared.exe",
        BASE_DIR / "scratch" / "cloudflared.exe",
        BASE_DIR / "cloudflared",
        shutil.which("cloudflared.exe"),
        shutil.which("cloudflared"),
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return str(cand)
    return "cloudflared"

def main():
    cf_bin = find_cloudflared()
    print(f"Starting Cloudflare Public Tunnel for Web Server (port {PORT}) using {cf_bin}...")
    proc = subprocess.Popen(
        [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url_pattern = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", re.IGNORECASE)
    public_url = None

    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            match = url_pattern.search(line)
            if match:
                public_url = match.group(0)
                break
        elif proc.poll() is not None:
            break
        time.sleep(0.1)

    if not public_url:
        print("❌ Failed to get Cloudflare tunnel URL.")
        return 1

    print(f"✅ Public Cloudflare Web Tunnel Live: {public_url}")
    TXT_PATH.write_text(public_url, encoding="utf-8")
    print(f"Wrote URL to {TXT_PATH.name}")

    # Keep process running to maintain tunnel active
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return 0

if __name__ == "__main__":
    sys.exit(main())
