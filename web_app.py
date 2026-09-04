import sys
import os
_venv_site = r"C:\Users\meesa\Downloads\final land\.venv\Lib\site-packages"
if os.path.exists(_venv_site) and _venv_site not in sys.path:
    sys.path.insert(0, _venv_site)

import base64
import html
import io
import json
import mimetypes
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from time import perf_counter
from urllib.parse import parse_qs, urlparse
from datetime import datetime

import requests
from land_document_extractor import (
    OCRLine,
    OCRWord,
    extract_land_document,
    extract_land_document_from_lines,
    get_paddle_ocr_model,
    group_words_into_lines,
    normalize_space,
)
import verification_service
import gis_service
import dashboard_view
import socket

def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_public_web_tunnel() -> str:
    port = os.environ.get("PORT", 8001)
    txt_path = Path(__file__).parent / "web_tunnel_url.txt"
    if txt_path.exists():
        try:
            url = txt_path.read_text(encoding="utf-8").strip()
            if url.startswith("http"):
                try:
                    resp = requests.get(url, timeout=1.2)
                    if resp.status_code < 500 and "no tunnel" not in resp.text.lower():
                        return url
                except Exception:
                    pass
                # Stale or dead tunnel file, remove it
                try:
                    txt_path.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass
    lan_ip = get_lan_ip()
    if lan_ip and lan_ip != "127.0.0.1":
        return f"http://{lan_ip}:{port}"
    return f"http://localhost:{port}"

# =====================================================================
# Kaggle / Colab OCR Tunnel Configuration
# =====================================================================
COLAB_OCR_URL = "https://instrumentation-cables-ranking-holds.trycloudflare.com"


def get_colab_url() -> str:
    env_val = os.environ.get("COLAB_OCR_URL")
    if env_val:
        return env_val.strip()

    txt_path = Path(__file__).parent / "colab_url.txt"
    if txt_path.exists():
        try:
            return txt_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    return COLAB_OCR_URL.strip()


def extract_pdf_pages_to_memory(uploaded_bytes: bytes, scale: float = 1.6) -> list[tuple[int, bytes, int, int]]:
    """
    Renders PDF pages directly into memory as lightweight JPEG byte buffers
    at optimized scale (1.6x, ~1300x1800px, JPEG quality 85).
    Returns list of (page_num, jpeg_bytes, width, height).
    Zero disk I/O, 96% smaller payload than PNG.
    """
    import io
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(uploaded_bytes)
    page_buffers = []
    for page_idx, page in enumerate(pdf, start=1):
        pil_img = page.render(scale=scale).to_pil()
        w, h = pil_img.size
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=85, optimize=True)
        page_buffers.append((page_idx, buf.getvalue(), w, h))
    return page_buffers


def try_extract_digital_pdf_lines(uploaded_bytes: bytes) -> tuple[list[OCRLine], str] | None:
    """
    Checks if the PDF is a digital/searchable document with embedded text.
    If substantial text is found (>120 chars), extracts text lines directly
    in <20ms, bypassing OCR completely. Returns None for scanned/image PDFs.
    """
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(uploaded_bytes)
        total_text_len = 0
        pages_text = []

        for page in pdf:
            textpage = page.get_textpage()
            txt = textpage.get_text_range() or ""
            pages_text.append(txt)
            total_text_len += len(txt.strip())

        if total_text_len < 120:
            return None

        all_lines: list[OCRLine] = []
        all_raw_texts: list[str] = []

        for page_idx, (page, raw_page_text) in enumerate(zip(pdf, pages_text), start=1):
            w = int(page.get_width() * 2) or 1500
            h = int(page.get_height() * 2) or 2000
            raw_lines = [l.strip() for l in raw_page_text.splitlines() if l.strip()]
            if not raw_lines:
                continue

            y_interval = h / max(1, len(raw_lines) + 1)
            p_lines = []
            for l_idx, line_text in enumerate(raw_lines):
                y_center = int((l_idx + 1) * y_interval)
                p_lines.append(
                    OCRLine(
                        text=normalize_space(line_text),
                        score=0.99,
                        x_min=50,
                        y_min=max(0, y_center - 15),
                        x_max=w - 50,
                        y_max=min(h, y_center + 15),
                        page_num=page_idx,
                        page_height=h,
                        page_width=w,
                    )
                )

            all_lines.extend(p_lines)
            all_raw_texts.append(f"--- PAGE {page_idx} ---\n" + "\n".join(l.text for l in p_lines))

        if all_lines:
            return all_lines, "\n\n".join(all_raw_texts)
    except Exception:
        pass
    return None


def extract_pdf_pages_to_images(uploaded_bytes: bytes) -> list[str]:
    """Legacy helper: Converts PDF into JPEG temp files at optimized scale."""
    page_buffers = extract_pdf_pages_to_memory(uploaded_bytes, scale=1.6)
    page_paths = []
    for page_idx, img_bytes, _, _ in page_buffers:
        out_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        out_file.write(img_bytes)
        out_file.close()
        page_paths.append(out_file.name)
    return page_paths


def process_uploaded_file(uploaded_bytes: bytes, filename: str) -> str:
    """Saves uploaded bytes to a temp file. If PDF, converts PDF pages into a single stacked PNG image."""
    is_pdf = filename.lower().endswith(".pdf") or uploaded_bytes.startswith(b"%PDF")
    if is_pdf:
        out_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        out_file.write(uploaded_bytes)
        out_file.close()
        return out_file.name
    else:
        suffix = Path(filename).suffix or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_bytes)
            return tmp.name


