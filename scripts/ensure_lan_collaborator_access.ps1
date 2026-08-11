# Ensure collaborator can reach this laptop's API on :8000 while system proxy/TUN stays ON.
# - Detects Wi-Fi/Ethernet LAN IPv4 (skips WSL/VMware/xray_tun)
# - Opens Windows Firewall TCP 8000 on ALL profiles (Public home Wi-Fi often blocks otherwise)
# - Adds LAN IP + 192.168.* to WinInet ProxyOverride (so local tools bypass proxy)
# - Prints the URL/API key hint for HakimAI
#
# Usage (from repo root, PowerShell):
#   .\scripts\ensure_lan_collaborator_access.ps1
#   .\scripts\ensure_lan_collaborator_access.ps1 -RestartApi

param(
    [switch]$RestartApi,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Get-LanIPv4 {
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.PrefixOrigin -ne "WellKnown" -and
            $_.InterfaceAlias -notmatch "WSL|Hyper-V|vEthernet|VMware|xray|Loopback|Virtual|Docker|Bluetooth"
        } |
        Sort-Object {
            # Prefer 192.168.*, then 10.*, then others
            if ($_.IPAddress -like "192.168.*") { 0 }
            elseif ($_.IPAddress -like "10.*") { 1 }
            else { 2 }
        }, InterfaceAlias

    $wifi = $candidates | Where-Object { $_.InterfaceAlias -match "Wi-?Fi|Ethernet|WLAN" } | Select-Object -First 1
    if ($wifi) { return $wifi.IPAddress }
    if ($candidates) { return $candidates[0].IPAddress }
    return $null
}

$lanIp = Get-LanIPv4
if (-not $lanIp) {
    Write-Error "Could not detect LAN IPv4. Connect Wi-Fi/Ethernet and retry."
}

Write-Host "LAN IP: $lanIp"
$publicUrl = "http://${lanIp}:${Port}"

# --- Firewall (Public profile is required: Windows often marks home Wi-Fi as Public) ---
$ruleName = "Medical Voice API $Port"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort $Port `
        -Action Allow `
        -Profile Any `
        -Description "Allow HakimAI/collaborator LAN access to voice API" | Out-Null
    Write-Host "Created firewall rule: $ruleName (Profile=Any)"
} else {
    Set-NetFirewallRule -DisplayName $ruleName -Enabled True -Profile Any -Action Allow
    Write-Host "Updated firewall rule: $ruleName (Profile=Any)"
}

# Prefer Private for this Wi-Fi (helps LAN; may need elevation)
try {
    $wifi = Get-NetConnectionProfile -InterfaceAlias "Wi-Fi" -ErrorAction SilentlyContinue
    if ($wifi -and $wifi.NetworkCategory -ne "Private") {
        Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
        Write-Host "Wi-Fi NetworkCategory -> Private"
    }
} catch {
    Write-Host "Note: could not set Wi-Fi to Private (run as Admin if needed): $($_.Exception.Message)"
}

# --- WinInet proxy bypass (keeps proxy ON for internet; LAN goes DIRECT) ---
$inetPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$cur = (Get-ItemProperty $inetPath -ErrorAction SilentlyContinue).ProxyOverride
$parts = @()
if ($cur) {
    $parts = @($cur -split ";" | Where-Object {
        $_ -and $_ -notmatch "^192\.168\.1\.235$"
    })
}
foreach ($n in @($lanIp, "192.168.*", "10.*", "127.0.0.1", "localhost", "<local>")) {
    if ($parts -notcontains $n) { $parts += $n }
}
$merged = ($parts -join ";")
Set-ItemProperty -Path $inetPath -Name ProxyOverride -Value $merged
Write-Host "ProxyOverride: added $lanIp and 192.168.* (proxy stays enabled for other hosts)"

# --- Patch .env PUBLIC_API_URL / NO_PROXY if present ---
$envFile = Join-Path $RepoRoot ".env"
if (Test-Path $envFile) {
    $text = Get-Content $envFile -Raw -Encoding UTF8
    if ($text -match "(?m)^PUBLIC_API_URL=.*$") {
        $text = [regex]::Replace($text, "(?m)^PUBLIC_API_URL=.*$", "PUBLIC_API_URL=$publicUrl")
    } else {
        $text = "PUBLIC_API_URL=$publicUrl`r`n" + $text
    }
    $noProxyVal = "sas.amin.parminstorage.ir,parminstorage.ir,localhost,127.0.0.1,$lanIp,192.168.0.0/16,10.0.0.0/8"
    if ($text -match "(?m)^NO_PROXY=.*$") {
        $text = [regex]::Replace($text, "(?m)^NO_PROXY=.*$", "NO_PROXY=$noProxyVal")
    } else {
        $text += "`r`nNO_PROXY=$noProxyVal`r`n"
    }
    if ($text -match "(?m)^no_proxy=.*$") {
        $text = [regex]::Replace($text, "(?m)^no_proxy=.*$", "no_proxy=$noProxyVal")
    } else {
        $text += "no_proxy=$noProxyVal`r`n"
    }
    Set-Content -Path $envFile -Value $text -Encoding UTF8 -NoNewline
    Write-Host ".env updated: PUBLIC_API_URL=$publicUrl"
} else {
    Write-Host "No .env found — set PUBLIC_API_URL=$publicUrl manually"
}

# Process env for this session / child
$env:PUBLIC_API_URL = $publicUrl
$env:NO_PROXY = "sas.amin.parminstorage.ir,parminstorage.ir,localhost,127.0.0.1,$lanIp,192.168.0.0/16,10.0.0.0/8"
$env:no_proxy = $env:NO_PROXY

Write-Host ""
Write-Host "=== Give collaborator ==="
Write-Host "Base URL:  $publicUrl"
Write-Host "Header:    X-API-Key: <from your .env API_KEY>"
Write-Host "Health:    curl $publicUrl/"
Write-Host "Keep your system proxy ON — LAN is bypassed."
Write-Host ""

if ($RestartApi) {
    $listen = netstat -ano | Select-String ":$Port\s+.*LISTENING"
    if ($listen) {
        $procId = ($listen.ToString() -split "\s+")[-1]
        if ($procId -match "^\d+$") {
            Write-Host "Stopping PID $procId on port $Port..."
            Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    }
    Write-Host "Starting API..."
    $env:PYTHONUTF8 = "1"
    $env:PYTHONPATH = $RepoRoot
    Start-Process -FilePath (Join-Path $RepoRoot "venv\Scripts\python.exe") `
        -ArgumentList "-m", "backend.main_api" `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Normal
    Write-Host "API start launched. Wait ~20s then: curl $publicUrl/"
}
