# Deploy current branch code + .env helpers to company VM, then run server_setup.sh.
# You may be prompted for SSH password (vpn@192.168.1.15) unless SSH keys are configured.
param(
    [string]$Server = "vpn@192.168.1.15",
    [string]$RemoteDir = "/home/vpn/Medical_Voice_Agent",
    [string]$LocalEnv = "d:\Python_envs\rag_project\.env",
    [string]$Branch = "feature/external-cases-api",
    [switch]$SkipEnvCopy
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent

Write-Host "Deploy target: $Server:$RemoteDir (branch=$Branch)"

Write-Host "Testing SSH..."
$sshOk = $false
try {
    ssh -o BatchMode=yes -o ConnectTimeout=8 $Server "echo ssh_ok" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $sshOk = $true }
} catch {
    $sshOk = $false
}

$setupLocal = Join-Path $ProjectRoot "scripts\server_setup.sh"

if (-not $sshOk) {
    Write-Host ""
    Write-Host "SSH key auth not available. Run these manually (enter password when prompted):"
    Write-Host ""
    Write-Host ('  scp "' + $setupLocal + '" ' + $Server + ':' + $RemoteDir + '/scripts/server_setup.sh')
    if (-not $SkipEnvCopy) {
        Write-Host ('  # Optional: copy .env then FIX PUBLIC_API_URL to http://192.168.1.15:8000 on server')
        Write-Host ('  scp "' + $LocalEnv + '" ' + $Server + ':' + $RemoteDir + '/.env')
    }
    $remoteCmd = 'sed -i ''s/\r$//'' ' + $RemoteDir + '/scripts/server_setup.sh; chmod +x ' + $RemoteDir + '/scripts/server_setup.sh; DEPLOY_BRANCH=' + $Branch + ' bash ' + $RemoteDir + '/scripts/server_setup.sh ' + $RemoteDir
    Write-Host ('  ssh ' + $Server + ' "' + $remoteCmd + '"')
    Write-Host ""
    exit 1
}

Write-Host "Copying server_setup.sh..."
scp $setupLocal ($Server + ":" + $RemoteDir + "/scripts/server_setup.sh")

if (-not $SkipEnvCopy) {
    if (-not (Test-Path $LocalEnv)) {
        Write-Error ".env not found at $LocalEnv"
    }
    Write-Host "Copying .env (server_setup will force PUBLIC_API_URL=192.168.1.15)..."
    scp $LocalEnv ($Server + ":" + $RemoteDir + "/.env")
}

Write-Host "Running remote setup..."
$remoteCmd = "sed -i 's/\r$//' $RemoteDir/scripts/server_setup.sh; chmod +x $RemoteDir/scripts/server_setup.sh; DEPLOY_BRANCH=$Branch bash $RemoteDir/scripts/server_setup.sh $RemoteDir"
ssh $Server $remoteCmd

Write-Host "Deploy finished."
Write-Host "Health: http://192.168.1.15:8000/"