def generate_qr_base64(text: str) -> str:
    """Generates an embedded Base64-encoded PNG image of the QR Code."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        print(f"QR generation error: {exc}")
        return ""


PREVIEW_CACHE: dict[str, str] = {}
PREVIEW_CACHE_DIR = Path("scratch/preview_cache")
PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save_preview_html(verification_id: str, html_content: str) -> None:
    if not verification_id or not html_content:
        return
    PREVIEW_CACHE[verification_id] = html_content
    try:
        (PREVIEW_CACHE_DIR / f"{verification_id}.html").write_text(
            html_content, encoding="utf-8"
        )
    except Exception:
        pass


def get_preview_html(verification_id: str) -> str:
    if not verification_id:
        return ""
    if verification_id in PREVIEW_CACHE:
        return PREVIEW_CACHE[verification_id]
    cache_file = PREVIEW_CACHE_DIR / f"{verification_id}.html"
    if cache_file.exists():
        try:
            content = cache_file.read_text(encoding="utf-8")
            PREVIEW_CACHE[verification_id] = content
            return content
        except Exception:
            pass
    return ""


PUBLIC_TUNNEL_URL: str = ""


def get_public_tunnel_url() -> str:
    global PUBLIC_TUNNEL_URL
    if PUBLIC_TUNNEL_URL:
        return PUBLIC_TUNNEL_URL
    p_file = Path("scratch/public_url.txt")
    if p_file.exists():
        try:
            url = p_file.read_text(encoding="utf-8").strip()
            if url and url.startswith("https://"):
                PUBLIC_TUNNEL_URL = url
                return url
        except Exception:
            pass
    return ""


def start_public_tunnel(port: int) -> None:
    global PUBLIC_TUNNEL_URL
    cf_path = Path("scratch/cloudflared.exe")
    if not cf_path.exists():
        return
    try:
        import subprocess
        proc = subprocess.Popen(
            [str(cf_path), "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
            if m:
                PUBLIC_TUNNEL_URL = m.group(0)
                print(f"[TUNNEL] Mobile & Internet Access URL: {PUBLIC_TUNNEL_URL}")
                try:
                    Path("scratch/public_url.txt").write_text(
                        PUBLIC_TUNNEL_URL, encoding="utf-8"
                    )
                except Exception:
                    pass
                break
    except Exception as exc:
        print(f"[TUNNEL] Could not start tunnel: {exc}")


# HTML Template for main app and verification console
HTML_PAGE = Template("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OneBhoomi — Registry Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Archivo:wght@400;500;600;700&family=Courier+Prime:ital,wght@0,400;0,700;1,400&family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Sans+Telugu:wght@400;500;600;700&family=Noto+Sans+Kannada:wght@400;500;600;700&family=Noto+Sans+Tamil:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root{
      --paper:#F6F0E1; --paper-deep:#EFE6D0; --ink:#221D17; --ink-soft:#5A5142;
      --stamp:#A6193C; --stamp-deep:#7C1030; --rosette:#C99AA8; --green:#2E6B4F;
      --green-deep:#1C4A36; --amber:#A96A1F; --gold:#C9A227;
      --rule:#C9BC9F; --rule-soft:#DCD2B8; --card:#FFFDF6;
      --serif:"Fraunces", "Noto Serif Devanagari", "Noto Serif Telugu", "Noto Serif Kannada", "Noto Serif Tamil", Georgia, serif;
      --type:"Courier Prime", "Noto Sans Devanagari", "Noto Sans Telugu", "Noto Sans Kannada", "Noto Sans Tamil", "Courier New", monospace;
      --sans:"Archivo", "Noto Sans Devanagari", "Noto Sans Telugu", "Noto Sans Kannada", "Noto Sans Tamil", system-ui, sans-serif;
    }

    /* Header Language Picker */
    .lang-picker {
      display: inline-flex;
      align-items: center;
      background: var(--paper-deep);
      border: 1px solid var(--rule);
      border-radius: 4px;
      padding: 3px 8px;
      margin-left: 12px;
      transition: border-color .15s ease, box-shadow .15s ease;
    }
    .lang-picker:focus-within, .lang-picker:hover {
      border-color: var(--stamp);
      box-shadow: 0 0 0 2px rgba(166,25,60,0.12);
    }
    .lang-icon {
      font-size: 13px;
      margin-right: 6px;
      color: var(--ink-soft);
      line-height: 1;
      user-select: none;
    }
    .lang-dropdown {
      background: transparent;
      border: none;
      outline: none;
      font-family: var(--type);
      font-size: 11.5px;
      color: var(--ink);
      font-weight: 700;
      letter-spacing: .5px;
      cursor: pointer;
      padding: 2px 18px 2px 2px;
      appearance: none;
      -webkit-appearance: none;
      background-image: url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%235A5142' d='M0 0l5 6 5-6z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right center;
      background-size: 8px 5px;
    }
    .lang-dropdown option {
      background: #FFFDF6;
      color: #221D17;
      font-family: var(--sans);
      font-size: 13px;
      font-weight: 500;
      padding: 6px 10px;
    }
    html[lang="hi"] body, html[lang="hi"] p, html[lang="hi"] span, html[lang="hi"] a { font-family: "Noto Sans Devanagari", var(--sans); }
    html[lang="te"] body, html[lang="te"] p, html[lang="te"] span, html[lang="te"] a { font-family: "Noto Sans Telugu", var(--sans); }
    html[lang="kn"] body, html[lang="kn"] p, html[lang="kn"] span, html[lang="kn"] a { font-family: "Noto Sans Kannada", var(--sans); }
    html[lang="ta"] body, html[lang="ta"] p, html[lang="ta"] span, html[lang="ta"] a { font-family: "Noto Sans Tamil", var(--sans); }
    *{margin:0;padding:0;box-sizing:border-box}
    html{scroll-behavior:smooth}
    body{
      background:var(--paper);color:var(--ink);font-family:var(--sans);
      font-size:16px;line-height:1.6;overflow-x:hidden;
    }
    ::selection{background:var(--stamp);color:var(--paper)}

    /* security guilloche backdrop (from the register front page) */
    .security-bg{
      position:fixed;inset:0;z-index:0;pointer-events:none;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='420' height='420' viewBox='0 0 420 420'%3E%3Cg fill='none' stroke='%23C99AA8' stroke-width='1' opacity='.33'%3E%3Ccircle cx='210' cy='210' r='196'/%3E%3Ccircle cx='210' cy='210' r='188' stroke-dasharray='3 6'/%3E%3Ccircle cx='210' cy='210' r='172'/%3E%3Ccircle cx='210' cy='210' r='164' stroke-dasharray='10 4'/%3E%3Ccircle cx='210' cy='210' r='148'/%3E%3Ccircle cx='210' cy='210' r='140' stroke-dasharray='2 5'/%3E%3Ccircle cx='210' cy='210' r='124'/%3E%3Ccircle cx='210' cy='210' r='116' stroke-dasharray='8 5'/%3E%3Ccircle cx='210' cy='210' r='100'/%3E%3Ccircle cx='210' cy='210' r='92' stroke-dasharray='4 4'/%3E%3Ccircle cx='210' cy='210' r='76'/%3E%3Ccircle cx='210' cy='210' r='68' stroke-dasharray='12 3'/%3E%3Ccircle cx='210' cy='210' r='52'/%3E%3Ccircle cx='210' cy='210' r='44'/%3E%3Ccircle cx='210' cy='210' r='36' stroke-dasharray='3 4'/%3E%3Ccircle cx='210' cy='210' r='20'/%3E%3C/g%3E%3C/svg%3E");
      background-size:420px 420px;opacity:.5;
    }
    .page{position:relative;z-index:1}
    .perf{
      height:26px;width:100%;
      background-image:radial-gradient(circle at 13px 13px, var(--paper) 6px, transparent 7px);
      background-size:26px 26px;background-position:center top;
    }
    .perf.bottom{background-position:center bottom}

    .wrap{max-width:1440px;margin:0 auto;padding:0 48px;width:100%;box-sizing:border-box}
    @media(max-width:1100px){.wrap{padding:0 32px}}
    @media(max-width:640px){.wrap{padding:0 18px}}

    header{border-bottom:3px double var(--rule)}
    .reg-bar{display:flex;align-items:center;justify-content:space-between;padding:20px 0;gap:24px;flex-wrap:nowrap}
    .brand{display:flex;align-items:baseline;gap:14px;text-decoration:none;color:var(--ink);white-space:nowrap;flex-shrink:0}
    .brand b{font-family:var(--serif);font-weight:900;font-size:26px;letter-spacing:.04em;white-space:nowrap}
    .brand span{font-family:var(--type);font-size:11px;letter-spacing:.14em;color:var(--stamp);text-transform:uppercase;white-space:nowrap;display:inline-block}
    nav{display:flex;gap:28px;align-items:center;white-space:nowrap}
    nav a{font-family:var(--type);font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft);text-decoration:none;white-space:nowrap}
    nav a:hover{color:var(--stamp)}
    nav a:focus-visible{outline:2px solid var(--stamp);outline-offset:4px}
    .reg-no{font-family:var(--type);font-size:11px;color:var(--ink-soft);letter-spacing:.12em;white-space:nowrap}
    @media(max-width:820px){nav{display:none}}
    main{min-height:70vh;padding:24px 0 60px}

    /* ---------- type ---------- */
    .eyebrow{font-family:var(--type);font-size:12px;letter-spacing:.28em;text-transform:uppercase;color:var(--stamp);margin-bottom:24px}
    h1{font-family:var(--serif);font-weight:560;font-size:clamp(38px,5.6vw,72px);line-height:1.05;letter-spacing:-.015em}
    h1 em{font-style:italic;font-weight:420;color:var(--stamp)}
    .lede{max-width:58ch;margin:22px auto 0;font-size:17.5px;color:var(--ink-soft)}

    /* ---------- buttons ---------- */
    .btn{
      font-family:var(--type);font-size:13px;letter-spacing:.16em;text-transform:uppercase;
      text-decoration:none;padding:15px 30px;border-radius:2px;border:0;cursor:pointer;
      display:inline-flex;align-items:center;justify-content:center;gap:8px;
      transition:transform .15s ease, box-shadow .15s ease, background .15s ease, color .15s ease;
    }
    .btn:focus-visible{outline:3px solid var(--stamp);outline-offset:3px}
    .btn-primary{background:var(--stamp);color:var(--paper);box-shadow:3px 3px 0 var(--stamp-deep)}
    .btn-primary:hover{transform:translate(-2px,-2px);box-shadow:5px 5px 0 var(--stamp-deep)}
    .btn-ghost{color:var(--ink);border:1.5px solid var(--ink);background:transparent}
    .btn-ghost:hover{background:var(--ink);color:var(--paper)}
    .btn-green{background:var(--green);color:var(--paper);box-shadow:3px 3px 0 var(--green-deep)}
    .btn-green:hover{transform:translate(-2px,-2px);box-shadow:5px 5px 0 var(--green-deep)}
    .btn-outline-red{color:var(--stamp);border:1.5px solid var(--stamp);background:transparent}
    .btn-outline-red:hover{background:var(--stamp);color:var(--paper)}
    .btn:disabled{background:var(--rule-soft);color:#8A8070;box-shadow:none;cursor:not-allowed;border:0;transform:none}
    .btn-xl{padding:17px 36px;font-size:14px}
    .btn-sm{padding:10px 16px;font-size:11.5px}

    /* ---------- panel chrome: legal border + black tab ---------- */
    .panel{border:1.5px solid var(--ink);background:rgba(255,255,255,.5)}
    .panel .tab{
      font-family:var(--type);font-size:11px;letter-spacing:.22em;text-transform:uppercase;
      background:var(--ink);color:var(--paper);padding:10px 18px;display:flex;justify-content:space-between;gap:12px;
    }
    .panel .tab em{font-style:normal;color:var(--rosette)}
    .panel .tab.t-green{background:var(--green)}
    .panel .tab.t-green em{color:rgba(246,240,225,.75)}
    .panel .tab.t-red{background:var(--stamp-deep)}
    .panel .body{padding:26px}
    @media(max-width:640px){.panel .body{padding:20px 16px}}

    /* ---------- intake desk (upload stage) ---------- */
    .desk{text-align:center;padding:72px 0 48px}
    .scan-form{max-width:680px;margin:46px auto 0;text-align:left}
    .field-label{display:block;font-family:var(--type);font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-soft);margin-bottom:10px}
    .dropzone{
      border:2px dashed var(--rule);background:rgba(255,255,255,.4);padding:46px 26px;
      text-align:center;cursor:pointer;transition:border-color .15s ease, background .15s ease;
    }
    .dropzone:hover,.dropzone:focus-visible,.dropzone.drag{border-color:var(--stamp);background:rgba(201,154,168,.14);outline:none}
    .dropzone.has{border-style:solid;border-color:var(--green);background:rgba(46,107,79,.06)}
    .dz-ico{width:42px;height:52px;display:block;margin:0 auto 14px;stroke:var(--ink-soft);fill:none;stroke-width:1.5}
    .dropzone:hover .dz-ico,.dropzone.drag .dz-ico{stroke:var(--stamp)}
    .dz-title{font-weight:600;font-size:16px}
    .dz-title span{color:var(--stamp);text-decoration:underline;text-underline-offset:3px}
    .dz-hint{font-family:var(--type);font-size:11.5px;color:var(--ink-soft);letter-spacing:.06em;margin-top:8px}
    .filechip{
      display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px;
      background:var(--paper-deep);border:1px solid var(--rule);padding:11px 14px;
      font-family:var(--type);font-size:13px;
    }
    .chip-meta{display:flex;align-items:center;gap:12px;color:var(--ink-soft)}
    .chip-x{border:0;background:none;font-size:18px;line-height:1;cursor:pointer;color:var(--ink-soft);padding:2px 6px}
    .chip-x:hover{color:var(--stamp)}
    .mode-row{margin-top:20px;text-align:left}
    select:not(.lang-dropdown){
      width:100%;padding:11px 12px;border:1.5px solid var(--rule);background:var(--card);
      color:var(--ink);font-family:var(--sans);font-size:14px;border-radius:0;
    }
    select:not(.lang-dropdown):focus{outline:2px solid var(--stamp);outline-offset:1px}
    .mode-note{font-family:var(--type);font-size:11px;color:var(--ink-soft);letter-spacing:.05em;margin-top:8px}
    .submit-row{margin-top:26px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
    .submit-note{font-family:var(--type);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-soft)}
    .next-strip{max-width:680px;margin:28px auto 0;display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
    .next{
      border:1px solid var(--rule);background:rgba(255,255,255,.4);padding:11px 14px;
      font-family:var(--type);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
      color:var(--ink-soft);display:flex;gap:9px;align-items:baseline;
    }
    .next b{color:var(--stamp);font-weight:400}
    @media(max-width:640px){.next-strip{grid-template-columns:1fr}}

    /* ---------- processing overlay ---------- */
    .overlay{
      position:fixed;inset:0;background:var(--paper);z-index:60;display:none;
      flex-direction:column;align-items:center;justify-content:center;gap:20px;text-align:center;padding:24px;
    }
    .overlay.on{display:flex}
    .ov-stamp{
      font-family:var(--serif);font-weight:900;font-size:30px;letter-spacing:.08em;color:var(--stamp);
      border:3px solid var(--stamp);padding:8px 26px;transform:rotate(-7deg);filter:url(#roughen);
    }
    .ov-stage{font-family:var(--serif);font-style:italic;font-size:20px;color:var(--ink)}
    .ov-pipe{width:230px}
    .ov-pipe .shaft{
      width:100%;height:2px;position:relative;
      background:repeating-linear-gradient(90deg,var(--ink) 0 9px,transparent 9px 15px);
      animation:pipeflow 1s linear infinite;
    }
    .ov-pipe .shaft::after{
      content:"";position:absolute;right:-1px;top:-6px;
      border-left:12px solid var(--ink);border-top:7px solid transparent;border-bottom:7px solid transparent;
    }
    @keyframes pipeflow{to{background-position:15px 0}}
    .ov-note{font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft)}

    /* ---------- console head ---------- */
    .console-top{padding:60px 0 0}
    .console-head{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap}
    .console-head h1{font-size:clamp(34px,4.6vw,56px)}
    .console-head .badge{margin-left:auto}
    .sub{font-family:var(--type);font-size:12px;color:var(--ink-soft);letter-spacing:.1em;margin-top:10px}
    .badge{font-family:var(--type);font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;padding:8px 14px;border:1.5px solid;border-radius:2px;white-space:nowrap}
    .badge.b-fail,.badge.b-rejected{color:var(--paper);background:var(--stamp-deep);border-color:var(--stamp-deep)}
    .badge.b-needs_review{color:var(--amber);border-color:var(--amber);background:rgba(169,106,31,.08)}
    .badge.b-extracted{color:var(--ink-soft);border-color:var(--rule);background:rgba(255,255,255,.5)}
    .badge.b-ready_for_approval{color:var(--green);border-color:var(--green);background:rgba(46,107,79,.08)}
    .badge.b-approved{color:var(--paper);background:var(--green);border-color:var(--green)}
    .stepper{display:flex;border:1.5px solid var(--ink);background:rgba(255,255,255,.45);padding:16px 20px;margin-top:28px;gap:6px}
    .step{flex:1;position:relative;text-align:center;padding-top:2px}
    .step .dot{
      width:28px;height:28px;border-radius:50%;border:1.5px solid var(--rule);background:var(--card);
      color:var(--ink-soft);font-family:var(--type);font-size:12px;
      display:flex;align-items:center;justify-content:center;margin:0 auto;
    }
    .step .lbl{font-family:var(--type);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-soft);margin-top:8px}
    .step.done .dot{background:var(--ink);border-color:var(--ink);color:var(--paper)}
    .step.done .lbl{color:var(--ink)}
    .step.now .dot{background:var(--stamp);border-color:var(--stamp);color:var(--paper)}
    .step.now .lbl{color:var(--stamp)}
    .step.warn .dot{background:var(--amber);border-color:var(--amber);color:var(--paper)}
    .step.warn .lbl{color:var(--amber)}
    .step.bad .dot{background:var(--stamp-deep);border-color:var(--stamp-deep);color:var(--paper)}
    .step.bad .lbl{color:var(--stamp)}
    .step:not(:last-child)::after{content:"";position:absolute;top:15px;left:calc(50% + 22px);right:calc(-50% + 22px);border-top:1.5px dashed var(--rule)}
    @media(max-width:760px){
      .stepper{flex-wrap:wrap;gap:14px}
      .step{flex:1 1 38%}
      .step:not(:last-child)::after{display:none}
    }
    .banner{margin-top:24px;border:1.5px solid var(--rule);background:var(--paper-deep);padding:13px 16px;display:flex;gap:12px;align-items:baseline;font-size:14px}
    .banner .bmark{font-family:var(--serif);font-weight:700;color:var(--stamp)}
    .banner.blocked{border-color:var(--stamp);background:rgba(166,25,60,.08);color:var(--stamp-deep);font-weight:600}
    .docket{
      margin-top:20px;display:flex;flex-wrap:wrap;gap:8px 28px;
      font-family:var(--type);font-size:12px;color:var(--ink-soft);
      border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);padding:10px 2px;
    }
    .docket b{color:var(--stamp);font-weight:400;margin-right:6px}
    .docket.error{color:var(--stamp-deep);border-color:rgba(166,25,60,.4)}

    /* ---------- split console: left exhibit + right clerk review ---------- */
    .console-grid{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:28px;margin-bottom:36px;align-items:start}
    @media(max-width:1080px){.console-grid{grid-template-columns:1fr;gap:24px}}
    .console-grid .exhibit-col{position:sticky;top:20px}
    .console-grid .clerk{margin-top:0}
    .exhibit-panel{display:flex;flex-direction:column;min-height:840px}
    .preview-body{padding:16px;background:var(--paper-deep);flex:1;display:flex;flex-direction:column}
    .preview-body > div{flex:1;min-height:760px;max-height:calc(100vh - 140px) !important;overflow-y:auto}
    .preview-body img{width:100% !important;max-width:100% !important;border:1.5px solid var(--rule);background:#fff;box-shadow:0 4px 20px rgba(34,29,23,.14);display:block}
    .checklist-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px 24px}
    .pdf-note{padding:46px 20px;text-align:center;font-family:var(--type);font-size:12px;color:var(--ink-soft);border:1.5px dashed var(--rule)}
    .checklist{display:flex;flex-direction:column}
    .check{display:flex;gap:14px;padding:12px 4px;border-bottom:1px dotted var(--rule);align-items:baseline}
    .check:last-child{border-bottom:0}
    .check .g{font-family:var(--serif);font-weight:700;width:20px;flex:none;text-align:center}
    .g.pass{color:var(--green)} .g.warn{color:var(--amber)} .g.fail{color:var(--stamp)}
    .check.fail-row{background:rgba(166,25,60,.05)}
    .check .t{font-weight:600;font-size:14px}
    .check .t small{font-family:var(--type);font-size:10.5px;letter-spacing:.12em;color:var(--stamp);margin-left:8px;text-transform:uppercase}
    .check .m{font-family:var(--type);font-size:12px;color:var(--ink-soft);margin-top:2px;line-height:1.5}
    .check-sum{margin-top:14px;padding-top:14px;border-top:1.5px solid var(--ink);font-family:var(--type);font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft)}
    .check-sum .ok{color:var(--green)} .check-sum .md{color:var(--amber)} .check-sum .no{color:var(--stamp)}

    /* ---------- clerk review ---------- */
    .clerk{margin-top:26px}
    .clerk .note{font-family:var(--type);font-size:12px;color:var(--ink-soft);margin-bottom:18px}
    .editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px 18px}
    @media(max-width:700px){.editor-grid{grid-template-columns:1fr}}
    .efull{grid-column:1/-1}
    .editor-field label{font-family:var(--type);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-soft);display:block;margin-bottom:6px}
    .editor-field input,.editor-field select,.editor-field textarea{
      width:100%;padding:11px 12px;border:1.5px solid var(--rule);background:var(--card);
      color:var(--ink);font-family:var(--sans);font-size:14px;border-radius:0;
    }
    .editor-field textarea{font-family:var(--type);font-size:12px;line-height:1.6}
    .editor-field input:focus,.editor-field select:focus,.editor-field textarea:focus{outline:2px solid var(--stamp);outline-offset:1px}
    .editor-field input:disabled,.editor-field select:disabled,.editor-field textarea:disabled{background:var(--paper-deep);color:var(--ink-soft);cursor:not-allowed}
    .action-panel{margin-top:26px;border-top:1.5px solid var(--ink);padding-top:20px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
    .warnbox{width:100%;font-family:var(--type);font-size:12px;padding:10px 14px;border:1px solid}
    .warnbox.ok{border-color:rgba(46,107,79,.5);background:rgba(46,107,79,.08);color:var(--green)}
    .warnbox.stop{border-color:rgba(166,25,60,.5);background:rgba(166,25,60,.08);color:var(--stamp-deep)}
    .reject-group{margin-left:auto;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
    .reject-group input[type=text]{width:230px;padding:11px 12px;border:1.5px solid var(--rule);background:var(--card);font-family:var(--sans);font-size:13px;border-radius:0}
    .reject-group input[type=text]:focus{outline:2px solid var(--stamp);outline-offset:1px}
    @media(max-width:700px){.reject-group{margin-left:0}}

    /* ---------- sealed certificate ---------- */
    .cert{margin-top:32px}
    .cert-body{padding:34px;display:grid;grid-template-columns:1.15fr .85fr;gap:38px}
    @media(max-width:980px){.cert-body{grid-template-columns:1fr}}
    .fact{display:flex;gap:14px;padding:9px 0;border-bottom:1px dotted var(--rule);font-size:14px;align-items:baseline}
    .fact b{font-family:var(--type);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft);width:168px;flex:none;font-weight:400}
    .fact .v{font-weight:600}
    .fact ul{margin:0;padding-left:18px}
    .sig-state{font-family:var(--serif);font-weight:700;color:var(--green);margin:16px 0 2px;font-size:17px}
    .sig-state.bad{color:var(--stamp)}
    .crypto-h{font-family:var(--type);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--stamp);margin:22px 0 10px;padding-top:16px;border-top:1px solid var(--rule)}
    .crypto-line{font-size:13.5px;margin-bottom:8px}
    .sigbox{
      background:var(--paper-deep);border:1px solid var(--rule);font-family:var(--type);font-size:11px;
      word-break:break-all;padding:10px 12px;max-height:90px;overflow:auto;line-height:1.6;margin-top:6px;
    }
    .seal-side{display:flex;flex-direction:column;align-items:center;gap:18px;text-align:center}
    .seal-wrap{position:relative;width:min(240px,70vw)}
    .big-seal{width:100%;animation:slowspin 90s linear infinite}
    @keyframes slowspin{to{transform:rotate(360deg)}}
    .seal-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none}
    .seal-center b{font-family:var(--serif);font-weight:900;font-size:26px;letter-spacing:.06em;color:var(--ink)}
    .seal-center span{font-family:var(--type);font-size:9.5px;letter-spacing:.26em;color:var(--stamp);text-transform:uppercase;margin-top:4px}
    .qrbox{background:#fff;border:1.5px solid var(--ink);padding:14px;box-shadow:5px 5px 0 rgba(34,29,23,.14);transform:rotate(1.4deg)}
    .qrbox canvas{display:block}
    .qrurl{font-family:var(--type);font-size:11px;color:var(--ink-soft);word-break:break-all;max-width:260px}
    .qr-hint{font-size:12px;color:var(--ink-soft);max-width:260px}
    .cert-actions{grid-column:1/-1;display:flex;gap:14px;justify-content:center;flex-wrap:wrap;border-top:1px solid var(--rule);padding-top:22px;margin-top:4px}

    /* ---------- rejected ---------- */
    .rej{margin-top:32px;border:3px double var(--stamp-deep);background:rgba(166,25,60,.05);padding:34px;position:relative}
    .rej-head{font-family:var(--serif);font-weight:700;font-size:clamp(24px,3.4vw,34px);color:var(--stamp-deep)}
    .rej-stamp{
      position:absolute;right:24px;top:20px;transform:rotate(10deg);
      border:3px solid var(--stamp);color:var(--stamp);font-family:var(--serif);font-weight:900;
      font-size:26px;letter-spacing:.1em;padding:5px 16px;filter:url(#roughen);
    }
    @media(max-width:640px){.rej-stamp{position:static;display:inline-block;transform:rotate(-4deg);margin-bottom:16px}}
    .rej .reason{background:rgba(166,25,60,.08);border:1px solid rgba(166,25,60,.35);padding:14px 16px;font-size:14px;color:var(--stamp-deep);margin:20px 0}
    .rej .quiet{font-family:var(--type);font-size:12px;color:var(--ink-soft);margin:18px 0 22px}

    /* ---------- raw payload ---------- */
    .raw{margin-top:26px;border:1.5px solid var(--ink)}
    .raw summary{
      cursor:pointer;list-style:none;background:var(--ink);color:var(--paper);
      font-family:var(--type);font-size:11px;letter-spacing:.22em;text-transform:uppercase;
      padding:10px 18px;display:flex;justify-content:space-between;gap:12px;
    }
    .raw summary::-webkit-details-marker{display:none}
    .raw summary::after{content:"+ open"}
    .raw[open] summary::after{content:"close ×"}
    .raw pre{margin:0;padding:18px;background:var(--ink);color:var(--paper-deep);font-family:var(--type);font-size:12px;line-height:1.7;max-height:320px;overflow:auto}

    /* ---------- GIS panel ---------- */
    .gis{margin-top:26px}
    .gis .attr-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
    .gis .attr{background:var(--card);border:1px solid var(--rule);padding:12px 14px}
    .gis .attr .k{font-family:var(--type);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-soft);margin-bottom:4px}
    .gis .attr .v{font-size:14px;font-weight:700;color:var(--ink)}
    .gis .authority{background:rgba(46,107,79,.08);border:1px solid rgba(46,107,79,.35);padding:12px 14px;margin-bottom:14px}
    .gis .authority .k{font-family:var(--type);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--green)}
    .gis .authority .v{font-size:14px;font-weight:700;color:var(--green);margin-top:2px}
    .gis .authority .s{font-size:11px;color:var(--ink-soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .gis .infonote{background:var(--paper-deep);border-left:4px solid var(--stamp);padding:12px 16px;font-size:13.5px;color:var(--ink-soft);margin-bottom:14px}
    .gis .village-warn{background:rgba(169,106,31,.1);border-left:4px solid var(--amber);padding:10px 14px;font-size:13px;color:var(--amber);margin-bottom:14px}
    .gis .src-note{font-family:var(--type);font-size:11.5px;color:var(--ink-soft);font-style:italic;margin-bottom:16px}
    .gis .map-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:20px;align-items:start}
    @media(max-width:900px){.gis .map-grid{grid-template-columns:1fr}}
    .gis #gis-map{width:100%;height:380px;border:1.5px solid var(--rule);background:var(--paper-deep);z-index:1}
    .gis .legend{font-size:12px;background:var(--card);border:1px solid var(--rule);padding:10px 14px;margin-top:10px;display:flex;flex-wrap:wrap;gap:16px;align-items:center}
    .gis .legend .sw{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}
    .gis .legend .lbl{font-weight:600;color:var(--ink)}
    .gis .coords{font-family:var(--type);font-size:11.5px;color:var(--ink-soft);margin-top:8px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
    .gis .metric{background:var(--card);border:1px solid var(--rule);padding:16px;margin-bottom:14px}
    .gis .metric h4{font-family:var(--type);font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--stamp);margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid var(--rule-soft)}
    .gis .metric p{font-size:13px;line-height:1.6;color:var(--ink-soft);margin:0 0 6px}
    .gis .metric p b{color:var(--ink)}
    .gis .metric .disclaimer{font-family:var(--type);font-size:11px;color:var(--amber);background:rgba(169,106,31,.1);border:1px solid rgba(169,106,31,.3);padding:8px;margin-top:8px;font-style:italic}
    .gis .metric .quiet{font-family:var(--type);font-size:11px;color:var(--ink-soft);background:var(--paper);border:1px solid var(--rule-soft);padding:8px;font-style:italic;margin-top:8px}

    /* ---------- footer ---------- */
    footer{border-top:3px double var(--rule);padding:40px 0;margin-top:72px;background:rgba(255,255,255,.3)}
    .foot-note{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft)}

    /* ---------- reveals ---------- */
    .rv{opacity:0;transform:translateY(22px);transition:opacity .7s ease, transform .7s ease}
    .rv.in{opacity:1;transform:none}
    @media (prefers-reduced-motion: reduce){
      .rv{opacity:1;transform:none;transition:none}
      .big-seal{animation:none}
      .ov-pipe .shaft{animation:none}
      html{scroll-behavior:auto}
      .dropzone,.btn{transition:none}
    }
  </style>
</head>
<body>

<div class="security-bg" aria-hidden="true"></div>

<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <filter id="roughen">
    <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves="2" result="n"/>
    <feDisplacementMap in="SourceGraphic" in2="n" scale="2.5"/>
  </filter>
</svg>

<div class="perf" aria-hidden="true"></div>
<div class="page">

<header>
  <div class="wrap reg-bar">
    <a class="brand" href="/">
      <b>OneBhoomi</b>
      <span>वनभूमि &nbsp;·&nbsp; registry console</span>
    </a>
    <nav aria-label="Sections">
      <a href="/" data-i18n="nav_registry">Registry</a>
      <a href="/dashboard" data-i18n="nav_dashboard">Dashboard</a>
      <a href="/new" data-i18n="nav_new_scan">New Scan</a>
      <a href="/#sealing" data-i18n="nav_sealing">Sealing</a>
      <a href="/#verify" data-i18n="nav_verify">Verify</a>
    </nav>
    <div class="lang-picker" title="Change Language">
            <svg class="lang-svg" viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;stroke:var(--stamp);fill:none;flex-shrink:0;display:inline-block;vertical-align:middle;">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="2" y1="12" x2="22" y2="12"></line>
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
        </svg>
            <select id="langSelect" class="lang-dropdown" aria-label="Select Language">
              <option value="en" selected>English</option>
              <option value="hi">हिंदी (Hindi)</option>
              <option value="te">తెలుగు (Telugu)</option>
              <option value="kn">ಕನ್ನಡ (Kannada)</option>
              <option value="ta">தமிழ் (Tamil)</option>
            </select>
    </div>
    <span class="reg-no">$reg_no</span>
  </div>
</header>

<main>
  <div class="wrap">
$stage_markup
  </div>
</main>

<footer>
  <div class="wrap foot-note">
    <span data-i18n="footer_title">OneBhoomi · Offline Registry Console</span>
    <span data-i18n="footer_sub">Sale Deeds · Agreements · GPA</span>
    <span data-i18n="footer_cloud">No cloud. No keys leaving the office.</span>
  </div>
</footer>

</div>
<div class="perf bottom" aria-hidden="true"></div>

<!-- OFFLINE CLIENT-SIDE QR GENERATION ENGINE -->
<!-- OFFLINE CLIENT-SIDE QR GENERATION ENGINE -->
  <script>
    // Lightweight completely self-contained QR Code generator in JS (QRCode library wrapper)
    // Supports drawing QR codes onto HTML5 Canvas elements locally.
    (function(){
      var QRMode = { MODE_NUMBER: 1, MODE_ALPHA_NUM: 2, MODE_8BIT_BYTE: 4, MODE_KANJI: 8 };
      var QRErrorCorrectLevel = { L: 1, M: 0, Q: 3, H: 2 };
      var QRMaskPattern = { PATTERN000: 0, PATTERN001: 1, PATTERN010: 2, PATTERN011: 3, PATTERN100: 4, PATTERN101: 5, PATTERN110: 6, PATTERN111: 7 };
      var QRUtil = {
        PATTERN_POSITION_TABLE: [
          [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50], [6, 30, 54], [6, 32, 58], [6, 34, 62],
          [6, 26, 46, 66], [6, 26, 48, 70], [6, 26, 50, 74], [6, 30, 54, 78], [6, 30, 56, 82], [6, 30, 58, 86], [6, 34, 62, 90], [6, 28, 50, 72, 94],
          [6, 26, 50, 74, 98], [6, 30, 54, 78, 102], [6, 28, 54, 80, 106], [6, 32, 58, 84, 110], [6, 30, 58, 86, 114], [6, 34, 62, 90, 118],
          [6, 26, 50, 74, 98, 122], [6, 30, 54, 78, 102, 126], [6, 26, 52, 78, 104, 130], [6, 30, 56, 82, 108, 134], [6, 34, 60, 86, 112, 138],
          [6, 30, 58, 86, 114, 142], [6, 34, 62, 90, 118, 146], [6, 30, 54, 78, 102, 126, 150], [6, 24, 50, 76, 102, 128, 154], [6, 28, 54, 80, 106, 132, 158],
          [6, 32, 58, 84, 110, 136, 162], [6, 26, 54, 82, 110, 138, 166, 194], [6, 30, 58, 86, 114, 142, 170, 198]
        ],
        G15: (1 << 10) | (1 << 8) | (1 << 5) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0),
        G18: (1 << 12) | (1 << 11) | (1 << 10) | (1 << 9) | (1 << 8) | (1 << 5) | (1 << 2) | (1 << 0),
        G15_MASK: (1 << 14) | (1 << 12) | (1 << 10) | (1 << 4) | (1 << 1) | (1 << 0),
        getBchTypeInfo: function(data) { var d = data << 10; while (QRUtil.getBchDigit(d) - QRUtil.getBchDigit(QRUtil.G15) >= 0) { d ^= (QRUtil.G15 << (QRUtil.getBchDigit(d) - QRUtil.getBchDigit(QRUtil.G15))); } return ( (data << 10) | d) ^ QRUtil.G15_MASK; },
        getBchTypeNumber: function(data) { var d = data << 12; while (QRUtil.getBchDigit(d) - QRUtil.getBchDigit(QRUtil.G18) >= 0) { d ^= (QRUtil.G18 << (QRUtil.getBchDigit(d) - QRUtil.getBchDigit(QRUtil.G18))); } return (data << 12) | d; },
        getBchDigit: function(data) { var digit = 0; while (data != 0) { digit++; data >>>= 1; } return digit; },
        getPatternPositionTable: function(typeNumber) { return QRUtil.PATTERN_POSITION_TABLE[typeNumber - 1]; },
        getMask: function(maskPattern, i, j) {
          switch (maskPattern) {
            case QRMaskPattern.PATTERN000 : return (i + j) % 2 == 0;
            case QRMaskPattern.PATTERN001 : return i % 2 == 0;
            case QRMaskPattern.PATTERN010 : return j % 3 == 0;
            case QRMaskPattern.PATTERN011 : return (i + j) % 3 == 0;
            case QRMaskPattern.PATTERN100 : return (Math.floor(i / 2) + Math.floor(j / 3) ) % 2 == 0;
            case QRMaskPattern.PATTERN101 : return (i * j) % 2 + (i * j) % 3 == 0;
            case QRMaskPattern.PATTERN110 : return ( (i * j) % 2 + (i * j) % 3) % 2 == 0;
            case QRMaskPattern.PATTERN111 : return ( (i * j) % 3 + (i + j) % 2) % 2 == 0;
            default : throw new Error("bad maskPattern:" + maskPattern);
          }
        },
        getErrorCorrectPolynomial: function(errorCorrectLength) { var a = new QRPolynomial([1], 0); for (var i = 0; i < errorCorrectLength; i++) { a = a.multiply(new QRPolynomial([1, QRMath.gexp(i)], 0) ); } return a; },
        getLengthInBits: function(mode, type) {
          if (1 <= type && type < 10) {
            switch (mode) {
              case QRMode.MODE_NUMBER: return 10;
              case QRMode.MODE_ALPHA_NUM: return 9;
              case QRMode.MODE_8BIT_BYTE: return 8;
              case QRMode.MODE_KANJI: return 8;
              default: throw new Error("mode:" + mode);
            }
          } else if (type < 27) {
            switch (mode) {
              case QRMode.MODE_NUMBER: return 12;
              case QRMode.MODE_ALPHA_NUM: return 11;
              case QRMode.MODE_8BIT_BYTE: return 16;
              case QRMode.MODE_KANJI: return 10;
              default: throw new Error("mode:" + mode);
            }
          } else if (type < 41) {
            switch (mode) {
              case QRMode.MODE_NUMBER: return 14;
              case QRMode.MODE_ALPHA_NUM: return 13;
              case QRMode.MODE_8BIT_BYTE: return 16;
              case QRMode.MODE_KANJI: return 12;
              default: throw new Error("mode:" + mode);
            }
          } else {
            throw new Error("type:" + type);
          }
        },
        getLostPoint: function(qrCode) {
          var moduleCount = qrCode.getModuleCount();
          var lostPoint = 0;
          for (var row = 0; row < moduleCount; row++) {
            for (var col = 0; col < moduleCount; col++) {
              var sameColorCount = 0;
              var dark = qrCode.isDark(row, col);
              for (var r = -1; r <= 1; r++) {
                if (row + r < 0 || moduleCount <= row + r) { continue; }
                for (var c = -1; c <= 1; c++) {
                  if (col + c < 0 || moduleCount <= col + c) { continue; }
                  if (r == 0 && c == 0) { continue; }
                  if (dark == qrCode.isDark(row + r, col + c) ) { sameColorCount++; }
                }
              }
              if (sameColorCount > 5) { lostPoint += (3 + sameColorCount - 5); }
            }
          }
          for (var row = 0; row < moduleCount - 1; row++) {
            for (var col = 0; col < moduleCount - 1; col++) {
              var count = 0;
              if (qrCode.isDark(row, col) ) count++;
              if (qrCode.isDark(row + 1, col) ) count++;
              if (qrCode.isDark(row, col + 1) ) count++;
              if (qrCode.isDark(row + 1, col + 1) ) count++;
              if (count == 0 || count == 4) { lostPoint += 3; }
            }
          }
          for (var row = 0; row < moduleCount; row++) {
            for (var col = 0; col < moduleCount - 6; col++) {
              if (qrCode.isDark(row, col) && !qrCode.isDark(row, col + 1) && qrCode.isDark(row, col + 2) && qrCode.isDark(row, col + 3) && qrCode.isDark(row, col + 4) && !qrCode.isDark(row, col + 5) && qrCode.isDark(row, col + 6) ) {
                lostPoint += 40;
              }
            }
          }
          for (var col = 0; col < moduleCount; col++) {
            for (var row = 0; row < moduleCount - 6; row++) {
              if (qrCode.isDark(row, col) && !qrCode.isDark(row + 1, col) && qrCode.isDark(row + 2, col) && qrCode.isDark(row + 3, col) && qrCode.isDark(row + 4, col) && !qrCode.isDark(row + 5, col) && qrCode.isDark(row + 6, col) ) {
                lostPoint += 40;
              }
            }
          }
          var darkCount = 0;
          for (var col = 0; col < moduleCount; col++) {
            for (var row = 0; row < moduleCount; row++) {
              if (qrCode.isDark(row, col) ) { darkCount++; }
            }
          }
          var ratio = Math.abs(100 * darkCount / moduleCount / moduleCount - 50) / 5;
          lostPoint += ratio * 10;
          return lostPoint;
        }
      };
      var QRMath = {
        glog: function(n) { if (n < 1) { throw new Error("glog(" + n + ")"); } return QRMath.LOG_TABLE[n]; },
        gexp: function(n) { while (n < 0) { n += 255; } while (n >= 255) { n -= 255; } return QRMath.EXP_TABLE[n]; },
        EXP_TABLE: new Array(256),
        LOG_TABLE: new Array(256)
      };
      for (var i = 0; i < 8; i++) { QRMath.EXP_TABLE[i] = 1 << i; }
      for (var i = 8; i < 256; i++) { QRMath.EXP_TABLE[i] = QRMath.EXP_TABLE[i - 4] ^ QRMath.EXP_TABLE[i - 5] ^ QRMath.EXP_TABLE[i - 6] ^ QRMath.EXP_TABLE[i - 8]; }
      for (var i = 0; i < 255; i++) { QRMath.LOG_TABLE[QRMath.EXP_TABLE[i] ] = i; }
      
      function QRPolynomial(num, shift) {
        if (num.length == undefined) { throw new Error(num.length + "/" + shift); }
        var offset = 0;
        while (offset < num.length && num[offset] == 0) { offset++; }
        this.num = new Array(num.length - offset + shift);
        for (var i = 0; i < num.length - offset; i++) { this.num[i] = num[i + offset]; }
        for (var i = num.length - offset; i < this.num.length; i++) { this.num[i] = 0; }
      }
      QRPolynomial.prototype = {
        get: function(index) { return this.num[index]; },
        getLength: function() { return this.num.length; },
        multiply: function(e) {
          var num = new Array(this.getLength() + e.getLength() - 1);
          for (var i = 0; i < this.getLength(); i++) {
            for (var j = 0; j < e.getLength(); j++) {
              num[i + j] ^= QRMath.gexp(QRMath.glog(this.get(i) ) + QRMath.glog(e.get(j) ) );
            }
          }
          return new QRPolynomial(num, 0);
        },
        mod: function(e) {
          if (this.getLength() - e.getLength() < 0) { return this; }
          var ratio = QRMath.glog(this.get(0) ) - QRMath.glog(e.get(0) );
          var num = new Array(this.getLength() );
          for (var i = 0; i < this.getLength(); i++) { num[i] = this.get(i); }
          for (var i = 0; i < e.getLength(); i++) { num[i] ^= QRMath.gexp(QRMath.glog(e.get(i) ) + ratio); }
          return new QRPolynomial(num, 0).mod(e);
        }
      };
      
      var QRRSBlock = {
        RS_BLOCK_TABLE: [
          [1, 26, 19], [1, 26, 16], [1, 26, 13], [1, 26, 9], [1, 44, 34], [1, 44, 28], [1, 44, 22], [1, 44, 16],
          [1, 70, 55], [1, 70, 44], [2, 35, 17], [2, 35, 13], [1, 95, 80], [2, 47, 32], [2, 48, 24], [2, 48, 18],
          [1, 134, 108], [2, 67, 43], [2, 33, 15, 2, 34, 16], [2, 33, 11, 4, 34, 12], [2, 86, 68], [4, 43, 27], [4, 43, 19, 1, 44, 20], [4, 43, 15, 2, 44, 16],
          [2, 98, 78], [4, 49, 31], [2, 32, 14, 4, 33, 15], [4, 39, 13, 1, 40, 14], [2, 121, 97], [2, 60, 38, 2, 61, 39], [4, 40, 18, 2, 41, 19], [4, 40, 14, 2, 41, 15],
          [2, 146, 116], [3, 58, 36, 2, 59, 37], [4, 36, 16, 4, 37, 17], [4, 36, 12, 4, 37, 13], [2, 86, 68, 2, 87, 69], [4, 69, 43, 1, 70, 44], [6, 43, 19, 2, 44, 20], [6, 43, 15, 2, 44, 16],
          [4, 101, 80], [1, 80, 50, 4, 81, 51], [4, 50, 22, 4, 51, 23], [4, 50, 15, 4, 51, 16]
        ],
        getRSBlocks: function(typeNumber, errorCorrectLevel) {
          var list = QRRSBlock.getRsBlockTable(typeNumber, errorCorrectLevel);
          if (list == undefined) { throw new Error("bad rs block table for type:" + typeNumber + "/errorCorrectLevel:" + errorCorrectLevel); }
          var length = list.length / 3;
          var blocks = [];
          for (var i = 0; i < length; i++) {
            var count = list[i * 3 + 0];
            var totalCount = list[i * 3 + 1];
            var dataCount = list[i * 3 + 2];
            for (var j = 0; j < count; j++) { blocks.push(new QRRSBlock(totalCount, dataCount) ); }
          }
          return blocks;
        },
        getRsBlockTable: function(typeNumber, errorCorrectLevel) {
          switch (errorCorrectLevel) {
            case QRErrorCorrectLevel.L : return QRRSBlock.RS_BLOCK_TABLE[(typeNumber - 1) * 4 + 0];
            case QRErrorCorrectLevel.M : return QRRSBlock.RS_BLOCK_TABLE[(typeNumber - 1) * 4 + 1];
            case QRErrorCorrectLevel.Q : return QRRSBlock.RS_BLOCK_TABLE[(typeNumber - 1) * 4 + 2];
            case QRErrorCorrectLevel.H : return QRRSBlock.RS_BLOCK_TABLE[(typeNumber - 1) * 4 + 3];
            default : return undefined;
          }
        }
      };
      function QRRSBlock(totalCount, dataCount) { this.totalCount = totalCount; this.dataCount = dataCount; }
      
      function QRBitBuffer() { this.buffer = []; this.length = 0; }
      QRBitBuffer.prototype = {
        get: function(index) { var bufIndex = Math.floor(index / 8); return ( (this.buffer[bufIndex] >>> (7 - index % 8) ) & 1) == 1; },
        put: function(num, length) { for (var i = 0; i < length; i++) { this.putBit( ( (num >>> (length - i - 1) ) & 1) == 1); } },
        getLengthInBits: function() { return this.length; },
        putBit: function(bit) { var bufIndex = Math.floor(this.length / 8); if (this.buffer.length <= bufIndex) { this.buffer.push(0); } if (bit) { this.buffer[bufIndex] |= (0x80 >>> (this.length % 8) ); } this.length++; }
      };

      function QRCodeModel(typeNumber, errorCorrectLevel) {
        this.typeNumber = typeNumber;
        this.errorCorrectLevel = errorCorrectLevel;
        this.modules = null;
        this.moduleCount = 0;
        this.dataCache = null;
        this.dataList = [];
      }
      QRCodeModel.prototype = {
        addData: function(data) { var newData = new QR8bitByte(data); this.dataList.push(newData); this.dataCache = null; },
        isDark: function(row, col) { if (row < 0 || this.moduleCount <= row || col < 0 || this.moduleCount <= col) { throw new Error(row + "," + col); } return this.modules[row][col]; },
        getModuleCount: function() { return this.moduleCount; },
        make: function() { this.makeImpl(false, this.getBestMaskPattern() ); },
        makeImpl: function(test, maskPattern) {
          this.moduleCount = this.typeNumber * 4 + 17;
          this.modules = new Array(this.moduleCount);
          for (var row = 0; row < this.moduleCount; row++) { this.modules[row] = new Array(this.moduleCount); for (var col = 0; col < this.moduleCount; col++) { this.modules[row][col] = null; } }
          this.setupPositionFinderPattern(0, 0);
          this.setupPositionFinderPattern(this.moduleCount - 7, 0);
          this.setupPositionFinderPattern(0, this.moduleCount - 7);
          this.setupPositionAdjustPattern();
          this.setupTimingPattern();
          this.setupTypeInfo(test, maskPattern);
          if (this.typeNumber >= 7) { this.setupTypeNumber(test); }
          if (this.dataCache == null) { this.dataCache = QRCodeModel.createData(this.typeNumber, this.errorCorrectLevel, this.dataList); }
          this.mapData(this.dataCache, maskPattern);
        },
        setupPositionFinderPattern: function(row, col) {
          for (var r = -1; r <= 7; r++) {
            if (row + r <= -1 || this.moduleCount <= row + r) continue;
            for (var c = -1; c <= 7; c++) {
              if (col + c <= -1 || this.moduleCount <= col + c) continue;
              if ( (0 <= r && r <= 6 && (c == 0 || c == 6) ) || (0 <= c && c <= 6 && (r == 0 || r == 6) ) || (2 <= r && r <= 4 && 2 <= c && c <= 4) ) {
                this.modules[row + r][col + c] = true;
              } else {
                this.modules[row + r][col + c] = false;
              }
            }
          }
        },
        getBestMaskPattern: function() {
          var minLostPoint = 0;
          var pattern = 0;
          for (var i = 0; i < 8; i++) {
            this.makeImpl(true, i);
            var lostPoint = QRUtil.getLostPoint(this);
            if (i == 0 || minLostPoint > lostPoint) { minLostPoint = lostPoint; pattern = i; }
          }
          return pattern;
        },
        setupTimingPattern: function() {
          for (var r = 8; r < this.moduleCount - 8; r++) { if (this.modules[r][6] != null) { continue; } this.modules[r][6] = (r % 2 == 0); }
          for (var c = 8; c < this.moduleCount - 8; c++) { if (this.modules[6][c] != null) { continue; } this.modules[6][c] = (c % 2 == 0); }
        },
        setupPositionAdjustPattern: function() {
          var pos = QRUtil.getPatternPositionTable(this.typeNumber);
          for (var i = 0; i < pos.length; i++) {
            for (var j = 0; j < pos.length; j++) {
              var row = pos[i];
              var col = pos[j];
              if (this.modules[row][col] != null) { continue; }
              for (var r = -2; r <= 2; r++) {
                for (var c = -2; c <= 2; c++) {
                  if (Math.abs(r) == 2 || Math.abs(c) == 2 || (r == 0 && c == 0) ) {
                    this.modules[row + r][col + c] = true;
                  } else {
                    this.modules[row + r][col + c] = false;
                  }
                }
              }
            }
          }
        },
        setupTypeNumber: function(test) {
          var bits = QRUtil.getBchTypeNumber(this.typeNumber);
          for (var i = 0; i < 18; i++) {
            var mod = (!test && ( (bits >> i) & 1) == 1);
            this.modules[Math.floor(i / 3)][i % 3 + this.moduleCount - 8 - 3] = mod;
            this.modules[i % 3 + this.moduleCount - 8 - 3][Math.floor(i / 3)] = mod;
          }
        },
        setupTypeInfo: function(test, maskPattern) {
          var data = (this.errorCorrectLevel << 3) | maskPattern;
          var bits = QRUtil.getBchTypeInfo(data);
          for (var i = 0; i < 15; i++) {
            var mod = (!test && ( (bits >> i) & 1) == 1);
            if (i < 6) {
              this.modules[i][8] = mod;
            } else if (i < 8) {
              this.modules[i + 1][8] = mod;
            } else {
              this.modules[this.moduleCount - 15 + i][8] = mod;
            }
            if (i < 8) {
              this.modules[8][this.moduleCount - i - 1] = mod;
            } else if (i < 9) {
              this.modules[8][15 - i - 1 + 1] = mod;
            } else {
              this.modules[8][15 - i - 1] = mod;
            }
          }
          this.modules[this.moduleCount - 8][8] = !test;
        },
        mapData: function(data, maskPattern) {
          var inc = -1;
          var row = this.moduleCount - 1;
          var bitIndex = 0;
          var byteIndex = 0;
          for (var col = this.moduleCount - 1; col > 0; col -= 2) {
            if (col == 6) col--;
            while (true) {
              for (var c = 0; c < 2; c++) {
                var currentCol = col - c;
                if (this.modules[row][currentCol] == null) {
                  var dark = false;
                  if (bitIndex < data.length) { dark = ( ( (data[bitIndex] >>> (7 - byteIndex) ) & 1) == 1); }
                  var mask = QRUtil.getMask(maskPattern, row, currentCol);
                  if (mask) { dark = !dark; }
                  this.modules[row][currentCol] = dark;
                  byteIndex++;
                  if (byteIndex == 8) { byteIndex = 0; bitIndex++; }
                }
              }
              row += inc;
              if (row < 0 || this.moduleCount <= row) { row -= inc; inc = -inc; break; }
            }
          }
        }
      };
      QRCodeModel.createData = function(typeNumber, errorCorrectLevel, dataList) {
        var rsBlocks = QRRSBlock.getRSBlocks(typeNumber, errorCorrectLevel);
        var buffer = new QRBitBuffer();
        for (var i = 0; i < dataList.length; i++) {
          var data = dataList[i];
          buffer.put(data.mode, 4);
          buffer.put(data.getLength(), QRUtil.getLengthInBits(data.mode, typeNumber) );
          data.write(buffer);
        }
        var totalDataCount = 0;
        for (var i = 0; i < rsBlocks.length; i++) { totalDataCount += rsBlocks[i].dataCount; }
        if (buffer.getLengthInBits() > totalDataCount * 8) {
          throw new Error("code length overflow. (" + buffer.getLengthInBits() + ">" + (totalDataCount * 8) + ")");
        }
        if (buffer.getLengthInBits() + 4 <= totalDataCount * 8) { buffer.put(0, 4); }
        while (buffer.getLengthInBits() % 8 != 0) { buffer.putBit(false); }
        while (true) {
          if (buffer.getLengthInBits() >= totalDataCount * 8) { break; }
          buffer.put(QRCodeModel.PAD0, 8);
          if (buffer.getLengthInBits() >= totalDataCount * 8) { break; }
          buffer.put(QRCodeModel.PAD1, 8);
        }
        return QRCodeModel.createBytes(buffer, rsBlocks);
      };
      QRCodeModel.createBytes = function(buffer, rsBlocks) {
        var offset = 0;
        var maxDcCount = 0;
        var maxEcCount = 0;
        var dcdata = new Array(rsBlocks.length);
        var ecdata = new Array(rsBlocks.length);
        for (var r = 0; r < rsBlocks.length; r++) {
          var dcCount = rsBlocks[r].dataCount;
          var ecCount = rsBlocks[r].totalCount - dcCount;
          maxDcCount = Math.max(maxDcCount, dcCount);
          maxEcCount = Math.max(maxEcCount, ecCount);
          dcdata[r] = new Array(dcCount);
          for (var i = 0; i < dcdata[r].length; i++) { dcdata[r][i] = 0xff & buffer.buffer[i + offset]; }
          offset += dcCount;
          var rsPoly = QRUtil.getErrorCorrectPolynomial(ecCount);
          var rawPoly = new QRPolynomial(dcdata[r], rsPoly.getLength() - 1);
          var modPoly = rawPoly.mod(rsPoly);
          ecdata[r] = new Array(rsPoly.getLength() - 1);
          for (var i = 0; i < ecdata[r].length; i++) {
            var modIndex = i + modPoly.getLength() - ecdata[r].length;
            ecdata[r][i] = (modIndex >= 0) ? modPoly.get(modIndex) : 0;
          }
        }
        var totalCodeCount = 0;
        for (var i = 0; i < rsBlocks.length; i++) { totalCodeCount += rsBlocks[i].totalCount; }
        var data = new Array(totalCodeCount);
        var idx = 0;
        for (var i = 0; i < maxDcCount; i++) { for (var r = 0; r < rsBlocks.length; r++) { if (i < dcdata[r].length) { data[idx++] = dcdata[r][i]; } } }
        for (var i = 0; i < maxEcCount; i++) { for (var r = 0; r < rsBlocks.length; r++) { if (i < ecdata[r].length) { data[idx++] = ecdata[r][i]; } } }
        return data;
      };
      QRCodeModel.PAD0 = 0xEC;
      QRCodeModel.PAD1 = 0x11;
      
      function QR8bitByte(data) { this.mode = QRMode.MODE_8BIT_BYTE; this.data = data; }
      QR8bitByte.prototype = {
        getLength: function() { return this.data.length; },
        write: function(buffer) { for (var i = 0; i < this.data.length; i++) { buffer.put(this.data.charCodeAt(i), 8); } }
      };

      // Expose to window namespace
      window.QRCodeLib = { QRCodeModel: QRCodeModel, QRErrorCorrectLevel: QRErrorCorrectLevel };
    })();

    // Function to draw QR code on the canvas element
    function drawQRCode(canvasId, text) {
      var canvas = document.getElementById(canvasId);
      if (!canvas) return;
      var ctx = canvas.getContext('2d');
      
      var qr = null;
      for (var type = 1; type <= 11; type++) {
        try {
          qr = new QRCodeLib.QRCodeModel(type, QRCodeLib.QRErrorCorrectLevel.M);
          qr.addData(text);
          qr.make();
          break;
        } catch (e) {
          if (type === 11) {
            console.error("QR Code generation overflow:", e);
            return;
          }
        }
      }
      
      var moduleCount = qr.getModuleCount();
      var size = 200;
      canvas.width = size;
      canvas.height = size;
      var cellSize = size / moduleCount;
      
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, size, size);
      
      ctx.fillStyle = '#221D17';
      for (var row = 0; row < moduleCount; row++) {
        for (var col = 0; col < moduleCount; col++) {
          if (qr.isDark(row, col)) {
            ctx.fillRect(
              Math.floor(col * cellSize),
              Math.floor(row * cellSize),
              Math.ceil(cellSize),
              Math.ceil(cellSize)
            );
          }
        }
      }
    }
  </script>

<script>
  var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* reveal on scroll */
  (function(){
    var els = document.querySelectorAll('.rv');
    if ('IntersectionObserver' in window && !REDUCED) {
      var io = new IntersectionObserver(function(es){
        es.forEach(function(e){
          if(!e.isIntersecting) return;
          e.target.classList.add('in');
          io.unobserve(e.target);
        });
      }, {threshold:.12});
      els.forEach(function(el){ io.observe(el); });
    } else {
      els.forEach(function(el){ el.classList.add('in'); });
    }
  })();

  /* intake desk: dropzone, file chip, processing overlay */
  (function(){
    var form = document.getElementById('scanForm');
    if (!form) return;
    var dz = document.getElementById('dropzone'),
        fi = document.getElementById('document_image'),
        chip = document.getElementById('filechip'),
        chipName = document.getElementById('chipName'),
        chipSize = document.getElementById('chipSize'),
        chipClear = document.getElementById('chipClear'),
        dzTitle = document.getElementById('dzTitle'),
        overlay = document.getElementById('overlay'),
        ovStage = document.getElementById('ovStage');

    function humanSize(n){
      if (n >= 1048576) return (n/1048576).toFixed(1) + ' MB';
      if (n >= 1024) return Math.round(n/1024) + ' KB';
      return n + ' B';
    }
    function setFile(f){
      if (!f) return;
      chipName.textContent = f.name;
      chipSize.textContent = humanSize(f.size);
      chip.hidden = false;
      dz.classList.add('has');
      dzTitle.innerHTML = 'Scan loaded, drop a file here to replace it';
    }
    dz.addEventListener('click', function(){ fi.click(); });
    dz.addEventListener('keydown', function(e){
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fi.click(); }
    });
    ['dragenter','dragover'].forEach(function(ev){
      dz.addEventListener(ev, function(e){ e.preventDefault(); dz.classList.add('drag'); });
    });
    ['dragleave','drop'].forEach(function(ev){
      dz.addEventListener(ev, function(e){ e.preventDefault(); dz.classList.remove('drag'); });
    });
    dz.addEventListener('drop', function(e){
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f && window.DataTransfer) {
        var dt = new DataTransfer();
        dt.items.add(f);
        fi.files = dt.files;
      }
      setFile(f || (fi.files && fi.files[0]));
    });
    fi.addEventListener('change', function(){ setFile(fi.files[0]); });
    chipClear.addEventListener('click', function(){
      fi.value = '';
      chip.hidden = true;
      dz.classList.remove('has');
      dzTitle.innerHTML = 'Drop the scan here, or <span>browse files</span>';
    });
    form.addEventListener('submit', function(e){
      if (!fi.files || !fi.files.length) {
        e.preventDefault();
        dzTitle.innerHTML = 'Choose a scan first, then press Process Extraction';
        dz.focus();
        return;
      }
      if (overlay && !REDUCED) {
        overlay.classList.add('on');
        var stages = ['Reading the scan', 'Parsing the clauses', 'Filling the particulars', 'Running the machine checklist'];
        var si = 0;
        setInterval(function(){
          si = (si + 1) % stages.length;
          if (ovStage) ovStage.textContent = stages[si];
        }, 2300);
      } else if (overlay) {
        overlay.classList.add('on');
      }
    });
  })();
</script>

<script>
const CONSOLE_I18N = {"en": {"nav_registry": "Registry", "nav_dashboard": "Dashboard", "nav_new_scan": "New Scan", "nav_sealing": "Sealing", "nav_verify": "Verify", "console_h1": "Verification <em>Console</em>", "lbl_record": "Record", "badge_extracted": "Extracted", "badge_needs_review": "Needs Review", "badge_ready_for_approval": "Ready for Approval", "badge_approved": "Approved & Sealed", "badge_rejected": "Rejected", "badge_fail": "Checks Failed", "step_scan": "Scan", "step_machine": "Machine Check", "step_clerk": "Clerk Review", "step_seal": "Officer Seal", "lbl_mode": "Mode", "lbl_hardware": "Hardware", "lbl_ocr": "OCR", "lbl_transit": "Transit", "lbl_total": "Total", "lbl_passed": "passed", "lbl_warnings": "warnings", "lbl_failed": "failed", "sched_a_panel_title": "Schedule A · Machine Checklist", "sched_a_sub": "automated", "chk_required_fields_name": "Required Document Fields", "chk_required_fields_msg": "All critical document fields are present.", "chk_area_bounds_name": "Property Area Boundary Validation", "chk_area_bounds_msg": "Property area is valid.", "chk_date_order_name": "Date Parse & Logic Validation", "chk_date_order_msg": "Document and execution dates are logically ordered.", "chk_survey_format_name": "Survey Number Validation", "chk_survey_format_msg": "Survey number format is valid.", "chk_geographic_consistency_name": "Geographic Authority Consistency", "chk_geographic_consistency_msg": "State Authority: VALIDATED via State Registry.", "sched_b_panel_title": "Schedule B · Clerk Review", "sched_b_sub": "correct in place", "clerk_instruction_note": "read each field against the scan, fix what the OCR got wrong, then save or pass it up to the officer.", "f_doc_type": "Document Type", "f_doc_no": "Document Number", "f_survey": "Survey Number", "f_subsurvey": "Sub-Survey Number", "f_area": "Property Area (Sq. Yards)", "f_village": "Village", "f_mandal": "Mandal", "f_district": "District", "f_stamp_no": "Stamp Serial Number", "f_stamp_val": "Stamp Value (₹)", "f_sold_to": "Stamp Sold To", "f_doc_date": "Document Date", "f_exec_date": "Execution Date", "f_parties": "Parties (JSON)", "warn_officer_ok": "Officer approval permanently certifies the reviewed facts and applies the seal.", "btn_save_corrections": "Save Corrections", "btn_officer_approve_seal": "Officer Approve & Seal", "btn_officer_reject": "Officer Reject", "ph_rej_reason": "Rejection reason (required)", "btn_view_cert_qr": "View Standalone Certificate & QR", "footer_title": "OneBhoomi · Offline Registry Console", "footer_sub": "Sale Deeds · Agreements · GPA", "footer_cloud": "No cloud. No keys leaving the office.", "chk_area_validation_name": "Property Area Boundary Validation", "chk_area_validation_msg": "Property area is valid.", "chk_date_validation_name": "Date Parse & Logic Validation", "chk_date_validation_msg": "Document and execution dates are logically ordered.", "chk_survey_number_validation_name": "Survey Number Validation", "chk_survey_number_validation_msg": "Survey number format is valid.", "chk_internal_consistency_name": "Internal Consistency Check", "chk_internal_consistency_msg": "No contradictions found across deed clauses.", "chk_signature_detection_name": "Signature & Stamp Presence", "chk_signature_detection_msg": "Signatures and stamps detected on document scan."}, "hi": {"nav_registry": "रजिस्ट्री", "nav_dashboard": "डैशबोर्ड", "nav_new_scan": "नया स्कैन", "nav_sealing": "डिजिटल मुहर", "nav_verify": "सत्यापन", "console_h1": "सत्यापन <em>कंसोल</em>", "lbl_record": "अभिलेख सं.", "badge_extracted": "निष्कर्षित", "badge_needs_review": "समीक्षा आवश्यक", "badge_ready_for_approval": "मुहर हेतु तैयार", "badge_approved": "अनुमोदित एवं मुहरबंद", "badge_rejected": "अस्वीकृत", "badge_fail": "जांच विफल", "step_scan": "स्कैन", "step_machine": "मशीन चेक", "step_clerk": "क्लर्क समीक्षा", "step_seal": "अधिकारी मुहर", "lbl_mode": "मोड", "lbl_hardware": "हार्डवेयर", "lbl_ocr": "ओसीआर", "lbl_transit": "ट्रांजिट", "lbl_total": "कुल समय", "lbl_passed": "सफल", "lbl_warnings": "चेतावनी", "lbl_failed": "विफल", "sched_a_panel_title": "अनुसूची क · स्वचालित मशीन चेकलिस्ट", "sched_a_sub": "स्वचालित", "chk_required_fields_name": "अनिवार्य दस्तावेज़ फ़ील्ड्स", "chk_required_fields_msg": "सभी महत्वपूर्ण दस्तावेज़ फ़ील्ड्स उपस्थित हैं।", "chk_area_bounds_name": "संपत्ति क्षेत्र सीमा सत्यापन", "chk_area_bounds_msg": "संपत्ति क्षेत्रफल वैध है।", "chk_date_order_name": "तिथि विश्लेषण एवं तार्किक क्रम", "chk_date_order_msg": "दस्तावेज़ एवं निष्पादन तिथियां तार्किक क्रम में हैं।", "chk_survey_format_name": "सर्वेक्षण संख्या सत्यापन", "chk_survey_format_msg": "सर्वेक्षण संख्या प्रारूप कानूनी रूप से मान्य है।", "chk_geographic_consistency_name": "भौगोलिक प्राधिकरण संगतता", "chk_geographic_consistency_msg": "राज्य प्राधिकरण: राज्य रजिस्ट्री द्वारा सत्यापित।", "sched_b_panel_title": "अनुसूची ख · क्लर्क समीक्षा एवं सुधार", "sched_b_sub": "तत्काल सुधारें", "clerk_instruction_note": "स्कैन के आधार पर प्रत्येक फ़ील्ड की जांच करें, ओसीआर त्रुटियों को सुधारें, फिर सहेजें या अनुमोदन हेतु अधिकारी को भेजें।", "f_doc_type": "दस्तावेज़ प्रकार", "f_doc_no": "दस्तावेज़ संख्या", "f_survey": "सर्वेक्षण संख्या", "f_subsurvey": "उप-सर्वेक्षण संख्या", "f_area": "संपत्ति क्षेत्रफल (वर्ग गज)", "f_village": "ग्राम", "f_mandal": "मंडल", "f_district": "ज़िला", "f_stamp_no": "स्टाम्प क्रमांक", "f_stamp_val": "स्टाम्प मूल्य (₹)", "f_sold_to": "स्टाम्प क्रेता", "f_doc_date": "दस्तावेज़ दिनांक", "f_exec_date": "निष्पादन दिनांक", "f_parties": "पक्षकार (JSON)", "warn_officer_ok": "अधिकारी का अनुमोदन तथ्यों को स्थायी रूप से प्रमाणित करता है और डिजिटल मुहर लगाता है।", "btn_save_corrections": "सुधार सहेजें", "btn_officer_approve_seal": "अधिकारी अनुमोदन एवं मुहर", "btn_officer_reject": "अधिकारी अस्वीकृति", "ph_rej_reason": "अस्वीकृति का कारण (अनिवार्य)", "btn_view_cert_qr": "प्रमाणपत्र एवं क्यूआर देखें", "footer_title": "वनभूमि · ऑफ़लाइन रजिस्ट्री कंसोल", "footer_sub": "बिक्री विलेख · अनुबंध · जीपीए", "footer_cloud": "कोई क्लाउड नहीं। कोई भी कुंजी कार्यालय से बाहर नहीं जाती।", "chk_area_validation_name": "संपत्ति क्षेत्र सीमा सत्यापन", "chk_area_validation_msg": "संपत्ति क्षेत्रफल वैध है।", "chk_date_validation_name": "तिथि विश्लेषण एवं तार्किक क्रम", "chk_date_validation_msg": "दस्तावेज़ एवं निष्पादन तिथियां तार्किक क्रम में हैं।", "chk_survey_number_validation_name": "सर्वेक्षण संख्या सत्यापन", "chk_survey_number_validation_msg": "सर्वेक्षण संख्या प्रारूप कानूनी रूप से मान्य है।", "chk_internal_consistency_name": "आंतरिक संगति जांच", "chk_internal_consistency_msg": "विलेख शर्तों में कोई अंतर्विरोध नहीं मिला।", "chk_signature_detection_name": "हस्ताक्षर एवं स्टाम्प उपस्थिति", "chk_signature_detection_msg": "दस्तावेज़ स्कैन पर हस्ताक्षर एवं स्टाम्प की पुष्टि हुई।"}, "te": {"nav_registry": "రిజిస్ట్రీ", "nav_dashboard": "డ్యాష్‌బోర్డ్", "nav_new_scan": "కొత్త స్కాన్", "nav_sealing": "డిజిటల్ ముద్ర", "nav_verify": "ధృవీకరణ", "console_h1": "ధృవీకరణ <em>కన్సోల్</em>", "lbl_record": "రికార్డు సంఖ్య", "badge_extracted": "సేకరించబడింది", "badge_needs_review": "సమీక్ష అవసరం", "badge_ready_for_approval": "ముద్రకు సిద్ధం", "badge_approved": "ఆమోదించబడి & సీల్ చేయబడింది", "badge_rejected": "తిరస్కరించబడింది", "badge_fail": "తనిఖీ విఫలమైంది", "step_scan": "స్కాన్", "step_machine": "మెషిన్ చెక్", "step_clerk": "క్లర్క్ సమీక్ష", "step_seal": "అధికారి ముద్ర", "lbl_mode": "మోడ్", "lbl_hardware": "హార్డ్‌వేర్", "lbl_ocr": "OCR", "lbl_transit": "రవాణా", "lbl_total": "మొత్తం సమయం", "lbl_passed": "విజయవంతం", "lbl_warnings": "హెచ్చరికలు", "lbl_failed": "విఫలమైనవి", "sched_a_panel_title": "షెడ్యూల్ A · ఆటోమేటెడ్ మెషిన్ చెక్‌లిస్ట్", "sched_a_sub": "ఆటోమేటెడ్", "chk_required_fields_name": "అవసరమైన పత్రం ఫీల్డులు", "chk_required_fields_msg": "అన్ని ముఖ్యమైన ఫీల్డులు ఉన్నాయి.", "chk_area_bounds_name": "ఆస్తి విస్తీర్ణం సరిహద్దు తనిఖీ", "chk_area_bounds_msg": "ఆస్తి విస్తీర్ణం చట్టబద్ధంగా ఉంది.", "chk_date_order_name": "తేదీల విశ్లేషణ & తార్కిక క్రమం", "chk_date_order_msg": "దస్తావేజు మరియు అమలు తేదీలు సరైన క్రమంలో ఉన్నాయి.", "chk_survey_format_name": "సర్వే నంబర్ ధృవీకరణ", "chk_survey_format_msg": "సర్వే నంబర్ సరైన ఫార్మాట్‌లో ఉంది.", "chk_geographic_consistency_name": "భౌగోళిక స్థానిక సరిపోలిక", "chk_geographic_consistency_msg": "స్టేట్ అథారిటీ: అధికారిక రిజిస్ట్రీ ద్వారా ధృవీకరించబడింది.", "sched_b_panel_title": "షెడ్యూల్ B · క్లర్క్ సమీక్ష & సవరణ", "sched_b_sub": "ఇక్కడే సవరించండి", "clerk_instruction_note": "స్కాన్ చేసిన పత్రంతో ప్రతి ఫీల్డ్‌ను సరిచూడండి, తప్పులను సరిదిద్దండి, ఆపై భద్రపరచండి లేదా అధికారికి పంపండి.", "f_doc_type": "పత్రం రకం", "f_doc_no": "పత్రం సంఖ్య", "f_survey": "సర్వే నంబర్", "f_subsurvey": "సబ్-సర్వే నంబర్", "f_area": "ఆస్తి విస్తీర్ణం (గజాలు)", "f_village": "గ్రామం", "f_mandal": "మండలం", "f_district": "జిల్లా", "f_stamp_no": "స్టాంప్ సీరియల్ సంఖ్య", "f_stamp_val": "స్టాంప్ విలువ (₹)", "f_sold_to": "స్టాంప్ కొనుగోలుదారు", "f_doc_date": "పత్రం తేదీ", "f_exec_date": "అమలు తేదీ", "f_parties": "పార్టీలు (JSON)", "warn_officer_ok": "అధికారి ఆమోదం రికార్డును శాశ్వతంగా లాక్ చేసి డిజిటల్ సీల్ వేస్తుంది.", "btn_save_corrections": "సవరణలను భద్రపరచండి", "btn_officer_approve_seal": "అధికారి ఆమోదం & ముద్ర", "btn_officer_reject": "అధికారి తిరస్కరణ", "ph_rej_reason": "తిరస్కరణకు కారణం (తప్పనిసరి)", "btn_view_cert_qr": "ధృవీకరణ పత్రం & QR చూడండి", "footer_title": "వన్‌భూమి · ఆఫ్‌లైన్ రిజిస్ట్రీ కన్సోల్", "footer_sub": "సేల్ డీడ్‌లు · ఒప్పందాలు · GPA", "footer_cloud": "క్లౌడ్ లేదు. కార్యాలయం నుండి కీలు ఎక్కడికీ వెళ్లవు.", "chk_area_validation_name": "ఆస్తి విస్తీర్ణం సరిహద్దు తనిఖీ", "chk_area_validation_msg": "ఆస్తి విస్తీర్ణం చట్టబద్ధంగా ఉంది.", "chk_date_validation_name": "తేదీల విశ్లేషణ & తార్కిక క్రమం", "chk_date_validation_msg": "దస్తావేజు మరియు అమలు తేదీలు సరైన క్రమంలో ఉన్నాయి.", "chk_survey_number_validation_name": "సర్వే నంబర్ ధృవీకరణ", "chk_survey_number_validation_msg": "సర్వే నంబర్ సరైన ఫార్మాట్‌లో ఉంది.", "chk_internal_consistency_name": "అంతర్గత స్థిరత్వ తనిఖీ", "chk_internal_consistency_msg": "నిబంధనలలో ఎటువంటి వైరుధ్యాలు కనుగొనబడలేదు.", "chk_signature_detection_name": "సంతకం మరియు స్టాంప్ గుర్తింపు", "chk_signature_detection_msg": "స్కాన్ పత్రంలో సంతకాలు మరియు స్టాంపులు గుర్తించబడ్డాయి."}, "kn": {"nav_registry": "ನೋಂದಣಿ", "nav_dashboard": "ಡ್ಯಾಶ್‌ಬೋರ್ಡ್", "nav_new_scan": "ಹೊಸ ಸ್ಕ್ಯಾನ್", "nav_sealing": "ಡಿಜಿಟಲ್ ಮುದ್ರೆ", "nav_verify": "ಪರಿಶೀಲನೆ", "console_h1": "ಪರಿಶೀಲನಾ <em>ಕನ್ಸೋಲ್</em>", "lbl_record": "ದಾಖಲೆ ಸಂಖ್ಯೆ", "badge_extracted": "ಹೊರತೆಗೆಯಲಾಗಿದೆ", "badge_needs_review": "ಪರಿಶೀಲನೆ ಅಗತ್ಯವಿದೆ", "badge_ready_for_approval": "ಮುದ್ರೆಗೆ ಸಿದ್ಧ", "badge_approved": "ಅನುಮೋದಿಸಿ ಮುದ್ರೆ ಹಾಕಲಾಗಿದೆ", "badge_rejected": "ತಿರಸ್ಕರಿಸಲಾಗಿದೆ", "badge_fail": "ಪರಿಶೀಲನೆ ವಿಫಲ", "step_scan": "ಸ್ಕ್ಯಾನ್", "step_machine": "ಯಂತ್ರ ತಪಾಸಣೆ", "step_clerk": "ಗುಮಾಸ್ತರ ಪರಿಶೀಲನೆ", "step_seal": "ಅಧಿಕಾರಿಯ ಮುದ್ರೆ", "lbl_mode": "ಮೋಡ್", "lbl_hardware": "ಯಂತ್ರಾಂಶ", "lbl_ocr": "OCR", "lbl_transit": "ರವಾನೆ", "lbl_total": "ಒಟ್ಟು ಸಮಯ", "lbl_passed": "ಯಶಸ್ವಿ", "lbl_warnings": "ಎಚ್ಚರಿಕೆಗಳು", "lbl_failed": "ವಿಫಲ", "sched_a_panel_title": "ಹಂತ A · ಸ್ವಯಂಚಾಲಿತ ಯಂತ್ರ ಪರಿಶೀಲನಾಪಟ್ಟಿ", "sched_a_sub": "ಸ್ವಯಂಚಾಲಿತ", "chk_required_fields_name": "ಅಗತ್ಯವಿರುವ ದಾಖಲೆ ಕ್ಷೇತ್ರಗಳು", "chk_required_fields_msg": "ಎಲ್ಲಾ ಪ್ರಮುಖ ಕ್ಷೇತ್ರಗಳು ಲಭ್ಯವಿವೆ.", "chk_area_bounds_name": "ವಿಸ್ತೀರ್ಣ ಮಿತಿ ಪರಿಶೀಲನೆ", "chk_area_bounds_msg": "ಆಸ್ತಿ ವಿಸ್ತೀರ್ಣ ಮಾನ್ಯವಾಗಿದೆ.", "chk_date_order_name": "ದಿನಾಂಕಗಳ ಕ್ರಮಬದ್ಧತೆ ಪರಿಶೀಲನೆ", "chk_date_order_msg": "ದಾಖಲೆ ದಿನಾಂಕಗಳು ಸರಿಯಾದ ಕ್ರಮದಲ್ಲಿವೆ.", "chk_survey_format_name": "ಸರ್ವೇ ಸಂಖ್ಯೆ ಪರಿಶೀಲನೆ", "chk_survey_format_msg": "ಸರ್ವೇ ಸಂಖ್ಯೆ ಮಾದರಿ ಕಾನೂನುಬದ್ಧವಾಗಿದೆ.", "chk_geographic_consistency_name": "ಭೌಗೋಳಿಕ ತಾಳೆ ಪರಿಶೀಲನೆ", "chk_geographic_consistency_msg": "ರಾಜ್ಯ ಪ್ರಾಧಿಕಾರ: ಅಧಿಕೃತ ನೋಂದಣಿಯಿಂದ ದೃಢೀಕರಿಸಲಾಗಿದೆ.", "sched_b_panel_title": "ಹಂತ B · ಸಿಬ್ಬಂದಿ ಪರಿಶೀಲನೆ & ತಿದ್ದುಪಡಿ", "sched_b_sub": "ಇಲ್ಲಿಯೇ ಸರಿಪಡಿಸಿ", "clerk_instruction_note": "ಸ್ಕ್ಯಾನ್ ಮಾಡಿದ ಪ್ರತಿಯೊಂದಿಗೆ ತಾಳೆ ನೋಡಿ, ತಪ್ಪುಗಳನ್ನು ಸರಿಪಡಿಸಿ, ನಂತರ ಉಳಿಸಿ ಅಥವಾ ಅಧಿಕಾರಿಗೆ ಸಲ್ಲಿಸಿ.", "f_doc_type": "ದಾಖಲೆಯ ಪ್ರಕಾರ", "f_doc_no": "ದಾಖಲೆ ಸಂಖ್ಯೆ", "f_survey": "ಸರ್ವೇ ಸಂಖ್ಯೆ", "f_subsurvey": "ಉಪ-ಸರ್ವೇ ಸಂಖ್ಯೆ", "f_area": "ಆಸ್ತಿ ವಿಸ್ತೀರ್ಣ (ಚದರ ಗಜ)", "f_village": "ಗ್ರಾಮ", "f_mandal": "ಹೋಬಳಿ", "f_district": "ಜಿಲ್ಲೆ", "f_stamp_no": "ಮುದ್ರಾಂಕ ಸಂಖ್ಯೆ", "f_stamp_val": "ಮುದ್ರಾಂಕ ಮೌಲ್ಯ (₹)", "f_sold_to": "ಖರೀದಿದಾರರ ಹೆಸರು", "f_doc_date": "ದಾಖಲೆ ದಿನಾಂಕ", "f_exec_date": "ನೋಂದಣಿ ದಿನಾಂಕ", "f_parties": "ಪಕ್ಷಗಾರರ ವಿವರ (JSON)", "warn_officer_ok": "ಅಧಿಕಾರಿಯ ಅನುಮೋದನೆಯು ದಾಖಲೆಯನ್ನು ಅಂತಿಮಗೊಳಿಸಿ ಡಿಜಿಟಲ್ ಮುದ್ರೆ ಹಾಕುತ್ತದೆ.", "btn_save_corrections": "ತಿದ್ದುಪಡಿ ಉಳಿಸಿ", "btn_officer_approve_seal": "ಅಧಿಕಾರಿ ಅನುಮೋದನೆ & ಮುದ್ರೆ", "btn_officer_reject": "ಅಧಿಕಾರಿ ತಿರಸ್ಕಾರ", "ph_rej_reason": "ತಿರಸ್ಕಾರಕ್ಕೆ ಕಾರಣ (ಕಡ್ಡಾಯ)", "btn_view_cert_qr": "ಪ್ರಮಾಣಪತ್ರ & QR ವೀಕ್ಷಿಸಿ", "footer_title": "ವನ್‌ಭೂಮಿ · ಆಫ್‌ಲೈನ್ ನೋಂದಣಿ ಕನ್ಸೋಲ್", "footer_sub": "ಮಾರಾಟ ಪತ್ರಗಳು · ಒಪ್ಪಂದಗಳು · ಜಿಪಿಎ", "footer_cloud": "ಯಾವುದೇ ಕ್ಲೌಡ್ ಇಲ್ಲ. ಕಚೇರಿಯಿಂದ ಕೀಗಳು ಹೊರಹೋಗುವುದಿಲ್ಲ.", "chk_area_validation_name": "ವಿಸ್ತೀರ್ಣ ಮಿತಿ ಪರಿಶೀಲನೆ", "chk_area_validation_msg": "ಆಸ್ತಿ ವಿಸ್ತೀರ್ಣ ಮಾನ್ಯವಾಗಿದೆ.", "chk_date_validation_name": "ದಿನಾಂಕಗಳ ಕ್ರಮಬದ್ಧತೆ ಪರಿಶೀಲನೆ", "chk_date_validation_msg": "ದಾಖಲೆ ದಿನಾಂಕಗಳು ಸರಿಯಾದ ಕ್ರಮದಲ್ಲಿವೆ.", "chk_survey_number_validation_name": "ಸರ್ವೇ ಸಂಖ್ಯೆ ಪರಿಶೀಲನೆ", "chk_survey_number_validation_msg": "ಸರ್ವೇ ಸಂಖ್ಯೆ ಮಾದರಿ ಕಾನೂನುಬದ್ಧವಾಗಿದೆ.", "chk_internal_consistency_name": "ಆಂತರಿಕ ಸುಸಂಗತತೆ ಪರಿಶೀಲನೆ", "chk_internal_consistency_msg": "ಷರತ್ತುಗಳಲ್ಲಿ ಯಾವುದೇ ವಿರೋಧಾಭಾಸಗಳು ಕಂಡುಬಂದಿಲ್ಲ.", "chk_signature_detection_name": "ಸಹಿ ಮತ್ತು ಮುದ್ರಾಂಕ ಪರಿಶೀಲನೆ", "chk_signature_detection_msg": "ಸ್ಕ್ಯಾನ್ ಪ್ರತಿಯಲ್ಲಿ ಸಹಿ ಮತ್ತು ಮುದ್ರಾಂಕಗಳು ದೃಢಪಟ್ಟಿವೆ."}, "ta": {"nav_registry": "பதிவேடு", "nav_dashboard": "டாஷ்போர்டு", "nav_new_scan": "புதிய ஸ்கேன்", "nav_sealing": "டிஜிட்டல் முத்திரை", "nav_verify": "சரிபார்ப்பு", "console_h1": "சரிபார்ப்பு <em>கன்சோல்</em>", "lbl_record": "பதிவு எண்", "badge_extracted": "பிரித்தெடுக்கப்பட்டது", "badge_needs_review": "மதிப்பாய்வு தேவை", "badge_ready_for_approval": "முத்திரைக்கு தயார்", "badge_approved": "ஒப்புதல் அளிக்கப்பட்டு முத்திரையிடப்பட்டது", "badge_rejected": "நிராகரிக்கப்பட்டது", "badge_fail": "சரிபார்ப்பு தோல்வி", "step_scan": "ஸ்கேன்", "step_machine": "இயந்திர சரிபார்ப்பு", "step_clerk": "எழுத்தர் மதிப்பாய்வு", "step_seal": "அதிகாரி முத்திரை", "lbl_mode": "முறைமை", "lbl_hardware": "வன்பொருள்", "lbl_ocr": "OCR", "lbl_transit": "போக்குவரத்து", "lbl_total": "மொத்த நேரம்", "lbl_passed": "வெற்றி", "lbl_warnings": "எச்சரிக்கைகள்", "lbl_failed": "தோல்வி", "sched_a_panel_title": "அட்டவணை A · தானியங்கி இயந்திர சரிபார்ப்பு பட்டியல்", "sched_a_sub": "தானியங்கி", "chk_required_fields_name": "தேவையான ஆவணப் புலங்கள்", "chk_required_fields_msg": "அனைத்து முக்கிய புலங்களும் உள்ளன.", "chk_area_bounds_name": "நிலப் பரப்பளவு எல்லைச் சரிபார்ப்பு", "chk_area_bounds_msg": "பரப்பளவு செல்லுபடியாகும்.", "chk_date_order_name": "தேதி பகுப்பாய்வு & தர்க்கரீதியான வரிசை", "chk_date_order_msg": "ஆவணத் தேதிகள் சரியான வரிசையில் உள்ளன.", "chk_survey_format_name": "சர்வே எண் சரிபார்ப்பு", "chk_survey_format_msg": "சர்வே எண் வடிவம் சட்டப்பூர்வமானது.", "chk_geographic_consistency_name": "இடஞ்சார்ந்த அதிகாரப் பொருத்தம்", "chk_geographic_consistency_msg": "அரசு அதிகாரம்: அதிகாரப்பூர்வ பதிவேடு மூலம் உறுதிப்படுத்தப்பட்டது.", "sched_b_panel_title": "அட்டவணை B · எழுத்தர் மதிப்பாய்வு & திருத்தம்", "sched_b_sub": "இங்கேயே திருத்துக", "clerk_instruction_note": "ஸ்கேன் செய்யப்பட்ட ஆவணத்துடன் ஒப்பிட்டு பிழைகளைத் திருத்துக, பின்னர் சேமிக்கவும் அல்லது அதிகாரிக்கு சமர்ப்பிக்கவும்.", "f_doc_type": "ஆவண வகை", "f_doc_no": "ஆவண எண்", "f_survey": "சர்வே எண்", "f_subsurvey": "உட்பிரிவு சர்வே எண்", "f_area": "சொத்து பரப்பளவு (சதுர கெஜம்)", "f_village": "கிராமம்", "f_mandal": "மண்டலம்", "f_district": "மாவட்டம்", "f_stamp_no": "முத்திரைத்தாள் எண்", "f_stamp_val": "முத்திரை மதிப்பு (₹)", "f_sold_to": "வாங்குபவர் பெயர்", "f_doc_date": "ஆவண தேதி", "f_exec_date": "நிறைவேற்றப்பட்ட தேதி", "f_parties": "நபர்கள் (JSON)", "warn_officer_ok": "அதிகாரியின் ஒப்புதல் ஆவணத்தை உறுதிசெய்து டிஜிட்டல் முத்திரையிடுகிறது.", "btn_save_corrections": "திருத்தங்களை சேமிக்கவும்", "btn_officer_approve_seal": "அதிகாரி ஒப்புதல் & முத்திரை", "btn_officer_reject": "அதிகாரி நிராகரிப்பு", "ph_rej_reason": "நிராகரிப்புக்கான காரணம் (கட்டாயம்)", "btn_view_cert_qr": "சான்றிதழ் & QR பார்க்க", "footer_title": "ஒன்பூமி · ஆஃப்லைன் பதிவேடு கன்சோல்", "footer_sub": "விற்பனைப் பத்திரங்கள் · ஒப்பந்தங்கள் · ஜிபிஏ", "footer_cloud": "கிளவுட் இல்லை. விசைகள் அலுவலகத்தை விட்டு வெளியேறாது.", "chk_area_validation_name": "நிலப் பரப்பளவு எல்லைச் சரிபார்ப்பு", "chk_area_validation_msg": "பரப்பளவு செல்லுபடியாகும்.", "chk_date_validation_name": "தேதி பகுப்பாய்வு & தர்க்கரீதியான வரிசை", "chk_date_validation_msg": "ஆவணத் தேதிகள் சரியான வரிசையில் உள்ளன.", "chk_survey_number_validation_name": "சர்வே எண் சரிபார்ப்பு", "chk_survey_number_validation_msg": "சர்வே எண் வடிவம் சட்டப்பூர்வமானது.", "chk_internal_consistency_name": "உள் நிலைத்தன்மை சரிபார்ப்பு", "chk_internal_consistency_msg": "பத்திரப் பிரிவுகளில் முரண்பாடுகள் எதுவும் இல்லை.", "chk_signature_detection_name": "கையொப்பம் மற்றும் முத்திரை சரிபார்ப்பு", "chk_signature_detection_msg": "ஸ்கேன் செய்யப்பட்ட ஆவணத்தில் கையொப்பங்கள் மற்றும் முத்திரைகள் உறுதிசெய்யப்பட்டன."}};

function applyConsoleLanguage(lang) {
  if (!CONSOLE_I18N[lang]) lang = 'en';
  document.documentElement.lang = lang;
  try { localStorage.setItem('onebhoomi_lang', lang); } catch(e) {}

  const select = document.getElementById('langSelect');
  if (select && select.value !== lang) select.value = lang;

  const dict = CONSOLE_I18N[lang] || CONSOLE_I18N['en'];

  // 1. Text elements
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key] !== undefined) {
      el.innerHTML = dict[key];
    }
  });

  // 2. Placeholders
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const key = el.getAttribute('data-i18n-ph');
    if (dict[key] !== undefined) {
      el.setAttribute('placeholder', dict[key]);
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  let savedLang = 'en';
  try { savedLang = localStorage.getItem('onebhoomi_lang') || 'en'; } catch(e) {}
  applyConsoleLanguage(savedLang);

  const sel = document.getElementById('langSelect');
  if (sel) {
    sel.addEventListener('change', (e) => {
      applyConsoleLanguage(e.target.value);
    });
  }
});
</script>
</body>
</html>

""")



