#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
if [ -f "$DIR/.venv/Scripts/python.exe" ]; then
    "$DIR/.venv/Scripts/python.exe" "$DIR/update_ocr_url.py" "$@"
elif [ -f "$DIR/.venv/bin/python3" ]; then
    "$DIR/.venv/bin/python3" "$DIR/update_ocr_url.py" "$@"
elif command -v python &>/dev/null; then
    python "$DIR/update_ocr_url.py" "$@"
else
    python3 "$DIR/update_ocr_url.py" "$@"
fi
