#!/usr/bin/env python3
"""
Kaggle GPU OCR Server - 12-Hour Headless Mode
Can be run directly as a script on Kaggle or pasted into a single Kaggle Notebook cell.

Run headless without keeping browser open:
1. Turn GPU ON (T4 x2 or P100)
2. Turn Internet ON
3. Click "Save Version" -> "Save & Run All (Commit)"
4. Close your browser tab or computer!
5. On your laptop, run: ./update_ocr_url.sh --sync
"""

import os
import re
import sys
import time
import shutil
import platform
import tempfile
import requests
import subprocess
import threading
from pathlib import Path

# ==============================================================================
# 0. AUTOMATIC DEPENDENCY INSTALLATION (PaddlePaddle GPU + PaddleOCR)
# ==============================================================================
def install_dependencies():
    print("Checking / Installing PaddlePaddle GPU & PaddleOCR...")
    try:
        import paddle
        import paddleocr
        print("✓ Paddle & PaddleOCR already installed.")
        return
    except ImportError:
        pass

    print("Uninstalling conflicting torch...")
    subprocess.run(["pip", "uninstall", "-y", "torch", "torchvision"], check=False)

    # Detect CUDA
    cu_suffix = "cu120"
    try:
        smi_out = subprocess.check_output(["nvidia-smi"]).decode("utf-8")
        match = re.search(r"CUDA Version:\s*(\d+\.\d+)", smi_out)
        if match:
            v = match.group(1)
            parts = v.split(".")
            maj, min_ = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            if maj == 11:
                cu_suffix = "cu118"
            elif maj == 12 and min_ >= 2:
                cu_suffix = "cu122" if min_ < 6 else "cu126"
    except Exception:
        pass

    print(f"Installing PaddlePaddle-GPU ({cu_suffix})...")
    subprocess.run([
        "pip", "install", "--default-timeout=1000", "paddlepaddle-gpu",
        "-i", f"https://www.paddlepaddle.org.cn/packages/stable/{cu_suffix}/"
    ], check=False)

    print("Installing PaddleOCR 3.7.0...")
    subprocess.run(["pip", "install", "paddleocr==3.7.0", "flask"], check=False)

install_dependencies()

import cv2
import numpy as np
from flask import Flask, request, jsonify
from paddleocr import PaddleOCR

# ==============================================================================
# 1. NOTIFICATION & 12-HOUR SETTINGS
# ==============================================================================
NOTIFY_CHANNEL = os.environ.get("NOTIFY_CHANNEL", "onebhoomi_ocr_tunnel")
MAX_RUNTIME_HOURS = 11.5

def broadcast_url(url: str, note: str = "Server Online"):
    if not NOTIFY_CHANNEL:
        return
    endpoint = f"https://ntfy.sh/{NOTIFY_CHANNEL}"
    try:
        requests.post(
            endpoint,
            data=url.encode("utf-8"),
            headers={
                "Title": f"Kaggle GPU OCR ({note})",
                "Tags": "rocket,gpu,computer",
                "Priority": "high"
            },
            timeout=10
        )
        print(f"✓ Broadcasted live URL to {endpoint}")
    except Exception as exc:
        print(f"Notification broadcast note: {exc}")

# ==============================================================================
# 2. TUNNEL SUPERVISOR
# ==============================================================================
_CLOUDFLARED_BINARY_URLS = {
    "x86_64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "amd64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "aarch64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    "arm64": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
}

active_tunnel_proc = None

def _stream_until_url(proc, patterns, timeout_s=120):
    global active_tunnel_proc
    active_tunnel_proc = proc
    if proc.stdout is None:
        raise RuntimeError("Tunnel process stdout is not available.")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line:
            print(line, end="")
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    return match.group(0)
        elif proc.poll() is not None:
            break
        else:
            time.sleep(0.2)
    raise TimeoutError("Timed out while waiting for a public tunnel URL.")

def _download_cloudflared_binary():
    machine = platform.machine().lower()
    asset_url = _CLOUDFLARED_BINARY_URLS.get(machine)
    if not asset_url:
        raise RuntimeError(f"Unsupported architecture for cloudflared: {machine}")
    target_dir = Path(tempfile.gettempdir()) / "codex-cloudflared"
    target_dir.mkdir(parents=True, exist_ok=True)
    binary_path = target_dir / "cloudflared"
    if binary_path.exists():
        return str(binary_path)
    print(f"Downloading cloudflared from {asset_url}...")
    response = requests.get(asset_url, timeout=120)
    response.raise_for_status()
    binary_path.write_bytes(response.content)
    binary_path.chmod(0o755)
    return str(binary_path)