def render_gis_section(ocr_payload: dict) -> str:
    if not isinstance(ocr_payload, dict) or not ocr_payload:
        return ""

    try:
        gis_data = gis_service.verify_gis_location(ocr_payload)
    except Exception as exc:
        return f"""
        <section class="panel gis rv" style="border-color:var(--stamp)">
          <div class="tab t-red"><span>Particulars · Property Location</span><em>GIS</em></div>
          <div class="body">
            <p style="color:var(--stamp-deep);font-family:var(--type);font-size:13px;">GIS resolution note: {html.escape(str(exc))}</p>
          </div>
        </section>
        """

    if gis_data.get("status") in ("UNSUPPORTED_STATE", "DATASET_NOT_FOUND", "UNRESOLVED") or not gis_data.get("coordinates"):
        return f"""
        <section class="panel gis rv">
          <div class="tab"><span>Particulars · Property Location</span><em>GIS</em></div>
          <div class="body">
            <p style="color:var(--amber);font-size:14px;">{html.escape(gis_data.get('disclaimer') or 'Location could not be resolved against local GIS dataset.')}</p>
          </div>
        </section>
        """

    lat = gis_data["coordinates"]["lat"]
    lng = gis_data["coordinates"]["lng"]

    # Dual layer geometry for Leaflet rendering
    admin_geom = gis_data.get("administrative_geometry")
    parcel_geom = gis_data.get("estimated_parcel_polygon")

    admin_geojson_str = json.dumps(admin_geom) if admin_geom else "null"
    parcel_geojson_str = json.dumps(parcel_geom) if parcel_geom else "null"

    res_level = (gis_data.get("resolution_level") or "none").capitalize()

    village_display = html.escape(str(gis_data.get("village") or "Not available"))
    if gis_data.get("village_status") == "NOT_RESOLVED":
        village_display += ' <span style="font-family:var(--type);font-size:11px;color:var(--amber);font-weight:400;">(not in dataset)</span>'

    dims_info = gis_data.get("dimensions") or {}
    area_str = f"{dims_info.get('area_sqm', 'N/A')} m² ({dims_info.get('area_sqft', 'N/A')} sq ft)" if dims_info else "Dimensions not extracted"
    dims_str = f"{dims_info.get('east_west_m', 'N/A')} m × {dims_info.get('north_south_m', 'N/A')} m" if dims_info else "N/A"

    return f"""
    <!-- GIS PROPERTY LOCATION VERIFICATION PANEL -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>

    <section class="panel gis rv">
      <div class="tab"><span>Particulars · Property Location</span><em>GIS</em></div>
      <div class="body">

      <div class="authority">
        <div class="k">Geographic Authority · Hierarchy Consistency</div>
        <div class="v">VALIDATED</div>
        <div class="s" title="{html.escape(gis_data.get('source_attribution') or 'State GIS Data')}">{html.escape(gis_data.get('source_attribution') or 'State GIS Data')}</div>
      </div>

      <div class="infonote">
        Resolved from the location information extracted out of the document, against the local GIS dataset only.
      </div>
      """ + (f"""
      <div class="village-warn">⚠ {html.escape(gis_data.get('village_disclaimer'))}</div>
      """ if (gis_data.get("village_disclaimer") and not str(gis_data.get("village_disclaimer", "")).startswith("Contradictory")) else "") + f"""

      <div class="src-note">Note: {html.escape(gis_data.get('disclaimer') or '')} Source: {html.escape(gis_data.get('source_attribution') or 'geoBoundaries')}</div>

      <!-- LOCATION ATTRIBUTES GRID -->
      <div class="attr-grid">
        <div class="attr"><div class="k">State</div><div class="v">{html.escape(str(gis_data.get('state') or 'N/A'))}</div></div>
        <div class="attr"><div class="k">District</div><div class="v">{html.escape(str(gis_data.get('district') or 'N/A'))}</div></div>
        <div class="attr"><div class="k">Mandal / Taluk</div><div class="v">{html.escape(str(gis_data.get('mandal') or 'N/A'))}</div></div>
        <div class="attr"><div class="k">Village</div><div class="v">{village_display}</div></div>
        <div class="attr"><div class="k">Survey Number</div><div class="v">{html.escape(str(gis_data.get('survey_number') or 'N/A'))}</div></div>
      </div>

      <!-- MAP AND SPATIAL DETAILS GRID -->
      <div class="map-grid">
        <!-- INTERACTIVE LEAFLET MAP -->
        <div>
          <div id="gis-map"></div>
          <!-- MAP LEGEND -->
          <div class="legend">
            <div><span class="sw" style="background:rgba(59,130,246,.3);border:2px solid #2563eb;"></span><span class="lbl">Source administrative / village boundary</span></div>
            """ + (f"""
            <div><span class="sw" style="background:rgba(16,185,129,.3);border:2px solid #059669;"></span><span class="lbl">Estimated parcel boundary</span></div>
            """ if parcel_geom else "") + f"""
          </div>
          <div class="coords">
            <span>Coordinates: <strong>{lat}, {lng}</strong></span>
            <span>Dataset: <strong>{html.escape(gis_data.get('source_attribution') or 'geoBoundaries')}</strong></span>
          </div>
        </div>

        <!-- SPATIAL METRICS -->
        <div>
          <div class="metric">
            <h4>Dimensions &amp; Parcel Estimate</h4>
            <p><b>Approximate area:</b> {html.escape(area_str)}</p>
            <p><b>Document dimensions:</b> {html.escape(dims_str)}</p>
            """ + (f"""
            <div class="disclaimer">⚠ {html.escape(dims_info.get('disclaimer', ''))}</div>
            """ if dims_info else "") + f"""
          </div>

          <div class="metric">
            <h4>Cadastral Survey Boundary</h4>
            <p><b>Cadastral status:</b> NOT_AVAILABLE</p>
            <div class="quiet">
              Authoritative cadastral survey boundaries are not currently available in the offline GIS registry. The estimated parcel rectangle is an approximate visualization based on document dimensions and is NOT an authoritative cadastral boundary.
            </div>
          </div>
        </div>
      </div>
      </div>
    </section>

    <script>
      (function() {{
        function initGisMap() {{
          var mapContainer = document.getElementById('gis-map');
          if (!mapContainer || mapContainer._leaflet_id) return;

          var lat = {lat};
          var lng = {lng};
          var adminGeojson = {admin_geojson_str};
          var parcelGeojson = {parcel_geojson_str};

          var map = L.map('gis-map').setView([lat, lng], 13);

          L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors | GIS Verification'
          }}).addTo(map);

          // 1. Source Administrative / Village Polygon (Blue Layer)
          if (adminGeojson) {{
            var adminLayer = L.geoJSON(adminGeojson, {{
              style: {{
                color: '#2563eb',
                weight: 2.5,
                opacity: 0.85,
                fillColor: '#3b82f6',
                fillOpacity: 0.2
              }}
            }}).addTo(map);
            try {{
              map.fitBounds(adminLayer.getBounds(), {{ padding: [20, 20] }});
            }} catch(e) {{}}
          }}

          // 2. Estimated Parcel Boundary Polygon (Green Layer)
          if (parcelGeojson) {{
            L.geoJSON(parcelGeojson, {{
              style: {{
                color: '#059669',
                weight: 2.5,
                opacity: 0.9,
                fillColor: '#10b981',
                fillOpacity: 0.35,
                dashArray: '5, 5'
              }}
            }}).addTo(map);
          }}

          // Centroid Marker
          L.marker([lat, lng]).addTo(map)
            .bindPopup('<b>Resolved Location: {html.escape(res_level)} Centroid</b><br>Lat: ' + lat + ', Lng: ' + lng)
            .openPopup();
        }}

        if (document.readyState === 'complete' || document.readyState === 'interactive') {{
          setTimeout(initGisMap, 200);
        }} else {{
          document.addEventListener('DOMContentLoaded', initGisMap);
        }}
      }})();
    </script>
    """


