# Score voice-form samples against gold labels. Does not start the API.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& "$root\venv\Scripts\python.exe" -m backend.experiments.eval_voice_form @args
exit $LASTEXITCODE