def expose_port(port: int = 5000) -> str:
    binary = shutil.which("cloudflared") or _download_cloudflared_binary()
    print("Starting cloudflared quick tunnel...")
    proc = subprocess.Popen(
        [binary, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    url = _stream_until_url(proc, [re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", re.IGNORECASE)])
    print(f"\nPublic OCR URL: {url}")
    return url

# ==============================================================================
# 3. PADDLEOCR ENGINE & FLASK APP
# ==============================================================================
print("Initializing PaddleOCR engine with GPU...")
ocr = PaddleOCR(
    det_limit_side_len=1536,
    device='gpu',
    lang='en',
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False
)
ocr_lock = threading.Lock()
print("PaddleOCR GPU engine initialized successfully!")

gpu_name = "NVIDIA GPU"
try:
    smi_out = subprocess.check_output(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).decode("utf-8")
    gpu_name = smi_out.strip()
except Exception:
    pass

app = Flask(__name__)

@app.route("/", methods=["GET"])
@app.route("/status", methods=["GET"])
def status_endpoint():
    return jsonify({"status": "connected", "gpu_name": gpu_name})

@app.route("/ocr", methods=["POST"])
def ocr_endpoint():
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400
    file = request.files["image"]
    img_bytes = file.read()
    nparr = np.frombuffer(img_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        return jsonify({"error": "Failed to decode image"}), 400
    with ocr_lock:
        start_time = time.perf_counter()
        result = ocr.predict(image)[0]
        ocr_time = (time.perf_counter() - start_time) * 1000
    rec_polys_list = [poly.tolist() for poly in result["rec_polys"]]
    return jsonify({
        "rec_texts": result["rec_texts"],
        "rec_scores": [float(s) for s in result["rec_scores"]],
        "rec_polys": rec_polys_list,
        "ocr_time_ms": ocr_time,
        "gpu_name": gpu_name
    })

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()
time.sleep(2)
print("Flask server running on port 5000.")

public_url = expose_port(5000)
broadcast_url(public_url, note="Server Ready")

# ==============================================================================
# 4. 12-HOUR SUPERVISOR LOOP
# ==============================================================================
deadline = time.time() + (MAX_RUNTIME_HOURS * 3600)
print("\n" + "=" * 65)
print(" 🚀 KAGGLE 12-HOUR HEADLESS OCR BACKEND IS RUNNING")
print("=" * 65)
print(f" • Public Tunnel URL: {public_url}")
print(f" • Sync Channel:     https://ntfy.sh/{NOTIFY_CHANNEL}")
print(f" • Planned Runtime:  {MAX_RUNTIME_HOURS} hours")
print(" • You can close your browser tab or turn off your PC safely!")
print(f" • Local sync:       ./update_ocr_url.sh --sync")
print("=" * 65 + "\n")

loop_count = 0
try:
    while time.time() < deadline:
        time.sleep(60)
        loop_count += 1

        if active_tunnel_proc and active_tunnel_proc.poll() is not None:
            print("⚠️ Tunnel dropped! Re-establishing...")
            try:
                public_url = expose_port(5000)
                broadcast_url(public_url, note="Tunnel Reconnected")
            except Exception as e:
                print(f"Tunnel restart attempt failed: {e}")

        if loop_count % 10 == 0:
            elapsed_m = loop_count
            remain_m = max(0, int((deadline - time.time()) / 60))
            try:
                st = requests.get("http://127.0.0.1:5000/status", timeout=5).json()
                st_desc = f"OK ({st.get('gpu_name', 'GPU Online')})"
            except Exception as ex:
                st_desc = f"Warning: {ex}"
            print(f"[{time.strftime('%H:%M:%S')}] Active: {elapsed_m}m / {remain_m}m remaining | Local: {st_desc}")

        if loop_count % 60 == 0:
            broadcast_url(public_url, note=f"Active ({loop_count // 60}h)")

    print("Execution completed.")
except KeyboardInterrupt:
    print("Stopped by user.")