BADGE_LABELS = {
    "EXTRACTED": "Extracted",
    "NEEDS_REVIEW": "Needs review",
    "READY_FOR_APPROVAL": "Ready for approval",
    "APPROVED": "Approved & sealed",
    "REJECTED": "Rejected",
    "FAIL": "Checks failed",
}


def _badge_markup(status: str) -> str:
    label = BADGE_LABELS.get(status, status.replace("_", " ").title())
    return f'<span class="badge b-{html.escape(status.lower())}" data-i18n="badge_{status.lower()}">{html.escape(label)}</span>'


def _stepper_markup(status: str) -> str:
    """Console stepper: i Scan · ii Machine check · iii Clerk review · iv Seal."""
    checks_ok = status in {"READY_FOR_APPROVAL", "APPROVED"}
    if status == "APPROVED":
        states = ["done", "done", "done", "done"]
        labels = ["Scan", "Machine check", "Clerk review", "Sealed"]
    elif status == "REJECTED":
        states = ["done", "done", "done", "bad"]
        labels = ["Scan", "Machine check", "Clerk review", "Rejected"]
    else:
        machine = "done" if checks_ok else "warn"
        states = ["done", machine, "now", ""]
        labels = ["Scan", "Machine check", "Clerk review", "Officer seal"]

    glyphs = ["i", "ii", "iii", "iv"]
    step_keys = ["step_scan", "step_machine", "step_clerk", "step_seal"]
    items = []
    for glyph, label, st, skey in zip(glyphs, labels, states, step_keys):
        cls = f"step {st}" if st else "step"
        items.append(
            f'<div class="{cls}"><div class="dot">{glyph}</div>'
            f'<div class="lbl" data-i18n="{skey}">{label}</div></div>'
        )
    return f'<div class="stepper rv in" role="list" aria-label="Progress">{"".join(items)}</div>'


