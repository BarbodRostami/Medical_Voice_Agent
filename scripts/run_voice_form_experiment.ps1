# Launch experimental voice→form UI (correct Windows venv path).
# Usage:  .\scripts\run_voice_form_experiment.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# This repo uses "venv" (no leading dot). Do NOT use .\.venv\...
$Py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Error "Not found: $Py`nCreate/use folder 'venv' under the project root."
}

Write-Host "Python: $Py"
Write-Host "Open http://localhost:8502 after startup"
& $Py -m streamlit run "backend\experiments\voice_form_ui.py" --server.port 8502 --server.headless true --browser.gatherUsageStats false
