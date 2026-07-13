# Copy .env and run server setup on company VM.
# You will be prompted for SSH password (vpn@192.168.1.15) unless SSH keys are configured.
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

$envContent = Get-Content $LocalEnv -Raw
if ($envContent -notmatch "PUBLIC_API_URL=") {
    Add-Content -Path $LocalEnv -Value "`nPUBLIC_API_URL=http://192.168.1.15:8000"
    Write-Host "Added PUBLIC_API_URL to local .env"
    $envContent = Get-Content $LocalEnv -Raw
}

$required = @("LIARA_ENDPOINT", "LIARA_BUCKET", "LIARA_ACCESS_KEY", "LIARA_SECRET_KEY")
foreach ($key in $required) {
    $pattern = "(?m)^" + [regex]::Escape($key) + "="
    if ($envContent -notmatch $pattern) {
        Write-Error "Missing $key in $LocalEnv - add Parmin credentials before deploy."
    }
}
if ($envContent -match "LIARA_ACCESS_KEY=ghp_") {
    Write-Error "LIARA_ACCESS_KEY looks like a GitHub token - use Parmin Cloud keys."
}

Write-Host "Testing SSH..."
$sshOk = $false
try {
    ssh -o BatchMode=yes -o ConnectTimeout=8 $Server "echo ssh_ok" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $sshOk = $true }
} catch {
    $sshOk = $false
}
if (-not $sshOk) {
    Write-Host ""
    Write-Host "SSH key auth not available. Run these commands manually (enter password when prompted):"
    Write-Host ""
    Write-Host ('  scp "' + $LocalEnv + '" ' + $Server + ':' + $RemoteDir + '/.env')
    Write-Host ('  scp "' + $ProjectRoot + '\scripts\server_setup.sh" ' + $Server + ':' + $RemoteDir + '/scripts/server_setup.sh')
    $remoteCmd = 'chmod +x ' + $RemoteDir + '/scripts/server_setup.sh; bash ' + $RemoteDir + '/scripts/server_setup.sh ' + $RemoteDir
    Write-Host ('  ssh ' + $Server + ' "' + $remoteCmd + '"')
    Write-Host ""
    exit 1
}

Write-Host "Copying .env to server..."
scp $LocalEnv ($Server + ":" + $RemoteDir + "/.env")

Write-Host "Copying server_setup.sh..."
scp ($ProjectRoot + "\scripts\server_setup.sh") ($Server + ":" + $RemoteDir + "/scripts/server_setup.sh")

Write-Host "Running remote setup..."
$remoteCmd = "chmod +x " + $RemoteDir + "/scripts/server_setup.sh; bash " + $RemoteDir + "/scripts/server_setup.sh " + $RemoteDir
ssh $Server $remoteCmd

Write-Host "Deploy finished."