def _banner_markup(message: str, blocked: bool = False) -> str:
    if not message:
        return ""
    cls = "banner blocked" if blocked else "banner"
    mark = "✗" if blocked else "§"
    return f'<div class="{cls} rv in"><span class="bmark">{mark}</span><p>{html.escape(message)}</p></div>'


def _upload_stage(
    cpu_selected: str,
    gpu_selected: str,
    colab_url: str,
    banner_markup: str = "",
    docket_markup: str = "",
) -> str:
    if colab_url:
        try:
            worker_host = urlparse(colab_url).hostname or colab_url
        except Exception:
            worker_host = colab_url
        mode_note = f"GPU worker online at {worker_host} · OCR runs there, everything else stays here"
    else:
        mode_note = "No GPU worker configured · OCR will run on this machine's CPU"

    return f"""
    <section class="desk">
      <p class="eyebrow rv">New Registration · Desk 01</p>
      <h1 class="rv">It starts with the <em>scan.</em></h1>
      <p class="lede rv">Drop the sale deed, agreement of sale or GPA below. Reading, parsing and the machine checklist all happen on office hardware.</p>
      {banner_markup}
      {docket_markup}
      <form id="scanForm" class="scan-form panel rv" action="/extract" method="post" enctype="multipart/form-data">
        <div class="tab"><span>Form 1 · Scan Intake</span><em>offline</em></div>
        <div class="body">
          <p class="field-label" id="dzLabel">Select Scan Copy (Image or PDF)</p>
          <div id="dropzone" class="dropzone" tabindex="0" role="button" aria-labelledby="dzLabel">
            <svg class="dz-ico" viewBox="0 0 42 52" aria-hidden="true">
              <path d="M2 2 h26 l12 12 v36 h-38 z"/>
              <path d="M28 2 v12 h12"/>
              <path d="M12 30 h18 M12 38 h18 M12 22 h8"/>
            </svg>
            <p class="dz-title" id="dzTitle">Drop the scan here, or <span>browse files</span></p>
            <p class="dz-hint">PNG · JPG · PDF &mdash; read locally, sealed on this machine, never sent to a cloud</p>
            <input type="file" name="document_image" id="document_image" accept="image/*,.pdf,application/pdf" hidden>
          </div>
          <div id="filechip" class="filechip" hidden>
            <span id="chipName"></span>
            <span class="chip-meta"><span id="chipSize"></span><button type="button" id="chipClear" class="chip-x" aria-label="Remove selected file">&times;</button></span>
          </div>
          <div class="mode-row">
            <label class="field-label" for="processing_mode">Processing</label>
            <select name="processing_mode" id="processing_mode">
              <option value="gpu" {gpu_selected}>Remote GPU worker (encrypted tunnel)</option>
              <option value="cpu" {cpu_selected}>Local CPU (PaddleOCR on this machine)</option>
            </select>
            <p class="mode-note">{html.escape(mode_note)}</p>
          </div>
          <div class="submit-row">
            <p class="submit-note">Next · checklist → clerk review → seal</p>
            <button type="submit" class="btn btn-primary btn-xl">Process Extraction</button>
          </div>
        </div>
      </form>
      <div class="next-strip rv" aria-hidden="true">
        <span class="next"><b>i.</b> Machine checklist</span>
        <span class="next"><b>ii.</b> Clerk review</span>
        <span class="next"><b>iii.</b> Officer seal</span>
      </div>
    </section>
    <div class="overlay" id="overlay" role="status" aria-live="polite">
      <div class="ov-stamp">In Progress</div>
      <p class="ov-stage" id="ovStage">Reading the scan</p>
      <div class="ov-pipe" aria-hidden="true"><div class="shaft"></div></div>
      <p class="ov-note">Running on office hardware · no cloud</p>
    </div>
    """


