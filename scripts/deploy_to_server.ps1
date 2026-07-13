# Copy .env and run server setup on company VM.
# You will be prompted for SSH password (vpn@192.168.1.15).
param(
    [string]$Server = "vpn@192.168.1.15",
    [string]$RemoteDir = "/home/vpn/Medical_Voice_Agent",
    [string]$LocalEnv = "d:\Python_envs\rag_project\.env"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent

if (-not (Test-Path $LocalEnv)) {
    Write-Error ".env not found at $LocalEnv"
}

# Ensure PUBLIC_API_URL for correct audio_url on server
$envContent = Get-Content $LocalEnv -Raw
if ($envContent -notmatch "PUBLIC_API_URL=") {
    Add-Content -Path $LocalEnv -Value "`nPUBLIC_API_URL=http://192.168.1.15:8000"
    Write-Host "Added PUBLIC_API_URL to local .env"
}

Write-Host "Copying .env to server..."
scp $LocalEnv "${Server}:${RemoteDir}/.env"

Write-Host "Copying server_setup.sh..."
scp "$ProjectRoot\scripts\server_setup.sh" "${Server}:${RemoteDir}/scripts/server_setup.sh"

Write-Host "Running remote setup (git pull + docker + S3 test)..."
ssh $Server "chmod +x ${RemoteDir}/scripts/server_setup.sh && bash ${RemoteDir}/scripts/server_setup.sh ${RemoteDir}"

Write-Host "Deploy finished."
