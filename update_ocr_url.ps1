$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    & $VenvPython (Join-Path $ScriptDir "update_ocr_url.py") @args
} else {
    & python (Join-Path $ScriptDir "update_ocr_url.py") @args
}