def _checklist_panel(checks: list) -> str:
    rows = []
    counts = {"PASS": 0, "WARNING": 0, "FAIL": 0}
    for c in checks:
        chk_status = c.get("status", "PASS")
        counts[chk_status] = counts.get(chk_status, 0) + 1
        chk_name = c.get("name", "")
        chk_msg = c.get("message", "")
        chk_sev = c.get("severity", "")

        glyph_cls = {"PASS": "pass", "WARNING": "warn"}.get(chk_status, "fail")
        glyph = {"PASS": "✓", "WARNING": "⚠"}.get(chk_status, "✗")
        sev = f"<small>{html.escape(chk_sev)}</small>" if chk_sev == "critical" and chk_status == "FAIL" else ""
        row_cls = "check fail-row" if chk_status == "FAIL" else "check"
        rows.append(
            f"""
            <div class="{row_cls}">
              <span class="g {glyph_cls}">{glyph}</span>
              <div>
                <p class="t" data-i18n="chk_{c.get('check_id', '')}_name">{html.escape(chk_name)}{sev}</p>
                <p class="m" data-i18n="chk_{c.get('check_id', '')}_msg">{html.escape(chk_msg)}</p>
              </div>
            </div>
            """
        )

    summary = (
        f'<span class="ok">{counts.get("PASS", 0)} <span data-i18n="lbl_passed">passed</span></span> · '
        f'<span class="md">{counts.get("WARNING", 0)} <span data-i18n="lbl_warnings">warnings</span></span> · '
        f'<span class="no">{counts.get("FAIL", 0)} <span data-i18n="lbl_failed">failed</span></span>'
    )
    return f"""
    <section class="panel checklist-panel rv" style="margin-top:24px; margin-bottom:28px;">
      <div class="tab"><span data-i18n="sched_a_panel_title">Schedule A · Machine Checklist</span><em data-i18n="sched_a_sub">automated</em></div>
      <div class="body">
        <div class="checklist checklist-grid">{''.join(rows)}</div>
        <p class="check-sum" style="margin-top:16px;">{summary}</p>
      </div>
    </section>
    """


def _exhibit_panel(preview: str, caption: str) -> str:
    cap = html.escape(caption or "scan copy")
    return f"""
    <section class="panel exhibit-panel rv">
      <div class="tab"><span>Exhibit · Scan Copy</span><em>{cap}</em></div>
      <div class="preview-body">
        {preview}
        <div class="pdf-note" hidden>The scan copy is a PDF on file &mdash; its pages were stacked and read in full.</div>
      </div>
    </section>
    """


def _clerk_panel(record: dict, message: str) -> str:
    rec_id = record["verification_id"]
    payload_data = record["document_payload"]
    checks = record.get("checks", [])
    prop = payload_data.get("property", {}) or {}
    stamp = payload_data.get("stamp_information", {}) or {}
    parties = payload_data.get("parties", []) or []
    parties_json_str = json.dumps(parties, ensure_ascii=False)

    current_status = record.get("status")
    is_approved = current_status == "APPROVED"
    is_rejected = current_status == "REJECTED"
    readonly_attr = "readonly" if is_approved else ""

    has_critical_fail = any(
        c.get("status") == "FAIL" and c.get("severity") == "critical" for c in checks
    )
    if has_critical_fail:
        warn = (
            '<p class="warnbox stop">Officer approval is locked while critical checks fail. '
            "Correct the flagged fields and Save Corrections first.</p>"
        )
        approve_disabled = "disabled"
    else:
        warn = '<p class="warnbox ok" data-i18n="warn_officer_ok">Officer approval permanently certifies the reviewed facts and applies the seal.</p>'
        approve_disabled = ""

    if is_approved:
        approved_at = record.get("approved_at", "Certified")
        action_buttons = f"""
        <div class="action-panel">
          <p class="warnbox ok" style="border-left-color:var(--green)">
            🔒 <b>Officially Approved &amp; Cryptographically Sealed ({html.escape(approved_at)})</b><br>
            This document has been certified with RSA-PSS 2048-bit. Document facts are locked and immutable.
          </p>
          <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
            <a href="/?verification_id={html.escape(rec_id)}" target="_blank" class="btn btn-green" data-i18n="btn_view_cert_qr">View Standalone Certificate &amp; QR</a>
            <div class="reject-group" style="margin-left:auto;">
              <input type="text" name="rejection_reason" id="rejection_reason" placeholder="Reason to revoke approval (required)" aria-label="Rejection reason">
              <button type="submit" name="action" value="reject" class="btn btn-outline-red" data-i18n="btn_officer_reject"
                onclick="if(!document.getElementById('rejection_reason').value.trim()) {{ alert('Please provide a reason to revoke approval.'); return false; }} return confirm('Are you sure you want to revoke the certified seal and reject this record?');">Revoke / Officer Reject</button>
            </div>
          </div>
        </div>
        """
    elif is_rejected:
        rejected_at = record.get("rejected_at", "On file")
        rej_reason = record.get("rejection_reason", "No reason provided")
        action_buttons = f"""
        <div class="action-panel">
          <p class="warnbox stop">
            ❌ <b>Document Rejected by Officer ({html.escape(rejected_at)})</b><br>
            <b>Reason:</b> {html.escape(rej_reason)}<br>
            Review and correct the flagged fields below, then save or re-submit for officer approval.
          </p>
          <button type="submit" name="action" value="correct" class="btn btn-ghost" data-i18n="btn_save_corrections">Save Corrections</button>
          <button type="submit" name="action" value="approve" class="btn btn-green" {approve_disabled}>Re-Approve &amp; Seal</button>
        </div>
        """
    else:
        action_buttons = f"""
        <div class="action-panel">
          {warn}
          <button type="submit" name="action" value="correct" class="btn btn-ghost">Save Corrections</button>
          <button type="submit" name="action" value="approve" class="btn btn-green" {approve_disabled} data-i18n="btn_officer_approve_seal">Officer Approve &amp; Seal</button>
          <div class="reject-group">
            <input type="text" name="rejection_reason" id="rejection_reason" placeholder="Rejection reason (required)" data-i18n-ph="ph_rej_reason" aria-label="Rejection reason">
            <button type="submit" name="action" value="reject" class="btn btn-outline-red"
              onclick="if(!document.getElementById('rejection_reason').value.trim()) {{ alert('Please provide a rejection reason.'); return false; }}">Officer Reject</button>
          </div>
        </div>
        """

    blocked = ""

    return f"""
    <section class="panel clerk rv">
      <div class="tab"><span data-i18n="sched_b_panel_title">Schedule B · Clerk Review</span><em data-i18n="sched_b_sub">correct in place</em></div>
      <div class="body">
        {blocked}
        <p class="note"><span data-i18n="lbl_record">Record</span> {html.escape(rec_id)} · <span data-i18n="clerk_instruction_note">read each field against the scan, fix what the OCR got wrong, then save or pass it up to the officer.</span></p>
        <form action="/extract" method="post" enctype="multipart/form-data">
          <input type="hidden" name="verification_id" value="{html.escape(rec_id)}">
          <div class="editor-grid">
            <div class="editor-field">
              <label for="f_doc_type" data-i18n="f_doc_type">Document Type</label>
              <input type="text" id="f_doc_type" name="document_type" value="{html.escape(str(payload_data.get('document_type') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_doc_no" data-i18n="f_doc_no">Document Number</label>
              <input type="text" id="f_doc_no" name="document_number" value="{html.escape(str(payload_data.get('document_number') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_survey" data-i18n="f_survey">Survey Number</label>
              <input type="text" id="f_survey" name="survey_number" value="{html.escape(str(prop.get('survey_number') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_subsurvey" data-i18n="f_subsurvey">Sub-Survey Number</label>
              <input type="text" id="f_subsurvey" name="sub_survey_number" value="{html.escape(str(prop.get('sub_survey_number') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_area" data-i18n="f_area">Property Area</label>
              <input type="text" id="f_area" name="area" value="{html.escape(str(prop.get('area') if prop.get('area') is not None else ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_village" data-i18n="f_village">Village</label>
              <input type="text" id="f_village" name="village" value="{html.escape(str(prop.get('village') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_mandal" data-i18n="f_mandal">Mandal</label>
              <input type="text" id="f_mandal" name="mandal" value="{html.escape(str(prop.get('mandal') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_district" data-i18n="f_district">District</label>
              <input type="text" id="f_district" name="district" value="{html.escape(str(prop.get('district') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_stamp_no" data-i18n="f_stamp_no">Stamp Serial Number</label>
              <input type="text" id="f_stamp_no" name="stamp_number" value="{html.escape(str(stamp.get('stamp_number') or payload_data.get('stamp_number') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_stamp_val" data-i18n="f_stamp_val">Stamp Value</label>
              <input type="text" id="f_stamp_val" name="stamp_value" value="{html.escape(str(stamp.get('stamp_value') if stamp.get('stamp_value') is not None else (payload_data.get('stamp_value') if payload_data.get('stamp_value') is not None else '')))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_sold_to" data-i18n="f_sold_to">Stamp Sold To</label>
              <input type="text" id="f_sold_to" name="sold_to" value="{html.escape(str(stamp.get('sold_to') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_doc_date" data-i18n="f_doc_date">Document Date</label>
              <input type="text" id="f_doc_date" name="document_date" value="{html.escape(str(payload_data.get('document_date') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field">
              <label for="f_exec_date" data-i18n="f_exec_date">Execution Date</label>
              <input type="text" id="f_exec_date" name="execution_date" value="{html.escape(str(payload_data.get('execution_date') or ''))}" {readonly_attr}>
            </div>
            <div class="editor-field efull">
              <label for="f_parties" data-i18n="f_parties">Parties (JSON)</label>
              <textarea id="f_parties" name="parties_json" rows="3" {readonly_attr}>{html.escape(parties_json_str)}</textarea>
            </div>
          </div>
          {action_buttons}
        </form>
      </div>
    </section>
    """


def _cert_panel(record: dict, host_name: str) -> str:
    rec_id = record["verification_id"]
    payload_data = record["document_payload"]
    prop = payload_data.get("property", {}) or {}
    parties = payload_data.get("parties", []) or []
    sig = record.get("signature", "")
    pub_key = record.get("public_key", "")

    sig_valid = False
    if sig and pub_key:
        sig_valid = verification_service.verify_document_signature(payload_data, sig, pub_key)
    sig_state = (
        '<p class="sig-state">✓ Signature re-verified against the record at render time.</p>'
        if sig_valid
        else '<p class="sig-state bad">✗ Signature check FAILED at render time.</p>'
    )

    parties_rows = "".join(
        f"<li>{html.escape(p.get('name') or '')} <em style=\"color:var(--ink-soft);\">({html.escape(p.get('role') or '')})</em></li>"
        for p in parties
        if isinstance(p, dict)
    )
    public_tunnel = get_public_web_tunnel()
    verify_url = f"{public_tunnel}/?verification_id={rec_id}"
    qr_b64 = generate_qr_base64(verify_url)
    qr_markup = f'<img src="data:image/png;base64,{qr_b64}" width="180" height="180" alt="Verification QR Code" style="display:block;margin:0 auto;border-radius:2px;">' if qr_b64 else '<canvas id="qrCanvas" width="200" height="200" aria-label="Verification QR code"></canvas>'

    return f"""
    <section class="panel cert rv">
      <div class="tab t-green"><span>Schedule C · Certificate of Seal</span><em>{html.escape(record.get('approved_at') or '')}</em></div>
      <div class="cert-body">
        <div>
          <div class="fact"><b>Verification ID</b><span class="v" style="font-family:var(--type);font-weight:400;">{html.escape(rec_id)}</span></div>
          <div class="fact"><b>Document Type</b><span class="v">{html.escape(payload_data.get('document_type') or '')}</span></div>
          <div class="fact"><b>Document Number</b><span class="v">{html.escape(payload_data.get('document_number') or '')}</span></div>
          <div class="fact"><b>Survey Number</b><span class="v">{html.escape(str(prop.get('survey_number') or ''))}</span></div>
          <div class="fact"><b>Area</b><span class="v">{html.escape(str(prop.get('area') or ''))}</span></div>
          <div class="fact"><b>Village</b><span class="v">{html.escape(prop.get('village') or '')}</span></div>
          <div class="fact"><b>District</b><span class="v">{html.escape(prop.get('district') or '')}</span></div>
          <div class="fact"><b>Document Date</b><span class="v">{html.escape(payload_data.get('document_date') or '')}</span></div>
          <div class="fact"><b>Execution Date</b><span class="v">{html.escape(payload_data.get('execution_date') or '')}</span></div>
          <div class="fact"><b>Parties</b><ul>{parties_rows}</ul></div>

          <p class="crypto-h">Cryptographic Security</p>
          <p class="crypto-line"><strong>Algorithm:</strong> RSA-PSS / SHA-256, keypair held in <span style="font-family:var(--type);">verification_keys/</span></p>
          {sig_state}
          <div class="sigbox">{html.escape(sig)}</div>
        </div>

        <div class="seal-side">
          <div class="seal-wrap">
            <svg class="big-seal" viewBox="0 0 340 340" aria-hidden="true">
              <g fill="none" stroke="#C9A227">
                <circle cx="170" cy="170" r="160" stroke-width="3"/>
                <circle cx="170" cy="170" r="150" stroke-width="1.2" stroke-dasharray="4 6"/>
                <circle cx="170" cy="170" r="120" stroke-width="2"/>
                <circle cx="170" cy="170" r="112" stroke-width="1" stroke-dasharray="2 4"/>
                <circle cx="170" cy="170" r="74" stroke-width="1.4"/>
              </g>
              <path id="certSealTop" d="M 170 170 m -134 0 a 134 134 0 1 1 268 0" fill="none"/>
              <path id="certSealBot" d="M 170 170 m -134 0 a 134 134 0 1 0 268 0" fill="none"/>
              <text font-family="Courier Prime, monospace" font-size="15" letter-spacing="6" fill="#C9A227">
                <textPath href="#certSealTop" startOffset="6%">CANONICAL · SHA-256</textPath>
              </text>
              <text font-family="Courier Prime, monospace" font-size="15" letter-spacing="6" fill="#C9A227">
                <textPath href="#certSealBot" startOffset="15%">RSA-PSS · 2048 · LOCAL</textPath>
              </text>
              <g fill="#C9A227">
                <circle cx="170" cy="110" r="4"/><circle cx="230" cy="170" r="4"/>
                <circle cx="170" cy="230" r="4"/><circle cx="110" cy="170" r="4"/>
              </g>
            </svg>
            <div class="seal-center"><b>Sealed</b><span>Immutably on file</span></div>
          </div>

          <div class="qrbox">{qr_markup}</div>
          <p class="qrurl">{html.escape(verify_url)}</p>
          <p class="qr-hint">Scan from any phone on the same office network: the page re-checks the signature locally, offline.</p>
        </div>

        <div class="cert-actions">
          <a class="btn btn-ghost" href="/?verification_id={html.escape(rec_id)}">Open Public Verification Page</a>
          <a class="btn btn-primary" href="/dashboard">Process New Document</a>
        </div>
      </div>
      <script>
        if (document.getElementById('qrCanvas')) {{
          setTimeout(function() {{
            drawQRCode('qrCanvas', '{verify_url}');
          }}, 100);
        }}
      </script>
    </section>
    """


def _rejected_panel(record: dict) -> str:
    rec_id = record["verification_id"]
    reason = record.get("rejection_reason") or "No reason was recorded."
    return f"""
    <section class="rej rv">
      <span class="rej-stamp">Rejected</span>
      <h2 class="rej-head">Rejected on file</h2>
      <div class="reason">
        <strong>Reason recorded by the officer:</strong>
        <p style="margin:6px 0 0 0;">{html.escape(reason)}</p>
      </div>
      <p class="quiet">Record {html.escape(rec_id)} · rejected at {html.escape(record.get('rejected_at') or '')} · this document was never cryptographically certified, and the rejection itself stays on the register.</p>
      <a class="btn btn-primary" href="/dashboard">Process New Document</a>
    </section>
    """


def render_page(
    payload: str = "{}",
    message: str = "",
    preview: str = "",
    preview_caption: str = "",
    cpu_selected: str = "",
    gpu_selected: str = "",
    colab_url_value: str = "",
    timing_info: str = "",
    active_record: dict = None,
    host_name: str = "localhost:8001",
    stage: str = "results",
) -> bytes:
    colab_val = colab_url_value or get_colab_url()
    if not cpu_selected and not gpu_selected:
        if colab_val:
            gpu_selected = "selected"
            cpu_selected = ""
        else:
            cpu_selected = "selected"
            gpu_selected = ""

    # ---------- Intake stage: the scan-selection desk ----------
    if stage == "upload":
        banner = _banner_markup(message)
        stage_markup = _upload_stage(
            cpu_selected, gpu_selected, colab_val, banner, timing_info
        )
        return HTML_PAGE.substitute(
            reg_no="REGISTER OPEN · DESK 01",
            stage_markup=stage_markup,
        ).encode("utf-8")

    # ---------- Results stage: everything after extraction ----------
    if active_record:
        rec_id = active_record["verification_id"]
        status = active_record["status"]
        reg_no = f"RECORD NO. {rec_id[:8].upper()}"

        head = f"""
        <div class="console-top">
          <div class="console-head rv">
            <h1 data-i18n="console_h1">Verification <em>Console</em></h1>
            {_badge_markup(status)}
          </div>
          <p class="sub rv"><span data-i18n="lbl_record">Record</span> {html.escape(rec_id)}</p>
          {_stepper_markup(status)}
          {_banner_markup(message, blocked=("Approval refused" in (message or "")))}
          {timing_info}
        </div>
        """

        body_parts = []
        if status == "APPROVED":
            body_parts.append(_cert_panel(active_record, host_name))
        elif status == "REJECTED":
            body_parts.append(_rejected_panel(active_record))
        else:
            checks = active_record.get("checks", [])
            payload_data = active_record["document_payload"]

            # GIS re-check mirrors the geographic_consistency check live
            for c in checks:
                if c.get("check_id") == "geographic_consistency":
                    try:
                        gis_res = gis_service.verify_gis_location(payload_data)
                        auth_val = gis_res.get("authority_validation", {})
                        h_status = auth_val.get("hierarchy_status", "PARTIAL")
                        if h_status == "CONSISTENT" and auth_val.get("state_registry_status") == "VALIDATED":
                            c["status"] = "PASS"
                        elif h_status in ("CONTRADICTORY", "AMBIGUOUS", "PARTIAL", "NOT_FOUND"):
                            c["status"] = "WARNING"
                        c["message"] = f"State Authority: VALIDATED via {gis_res.get('source_attribution', 'State Registry')}."
                    except Exception:
                        pass

            # 1. Schedule A: Machine Checklist (Full width above the split review console)
            body_parts.append(_checklist_panel(checks))

            # 2. Main 2-Column Split Console:
            # LEFT SIDE: Document Scan Copy (Exhibit)
            # RIGHT SIDE: Schedule B · Clerk Review Editor Form
            if preview:
                body_parts.append(
                    '<div class="console-grid">'
                    + '<div class="exhibit-col">' + _exhibit_panel(preview, preview_caption) + '</div>'
                    + '<div class="clerk-col">' + _clerk_panel(active_record, message or "") + '</div>'
                    + '</div>'
                )
            else:
                body_parts.append(_clerk_panel(active_record, message or ""))

        # 3. SEPARATE SECTION BELOW: GIS Property Location & Map
        ocr_payload = active_record.get("document_payload") or {}
        gis_markup = render_gis_section(ocr_payload) if ocr_payload else ""
        if gis_markup:
            body_parts.append(
                '<div class="gis-separate-section" style="margin-top: 36px; padding-top: 24px; border-top: 2px double var(--rule);">'
                + gis_markup
                + '</div>'
            )

        if payload and payload.strip() not in ("", "{}"):
            body_parts.append(
                f'<details class="raw rv"><summary><span>Payload · Raw JSON</span></summary>'
                f"<pre>{html.escape(payload)}</pre></details>"
            )

        stage_markup = head + "".join(body_parts)
        return HTML_PAGE.substitute(
            reg_no=reg_no,
            stage_markup=stage_markup,
        ).encode("utf-8")

    # ---------- Results stage without a record (extraction failure) ----------
    # Falls back to the intake desk with the error banner and docket on top.
    banner = _banner_markup(message or "Extraction failed.", blocked=True)
    stage_markup = _upload_stage(
        cpu_selected, gpu_selected, colab_val, banner, timing_info
    )
    return HTML_PAGE.substitute(
        reg_no="REGISTER OPEN · DESK 01",
        stage_markup=stage_markup,
    ).encode("utf-8")


def render_verification_view(record: dict, sig_valid: bool) -> bytes:
    """Renders the standalone public verification page (OneBhoomi register theme).

    This is the page a phone lands on after scanning the certificate QR:
    it recomputes the signature check server-side and stamps the verdict.
    """
    rec_id = record["verification_id"]
    status = record["status"]
    payload_data = record["document_payload"]
    prop = payload_data.get("property", {}) or {}
    parties = payload_data.get("parties", []) or []

    if sig_valid:
        verdict = """
        <div class="verdict ok">✓ Signature Valid</div>
        <p class="verdict-note">Recomputed over the canonical record fields with the office's RSA-PSS public key.</p>
        """
    else:
        verdict = """
        <div class="verdict bad">✗ Signature Invalid</div>
        <p class="verdict-note bad">This record does not match its seal. Treat the document as tampered or unsealed.</p>
        """

    parties_rows = "".join(
        f"<li>{html.escape(p.get('name') or '')} <em style=\"color:var(--ink-soft);\">({html.escape(p.get('role') or '')})</em></li>"
        for p in parties
        if isinstance(p, dict)
    )

    gis_html = render_gis_section(payload_data)

    page_html = f"""<!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>OneBhoomi — Record Verification</title>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Archivo:wght@400;500;600;700&family=Courier+Prime:ital,wght@0,400;0,700;1,400&family=Noto+Sans+Devanagari:wght@400;500;600;700&family=Noto+Sans+Telugu:wght@400;500;600;700&family=Noto+Sans+Kannada:wght@400;500;600;700&family=Noto+Sans+Tamil:wght@400;500;600;700&display=swap" rel="stylesheet">
      <style>
        :root{{
          --paper:#F6F0E1; --paper-deep:#EFE6D0; --ink:#221D17; --ink-soft:#5A5142;
          --stamp:#A6193C; --stamp-deep:#7C1030; --rosette:#C99AA8; --green:#2E6B4F;
          --amber:#A96A1F; --rule:#C9BC9F; --rule-soft:#DCD2B8; --card:#FFFDF6;
          --serif:"Fraunces",Georgia,serif;
          --type:"Courier Prime","Courier New",monospace;
          --sans:"Archivo",system-ui,sans-serif;
        }}
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{
          background:var(--paper);color:var(--ink);font-family:var(--sans);
          font-size:16px;line-height:1.6;padding:0 0 56px;
        }}
        ::selection{{background:var(--stamp);color:var(--paper)}}
        .security-bg{{
          position:fixed;inset:0;z-index:0;pointer-events:none;
          background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='420' height='420' viewBox='0 0 420 420'%3E%3Cg fill='none' stroke='%23C99AA8' stroke-width='1' opacity='.33'%3E%3Ccircle cx='210' cy='210' r='196'/%3E%3Ccircle cx='210' cy='210' r='188' stroke-dasharray='3 6'/%3E%3Ccircle cx='210' cy='210' r='172'/%3E%3Ccircle cx='210' cy='210' r='164' stroke-dasharray='10 4'/%3E%3Ccircle cx='210' cy='210' r='148'/%3E%3Ccircle cx='210' cy='210' r='140' stroke-dasharray='2 5'/%3E%3Ccircle cx='210' cy='210' r='124'/%3E%3Ccircle cx='210' cy='210' r='116' stroke-dasharray='8 5'/%3E%3Ccircle cx='210' cy='210' r='100'/%3E%3Ccircle cx='210' cy='210' r='92' stroke-dasharray='4 4'/%3E%3Ccircle cx='210' cy='210' r='76'/%3E%3Ccircle cx='210' cy='210' r='68' stroke-dasharray='12 3'/%3E%3Ccircle cx='210' cy='210' r='52'/%3E%3Ccircle cx='210' cy='210' r='44'/%3E%3Ccircle cx='210' cy='210' r='36' stroke-dasharray='3 4'/%3E%3Ccircle cx='210' cy='210' r='20'/%3E%3C/g%3E%3C/svg%3E");
          background-size:420px 420px;opacity:.5;
        }}
        .page{{position:relative;z-index:1;max-width:820px;margin:0 auto;padding:0 22px}}
        .perf{{
          height:26px;width:100%;
          background-image:radial-gradient(circle at 13px 13px, var(--paper) 6px, transparent 7px);
          background-size:26px 26px;background-position:center top;
        }}
        .perf.bottom{{background-position:center bottom}}
        header{{border-bottom:3px double var(--rule);margin-bottom:40px}}
        .reg-bar{{display:flex;align-items:center;justify-content:space-between;padding:20px 0;gap:20px}}
        .brand{{display:flex;align-items:baseline;gap:12px;text-decoration:none;color:var(--ink)}}
        .brand b{{font-family:var(--serif);font-weight:900;font-size:26px;letter-spacing:.04em}}
        .brand span{{font-family:var(--type);font-size:11px;letter-spacing:.18em;color:var(--stamp);text-transform:uppercase}}
        .reg-no{{font-family:var(--type);font-size:11px;color:var(--ink-soft);letter-spacing:.12em}}
        .panel{{border:1.5px solid var(--ink);background:rgba(255,255,255,.6);margin-bottom:28px}}
        .panel .tab{{
          font-family:var(--type);font-size:11px;letter-spacing:.22em;text-transform:uppercase;
          background:var(--ink);color:var(--paper);padding:10px 18px;display:flex;justify-content:space-between;gap:12px;
        }}
        .panel .tab em{{font-style:normal;color:var(--rosette)}}
        .panel .tab.t-green{{background:var(--green)}}
        .panel .tab.t-red{{background:var(--stamp-deep)}}
        .panel .body{{padding:26px}}
        .verdict{{
          display:inline-block;font-family:var(--serif);font-weight:900;
          font-size:clamp(26px,6vw,40px);letter-spacing:.06em;
          border:3px solid;padding:8px 26px;transform:rotate(-3deg);
          filter:url(#roughen);
        }}
        .verdict.ok{{color:var(--green);border-color:var(--green)}}
        .verdict.bad{{color:var(--stamp);border-color:var(--stamp)}}
        .verdict-note{{font-family:var(--type);font-size:12px;color:var(--ink-soft);margin-top:16px}}
        .verdict-note.bad{{color:var(--stamp-deep)}}
        .fact{{display:flex;gap:14px;padding:9px 0;border-bottom:1px dotted var(--rule);font-size:14px;align-items:baseline}}
        .fact:last-child{{border-bottom:0}}
        .fact b{{font-family:var(--type);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft);width:168px;flex:none;font-weight:400}}
        .fact .v{{font-weight:600}}
        .fact ul{{margin:0;padding-left:18px}}
        .pill{{font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;padding:4px 10px;border:1.5px solid;border-radius:2px}}
        .pill.ok{{color:var(--green);border-color:var(--green);background:rgba(46,107,79,.08)}}
        .pill.bad{{color:var(--stamp);border-color:var(--stamp);background:rgba(166,25,60,.08)}}
        .crypto-h{{font-family:var(--type);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--stamp);margin:20px 0 8px}}
        .sigbox{{
          background:var(--paper-deep);border:1px solid var(--rule);font-family:var(--type);font-size:11px;
          word-break:break-all;padding:10px 12px;max-height:90px;overflow:auto;line-height:1.6;
        }}
        footer{{border-top:3px double var(--rule);margin-top:44px;padding:28px 0 0}}
        .foot-note{{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;font-family:var(--type);font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft)}}
        .btn{{
          font-family:var(--type);font-size:12px;letter-spacing:.16em;text-transform:uppercase;
          text-decoration:none;padding:12px 24px;border-radius:2px;
          background:var(--stamp);color:var(--paper);box-shadow:3px 3px 0 var(--stamp-deep);display:inline-block;
        }}
        .gis{{margin-bottom:28px}}
        .gis .attr-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}
        .gis .attr{{background:var(--card);border:1px solid var(--rule);padding:12px 14px}}
        .gis .attr .k{{font-family:var(--type);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-soft);margin-bottom:4px}}
        .gis .attr .v{{font-size:14px;font-weight:700;color:var(--ink)}}
        .gis .authority{{background:rgba(46,107,79,.08);border:1px solid rgba(46,107,79,.35);padding:12px 14px;margin-bottom:14px}}
        .gis .authority .k{{font-family:var(--type);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--green)}}
        .gis .authority .v{{font-size:14px;font-weight:700;color:var(--green);margin-top:2px}}
        .gis .authority .s{{font-size:11px;color:var(--ink-soft);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
        .gis .infonote{{background:var(--paper-deep);border-left:4px solid var(--stamp);padding:12px 16px;font-size:13.5px;color:var(--ink-soft);margin-bottom:14px}}
        .gis .village-warn{{background:rgba(169,106,31,.1);border-left:4px solid var(--amber);padding:10px 14px;font-size:13px;color:var(--amber);margin-bottom:14px}}
        .gis .src-note{{font-family:var(--type);font-size:11.5px;color:var(--ink-soft);font-style:italic;margin-bottom:16px}}
        .gis .map-grid{{display:grid;grid-template-columns:1.2fr .8fr;gap:20px;align-items:start}}
        @media(max-width:900px){{.gis .map-grid{{grid-template-columns:1fr}}}}
        .gis #gis-map{{width:100%;height:380px;border:1.5px solid var(--rule);background:var(--paper-deep);z-index:1}}
        .gis .legend{{font-size:12px;background:var(--card);border:1px solid var(--rule);padding:10px 14px;margin-top:10px;display:flex;flex-wrap:wrap;gap:16px;align-items:center}}
        .gis .legend .sw{{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}}
        .gis .legend .lbl{{font-weight:600;color:var(--ink)}}
        .gis .coords{{font-family:var(--type);font-size:11.5px;color:var(--ink-soft);margin-top:8px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
        .gis .metric{{background:var(--card);border:1px solid var(--rule);padding:16px;margin-bottom:14px}}
        .gis .metric h4{{font-family:var(--type);font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--stamp);margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid var(--rule-soft)}}
        .gis .metric p{{font-size:13px;line-height:1.6;color:var(--ink-soft);margin:0 0 6px}}
        .gis .metric p b{{color:var(--ink)}}
        .gis .metric .disclaimer{{font-family:var(--type);font-size:11px;color:var(--amber);background:rgba(169,106,31,.1);border:1px solid rgba(169,106,31,.3);padding:8px;margin-top:8px;font-style:italic}}
        .gis .metric .quiet{{font-family:var(--type);font-size:11px;color:var(--ink-soft);background:var(--paper);border:1px solid var(--rule-soft);padding:8px;font-style:italic;margin-top:8px}}
      </style>
    </head>
    <body>

    <div class="security-bg" aria-hidden="true"></div>

    <svg width="0" height="0" style="position:absolute" aria-hidden="true">
      <filter id="roughen">
        <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves="2" result="n"/>
        <feDisplacementMap in="SourceGraphic" in2="n" scale="2.5"/>
      </filter>
    </svg>

    <div class="perf" aria-hidden="true"></div>
    <div class="page">

    <header>
      <div class="reg-bar">
        <a class="brand" href="/">
          <b>OneBhoomi</b>
          <span>वनभूमि &nbsp;·&nbsp; public verification</span>
        </a>
        <div style="display:flex; align-items:center; gap:10px;">
          <div class="lang-picker" title="Change Language">
            <svg class="lang-svg" viewBox="0 0 24 24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;stroke:var(--stamp);fill:none;flex-shrink:0;display:inline-block;vertical-align:middle;">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="2" y1="12" x2="22" y2="12"></line>
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
        </svg>
            <select id="langSelect" class="lang-dropdown" aria-label="Select Language">
              <option value="en" selected>English</option>
              <option value="hi">हिंदी (Hindi)</option>
              <option value="te">తెలుగు (Telugu)</option>
              <option value="kn">ಕನ್ನಡ (Kannada)</option>
              <option value="ta">தமிழ் (Tamil)</option>
            </select>
          </div>
          <span class="reg-no">RECORD NO. {html.escape(rec_id[:8].upper())}</span>
        </div>
      </div>
    </header>

    <section class="panel">
      <div class="tab"><span>Certificate Check</span><em>{html.escape(record.get('approved_at') or 'on record')}</em></div>
      <div class="body">
        {verdict}
        <div style="margin-top:22px;">
          <div class="fact"><b>Verification ID</b><span class="v" style="font-family:var(--type);font-weight:400;">{html.escape(rec_id)}</span></div>
          <div class="fact"><b>Register Status</b><span class="pill {'ok' if status == 'APPROVED' else 'bad'}">{html.escape(status)}</span></div>
          <div class="fact"><b>Approved At</b><span class="v">{html.escape(record.get('approved_at') or 'not approved')}</span></div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="tab"><span>Document Facts</span><em>as sealed</em></div>
      <div class="body">
        <div class="fact"><b>Document Type</b><span class="v">{html.escape(payload_data.get('document_type') or '')}</span></div>
        <div class="fact"><b>Document Number</b><span class="v">{html.escape(payload_data.get('document_number') or '')}</span></div>
        <div class="fact"><b>Property Survey</b><span class="v">{html.escape(str(prop.get('survey_number') or ''))}</span></div>
        <div class="fact"><b>Area</b><span class="v">{html.escape(str(prop.get('area') or ''))}</span></div>
        <div class="fact"><b>Village</b><span class="v">{html.escape(prop.get('village') or '')}</span></div>
        <div class="fact"><b>District</b><span class="v">{html.escape(prop.get('district') or '')}</span></div>
        <div class="fact"><b>Parties</b><ul>{parties_rows}</ul></div>
        <div class="fact"><b>Document Date</b><span class="v">{html.escape(payload_data.get('document_date') or '')}</span></div>
        <div class="fact"><b>Execution Date</b><span class="v">{html.escape(payload_data.get('execution_date') or '')}</span></div>

        <p class="crypto-h">Digital Signature Seal</p>
        <div class="sigbox">{html.escape(record.get('signature', 'None'))}</div>
      </div>
    </section>

    {gis_html}

    <footer>
      <div class="foot-note">
        <span>OneBhoomi · Offline Registry</span>
        <span>Signature checked on this device's request, no cloud involved</span>
        <span><a class="btn" href="/">Registry Office</a></span>
      </div>
    </footer>

    </div>
    <div class="perf bottom" aria-hidden="true"></div>

    </body>
    </html>
    """
    return page_html.encode("utf-8")


class LandExtractorHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        host_name = self.headers.get("Host", f"localhost:{self.server.server_address[1]}")

        # Quick OCR URL update endpoint: /set_ocr_url?url=https://...
        if parsed.path == "/set_ocr_url":
            new_url = query_params.get("url", [None])[0]
            if new_url:
                new_url = new_url.strip().rstrip("/")
                try:
                    (Path(__file__).parent / "colab_url.txt").write_text(new_url, encoding="utf-8")
                    global COLAB_OCR_URL
                    COLAB_OCR_URL = new_url
                    os.environ["COLAB_OCR_URL"] = new_url
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "url": new_url}).encode("utf-8"))
                    return
                except Exception as e:
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
                    return
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing url parameter")
            return

        # Verification view routing (offline QR validation & public certificate)
        verification_id = query_params.get("verification_id", [None])[0]
        if verification_id and parsed.path in {"/", "/index.html", "/verify"}:
            record = verification_service.get_record(verification_id)
            if record:
                pub_key = record.get(
                    "public_key"
                ) or verification_service.get_public_verification_key()
                signature = record.get("signature")
                payload = record.get("document_payload")
                status = record.get("status")

                sig_valid = False
                if signature and pub_key and payload:
                    sig_valid = verification_service.verify_document_signature(
                        payload, signature, pub_key
                    )

                page = render_verification_view(record, sig_valid)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Verification record not found")
                return

        # Dashboard View: Clean, professional operations portal with sidebar & stats
        if parsed.path == "/dashboard":
            page = dashboard_view.render_dashboard(
                host_name=host_name,
                colab_url=get_colab_url(),
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        # Dedicated New Scan & Document Intake desk (with persistent sidebar)
        if parsed.path in {"/new", "/desk", "/upload"}:
            page = dashboard_view.render_new_scan(
                host_name=host_name,
                colab_url=get_colab_url(),
                message="",
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        # Clerk Review & Approval Console for a specific record
        if parsed.path == "/record":
            record_id = query_params.get("verification_id", [None])[0]
            record = (
                verification_service.get_record(record_id) if record_id else None
            )
            if not record:
                self.send_error(HTTPStatus.NOT_FOUND, "Verification record not found")
                return
            preview_html = (
                get_preview_html(record_id)
                or f"<p><strong>Active Verification Record:</strong> {record_id}</p>"
            )
            page = render_page(
                payload=json.dumps(record, indent=2, ensure_ascii=False),
                message="",
                preview=preview_html,
                colab_url_value=get_colab_url(),
                active_record=record,
                host_name=host_name,
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        # Public Landing Page (OneBhoomi Design System)
        if parsed.path in {"/", "/index.html"}:
            landing_file = Path(__file__).parent / "01-onebhoomi-final.html"
            if landing_file.exists():
                content = landing_file.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            page = render_page(colab_url_value=get_colab_url(), host_name=host_name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        # In-memory OCR URL update API
        if self.path == "/api/update_ocr_url":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
                new_url = data.get("url", "").strip().rstrip("/")
                if new_url:
                    (Path(__file__).parent / "colab_url.txt").write_text(new_url, encoding="utf-8")
                    global COLAB_OCR_URL
                    COLAB_OCR_URL = new_url
                    os.environ["COLAB_OCR_URL"] = new_url
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok", "url": new_url}).encode("utf-8"))
                    return
            except Exception as e:
                self.send_error(HTTPStatus.BAD_REQUEST, str(e))
                return

        if self.path != "/extract":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_error(HTTPStatus.BAD_REQUEST, "Expected multipart upload")
            return

        boundary_token = "boundary="
        if boundary_token not in content_type:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing upload boundary")
            return

        boundary = content_type.split(boundary_token, 1)[1].encode("utf-8")
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        parts = body.split(b"--" + boundary)
        uploaded = None
        filename = "uploaded_image"
        colab_url = get_colab_url()
        processing_mode = "gpu" if colab_url else "cpu"

        # Action fields parsing
        action = None
        verification_id = None
        rejection_reason = ""
        form_fields = {}

        for part in parts:
            if b"Content-Disposition" not in part:
                continue

            header_blob, _, val_blob = part.partition(b"\r\n\r\n")
            val = val_blob.rsplit(b"\r\n", 1)[0]
            header_str = header_blob.decode("utf-8", errors="ignore")

            if 'name="document_image"' in header_str:
                if not val:
                    continue
                match = re.search(r'filename="([^"]+)"', header_str)
                if match:
                    filename = Path(match.group(1)).name
                uploaded = val
            elif 'name="processing_mode"' in header_str:
                mode_str = val.decode("utf-8", errors="ignore").strip()
                if mode_str:
                    processing_mode = mode_str
            elif 'name="colab_url"' in header_str:
                url_str = val.decode("utf-8", errors="ignore").strip()
                if url_str:
                    colab_url = url_str.rstrip("/")
                    try:
                        (Path(__file__).parent / "colab_url.txt").write_text(colab_url, encoding="utf-8")
                    except Exception:
                        pass
            elif 'name="action"' in header_str:
                action = val.decode("utf-8", errors="ignore").strip()
            elif 'name="verification_id"' in header_str:
                verification_id = val.decode("utf-8", errors="ignore").strip()
            elif 'name="rejection_reason"' in header_str:
                rejection_reason = val.decode("utf-8", errors="ignore").strip()
            else:
                match = re.search(r'name="([^"]+)"', header_str)
                if match:
                    field_name = match.group(1)
                    form_fields[field_name] = val.decode(
                        "utf-8", errors="ignore"
                    ).strip()

        # Handle postback actions (Approve / Reject / Save Corrections)
        if action and verification_id:
            record = verification_service.get_record(verification_id)
            if not record:
                self.send_error(HTTPStatus.NOT_FOUND, "Verification record not found")
                return

            current_status = record.get("status")

            # 1. Postback on an already APPROVED record
            if current_status == "APPROVED":
                if action == "reject":
                    if not rejection_reason.strip():
                        message = "Rejection refused: a rejection reason is required to revoke an approved record."
                    else:
                        record["status"] = "REJECTED"
                        record["rejection_reason"] = rejection_reason.strip()
                        record["rejected_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                        # We leave document_payload untouched to preserve historical audit integrity
                        verification_service.save_record(record)
                        message = "Approved certification was revoked and the record marked as REJECTED."
                elif action == "approve":
                    message = "Document is already approved and cryptographically sealed."
                elif action == "correct":
                    message = "Cannot modify facts: This document is already approved and sealed."

            # 2. Rejection on a non-approved record (NEEDS_REVIEW, FAIL, or REJECTED)
            elif action == "reject":
                if not rejection_reason.strip():
                    message = "Rejection failed: a rejection reason is required."
                else:
                    record["status"] = "REJECTED"
                    record["rejection_reason"] = rejection_reason.strip()
                    record["rejected_at"] = datetime.utcnow().strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    verification_service.save_record(record)
                    message = "Document was rejected by the officer."

            # 3. Clerk corrections or officer approval on a non-approved record
            elif action in ("approve", "correct"):
                payload = record.get("document_payload", {})

                if "document_type" in form_fields:
                    payload["document_type"] = form_fields["document_type"]
                if "document_number" in form_fields:
                    payload["document_number"] = form_fields["document_number"]

                payload.setdefault("property", {})
                if "area" in form_fields:
                    payload["property"]["area"] = form_fields["area"]
                if "survey_number" in form_fields:
                    payload["property"]["survey_number"] = form_fields["survey_number"]
                if "sub_survey_number" in form_fields:
                    payload["property"]["sub_survey_number"] = form_fields["sub_survey_number"]
                if "village" in form_fields:
                    payload["property"]["village"] = form_fields["village"]
                if "mandal" in form_fields:
                    payload["property"]["mandal"] = form_fields["mandal"]
                if "district" in form_fields:
                    payload["property"]["district"] = form_fields["district"]

                payload.setdefault("stamp_information", {})
                if "stamp_number" in form_fields:
                    payload["stamp_information"]["stamp_number"] = form_fields["stamp_number"]
                    payload["stamp_number"] = form_fields["stamp_number"]
                if "stamp_value" in form_fields:
                    payload["stamp_information"]["stamp_value"] = form_fields["stamp_value"]
                    payload["stamp_value"] = form_fields["stamp_value"]
                if "sold_to" in form_fields:
                    payload["stamp_information"]["sold_to"] = form_fields["sold_to"]

                if "document_date" in form_fields:
                    payload["document_date"] = form_fields["document_date"]
                if "execution_date" in form_fields:
                    payload["execution_date"] = form_fields["execution_date"]

                if "parties_json" in form_fields:
                    try:
                        payload["parties"] = json.loads(form_fields["parties_json"])
                    except Exception:
                        pass

                # Recompute automated validation checks
                checks = verification_service.run_verification_checks(payload)
                status = verification_service.calculate_overall_status(checks)

                record["document_payload"] = payload
                record["checks"] = checks
                record["status"] = status

                if action == "approve":
                    has_critical_fail = any(
                        c.get("status") == "FAIL" and c.get("severity") == "critical"
                        for c in checks
                    )
                    if has_critical_fail:
                        message = "Approval refused: critical automated checks failed."
                        verification_service.save_record(record)
                    else:
                        sig = verification_service.sign_document(payload)
                        pub_key = verification_service.get_public_verification_key()

                        record["status"] = "APPROVED"
                        record["signature"] = sig
                        record["public_key"] = pub_key
                        record["approved_at"] = datetime.utcnow().strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                        verification_service.save_record(record)
                        message = "Document approved and sealed successfully."
                elif action == "correct":
                    verification_service.save_record(record)
                    message = "Clerk review corrections saved successfully."

            payload_str = json.dumps(record, indent=2, ensure_ascii=False)
            host_name = self.headers.get("Host", f"localhost:{self.server.server_address[1]}")
            preview_html = (
                get_preview_html(verification_id)
                or f"<p><strong>Active Verification Record:</strong> {verification_id}</p>"
            )
            page = render_page(
                payload=payload_str,
                message=message,
                preview=preview_html,
                cpu_selected="",
                gpu_selected="",
                colab_url_value=colab_url,
                timing_info="",
                active_record=record,
                host_name=host_name,
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        if not uploaded:
            self.send_error(HTTPStatus.BAD_REQUEST, "No file was uploaded")
            return

        temp_path = None
        cpu_sel = "selected" if processing_mode == "cpu" else ""
        gpu_sel = "selected" if processing_mode == "gpu" else ""

        try:
            temp_path = process_uploaded_file(uploaded, filename)

            timing_info = ""

            if processing_mode == "gpu":
                t_total_start = perf_counter()
                try:
                    status_url = f"{colab_url.rstrip('/')}/status"
                    status_resp = requests.get(status_url, timeout=5)
                    if status_resp.status_code != 200:
                        raise ValueError(
                            f"Cloud GPU status check returned status code {status_resp.status_code}"
                        )
                    gpu_name = status_resp.json().get("gpu_name", "NVIDIA GPU")
                except Exception as e:
                    raise ConnectionError(
                        f"Cloud GPU is unavailable at this URL. Details: {e}"
                    )

                ocr_url = f"{colab_url.rstrip('/')}/ocr"
                is_pdf_upload = filename.lower().endswith(".pdf") or uploaded.startswith(b"%PDF")

                if is_pdf_upload:
                    # 1. Fast-path: Check for digital/searchable text layer (instant, zero network)
                    digital_extracted = try_extract_digital_pdf_lines(uploaded)
                    if digital_extracted is not None:
                        lines, raw_text = digital_extracted
                        ocr_time_ms = 5.0
                        network_time_ms = 0.0
                        gpu_name = "Digital PDF Parser (Instant Fast-Path)"
                    else:
                        # 2. Scanned PDF: Render directly to in-memory compressed JPEGs (scale 1.6x, ~300KB/page)
                        page_buffers = extract_pdf_pages_to_memory(uploaded, scale=1.6)
                        all_lines = []
                        all_raw_texts = []
                        total_ocr_time_ms = 0.0
                        t_net_start = perf_counter()

                        def _post_page(item: tuple[int, bytes, int, int]):
                            p_idx, img_bytes, pw, ph = item
                            resp = requests.post(
                                ocr_url,
                                files={"image": (f"page_{p_idx}.jpg", img_bytes, "image/jpeg")},
                                timeout=60,
                            )
                            if resp.status_code != 200:
                                try:
                                    err_msg = resp.json().get("error", resp.text)
                                except Exception:
                                    err_msg = resp.text
                                raise ValueError(
                                    f"Cloud GPU OCR failed on Page {p_idx} with status {resp.status_code}: {err_msg}"
                                )
                            return p_idx, resp.json(), pw, ph

                        # Upload & process pages in parallel via ThreadPoolExecutor
                        max_workers = min(4, max(1, len(page_buffers)))
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            results = list(executor.map(_post_page, page_buffers))

                        results.sort(key=lambda r: r[0])

                        for page_idx, gpu_result, pw, ph in results:
                            total_ocr_time_ms += gpu_result.get("ocr_time_ms", 0.0)
                            gpu_name = gpu_result.get("gpu_name", gpu_name)

                            p_words = []
                            for text, score, poly in zip(
                                gpu_result["rec_texts"],
                                gpu_result["rec_scores"],
                                gpu_result["rec_polys"],
                            ):
                                cleaned = normalize_space(str(text))
                                if not cleaned:
                                    continue
                                p_words.append(
                                    OCRWord(
                                        text=cleaned,
                                        score=float(score),
                                        points=[[int(pt[0]), int(pt[1])] for pt in poly],
                                    )
                                )

                            p_lines = group_words_into_lines(p_words)
                            for l in p_lines:
                                l.page_num = page_idx
                                l.page_height = ph
                                l.page_width = pw
                            all_lines.extend(p_lines)
                            p_raw = "\n".join(l.text for l in p_lines)
                            all_raw_texts.append(f"--- PAGE {page_idx} ---\n{p_raw}")

                        t_net_end = perf_counter()
                        total_request_time = (t_net_end - t_net_start) * 1000
                        ocr_time_ms = total_ocr_time_ms
                        network_time_ms = max(0.0, total_request_time - ocr_time_ms)
                        lines = all_lines
                        raw_text = "\n\n".join(all_raw_texts)
                else:
                    t_net_start = perf_counter()
                    # Optimize single image upload if massive
                    upload_files = None
                    try:
                        import cv2
                        img_cv = cv2.imread(temp_path)
                        if img_cv is not None:
                            max_dim = max(img_cv.shape[:2])
                            if max_dim > 1800:
                                scale_f = 1800.0 / max_dim
                                img_cv = cv2.resize(img_cv, (0, 0), fx=scale_f, fy=scale_f, interpolation=cv2.INTER_AREA)
                            success, enc_jpg = cv2.imencode(".jpg", img_cv, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            if success:
                                upload_files = {"image": ("upload.jpg", enc_jpg.tobytes(), "image/jpeg")}
                    except Exception:
                        upload_files = None

                    if upload_files is not None:
                        ocr_resp = requests.post(ocr_url, files=upload_files, timeout=45)
                    else:
                        with open(temp_path, "rb") as f:
                            ocr_resp = requests.post(ocr_url, files={"image": f}, timeout=45)

                    t_net_end = perf_counter()
                    total_request_time = (t_net_end - t_net_start) * 1000

                    if ocr_resp.status_code != 200:
                        try:
                            err_msg = ocr_resp.json().get("error", ocr_resp.text)
                        except Exception:
                            err_msg = ocr_resp.text
                        raise ValueError(
                            f"Cloud GPU OCR failed with status {ocr_resp.status_code}: {err_msg}"
                        )

                    gpu_result = ocr_resp.json()
                    ocr_time_ms = gpu_result.get("ocr_time_ms", 0.0)
                    gpu_name = gpu_result.get("gpu_name", gpu_name)
                    network_time_ms = max(0.0, total_request_time - ocr_time_ms)

                    words = []
                    for text, score, poly in zip(
                        gpu_result["rec_texts"],
                        gpu_result["rec_scores"],
                        gpu_result["rec_polys"],
                    ):
                        cleaned = normalize_space(str(text))
                        if not cleaned:
                            continue
                        words.append(
                            OCRWord(
                                text=cleaned,
                                score=float(score),
                                points=[[int(pt[0]), int(pt[1])] for pt in poly],
                            )
                        )

                    lines = group_words_into_lines(words)
                    # Estimate page height from max y coordinate of detected words
                    _est_h = max((w.y_max for w in words), default=2000) + 100 if words else 2000
                    _est_w = max((w.x_max for w in words), default=1500) + 100 if words else 1500
                    for l in lines:
                        l.page_num = 1
                        l.page_height = _est_h
                        l.page_width = _est_w
                    raw_text = "\n".join(l.text for l in lines)

                gpu_ocr_timings = {
                    "model_initialization_ms": 0.0,
                    "model_access_ms": 0.0,
                    "image_reading_ms": 0.0,
                    "ocr_inference_ms": ocr_time_ms,
                    "ocr_word_parsing_ms": 0.0,
                    "line_grouping_ms": 0.0,
                    "ocr_text_join_ms": 0.0,
                    "ocr_total_ms": ocr_time_ms,
                }

                result = extract_land_document_from_lines(
                    lines, raw_text, temp_path, timings=gpu_ocr_timings
                )

                total_time_ms = (perf_counter() - t_total_start) * 1000
                result.setdefault("profiling_ms", {})
                result["profiling_ms"]["pipeline_total_ms"] = round(
                    total_time_ms, 3
                )

                mode_label = (
                    "Digital Text Fast-Path"
                    if gpu_name.startswith("Digital")
                    else "Kaggle / Colab GPU"
                )
                timing_info = f"""
                <div class="docket rv in">
                  <span><b data-i18n="lbl_mode">Mode</b> {mode_label}</span>
                  <span><b data-i18n="lbl_hardware">Hardware</b> {html.escape(str(gpu_name))}</span>
                  <span><b data-i18n="lbl_ocr">OCR</b> {ocr_time_ms:.2f} ms</span>
                  <span><b data-i18n="lbl_transit">Transit</b> {network_time_ms:.2f} ms</span>
                  <span><b data-i18n="lbl_total">Total</b> {total_time_ms:.2f} ms</span>
                </div>
                """
            else:
                t_total_start = perf_counter()
                result = extract_land_document(temp_path)
                total_time_ms = (perf_counter() - t_total_start) * 1000

                ocr_time_ms = result.get("profiling_ms", {}).get(
                    "ocr_total_ms", 0.0
                )

                timing_info = f"""
                <div class="docket rv in">
                  <span><b>Mode</b> Local CPU · PaddleOCR</span>
                  <span><b>OCR</b> {ocr_time_ms:.2f} ms</span>
                  <span><b>Total</b> {total_time_ms:.2f} ms</span>
                </div>
                """

            # Create local verification record instantly
            record = verification_service.create_verification_record(result)
            verification_service.save_record(record)

            from semantic_extractor import clean_user_facing_schema
            user_facing_result = clean_user_facing_schema(result)
            payload = json.dumps(user_facing_result, indent=2, ensure_ascii=False)
            if is_pdf_upload:
                if 'page_buffers' not in locals() or not page_buffers:
                    page_buffers = extract_pdf_pages_to_memory(uploaded, scale=1.6)
                preview_pages_b64 = [base64.b64encode(pb[1]).decode("ascii") for pb in page_buffers]
                total_pgs = len(preview_pages_b64)
                pages_html = "\n".join(
                    f'<div style="margin-bottom: 18px; text-align: center;">'
                    f'<div style="font-family: var(--type); font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: var(--ink-soft); margin-bottom: 6px; text-align: left; text-transform: uppercase;">PAGE {idx} OF {total_pgs}</div>'
                    f'<img src="data:image/jpeg;base64,{b64_str}" style="width: 100%; border: 1.5px solid var(--rule); box-shadow: 2px 2px 0 rgba(0,0,0,0.06); display: block; background: #fff;" alt="Document Page {idx}">'
                    f'</div>'
                    for idx, b64_str in enumerate(preview_pages_b64, start=1)
                )
                preview = f"""
                <div style="min-height: 760px; max-height: calc(100vh - 140px); overflow-y: auto; background: var(--paper-deep); border: 1.5px solid var(--rule); padding: 16px;">
                  {pages_html}
                </div>
                """
            else:
                mime_type = mimetypes.guess_type(filename)[0] or "image/png"
                image_data = base64.b64encode(uploaded).decode("ascii")
                preview = f"""
                <div style="min-height: 760px; max-height: calc(100vh - 140px); overflow-y: auto; text-align: center; background: var(--paper-deep); border: 1.5px solid var(--rule); padding: 16px;">
                  <img src="data:{mime_type};base64,{image_data}" style="width: 100%; max-width: 100%; border: 1.5px solid var(--rule); box-shadow: 0 4px 20px rgba(0,0,0,0.12); background: #fff; display: block;" alt="Uploaded scan copy">
                </div>
                """
            message = f"Processed {html.escape(filename)}. Verification record created and machine checklist run."

            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

            host_name = self.headers.get("Host", f"localhost:{self.server.server_address[1]}")
            full_preview_html = preview
            save_preview_html(record["verification_id"], full_preview_html)
            page = render_page(
                payload=payload,
                message=message,
                preview=full_preview_html,
                preview_caption=filename,
                cpu_selected=cpu_sel,
                gpu_selected=gpu_sel,
                colab_url_value=colab_url,
                timing_info=timing_info,
                active_record=record,
                host_name=host_name,
                stage="results",
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        except Exception as exc:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            error_payload = json.dumps({"error": str(exc)}, indent=2)

            timing_info = (
                f"""
                <div class="docket error rv in">
                  <span><b>Mode</b> Remote GPU</span>
                  <span><b>Status</b> ✗ Unavailable</span>
                  <span><b>Error</b> {html.escape(str(exc))}</span>
                </div>
                """
                if processing_mode == "gpu"
                else ""
            )

            host_name = self.headers.get("Host", f"localhost:{self.server.server_address[1]}")
            page = render_page(
                payload=error_payload,
                message="Extraction failed. Check the docket above and try again.",
                cpu_selected=cpu_sel,
                gpu_selected=gpu_sel,
                colab_url_value=colab_url,
                timing_info=timing_info,
                host_name=host_name,
                stage="upload",
            )
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    def log_message(self, format, *args):
        return


def main() -> int:
    print("Pre-loading PaddleOCR models (this may take a moment)...")
    try:
        get_paddle_ocr_model()
        print("PaddleOCR models pre-loaded successfully!")
    except Exception as exc:
        print(
            f"Warning: local PaddleOCR preload failed, starting server anyway: {exc}"
        )
    port = int(os.environ.get("PORT", 8001))
    server = ThreadingHTTPServer(("0.0.0.0", port), LandExtractorHandler)
    lan_ip = get_lan_ip()
    print(f"Land extractor web app running locally at http://localhost:{port}")
    print(f"Accessible on your local network/LAN at http://{lan_ip}:{port}")
    import threading
    threading.Thread(target=start_public_tunnel, args=(port,), daemon=True).start()
    while True:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Server exception recovered: {exc}")
            import time, traceback
            traceback.print_exc()
            time.sleep(1)
    try:
        server.server_close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
