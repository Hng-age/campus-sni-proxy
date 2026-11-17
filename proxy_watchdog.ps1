# SNI Proxy watchdog - restores the original system proxy if the proxy dies
$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$flag = Join-Path $root "state\proxy_active.flag"
$stateFile = Join-Path $root "state\proxy_state.json"
$logFile = Join-Path $root "state\watchdog.log"
$reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$winKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Connections"

function Write-Log([string]$msg) {
    $line = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") + " " + $msg
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

$downCount = 0
while (Test-Path $flag) {
    Start-Sleep -Seconds 5
    if (-not (Test-Path $flag)) { break }

    $alive = $false
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 8888)
        $tcp.Close()
        $alive = $true
    } catch { }

    if ($alive) {
        $downCount = 0
        continue
    }

    $downCount++
    if ($downCount -lt 2) { continue }

    Write-Log "proxy is down, restoring original system proxy"
    if (Test-Path $stateFile) {
        $s = Get-Content $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        Set-ItemProperty -Path $reg -Name ProxyEnable -Value ([int]$s.ProxyEnable)
        if ($s.ProxyServer) {
            Set-ItemProperty -Path $reg -Name ProxyServer -Value $s.ProxyServer
        } else {
            Remove-ItemProperty -Path $reg -Name ProxyServer
        }
        if ($s.ProxyOverride) {
            Set-ItemProperty -Path $reg -Name ProxyOverride -Value $s.ProxyOverride
        } else {
            Remove-ItemProperty -Path $reg -Name ProxyOverride
        }
        if ($s.AutoConfigURL) {
            Set-ItemProperty -Path $reg -Name AutoConfigURL -Value $s.AutoConfigURL
        } else {
            Remove-ItemProperty -Path $reg -Name AutoConfigURL
        }
        if ($s.PSObject.Properties.Name -contains "WinHttpSettings") {
            if ($s.WinHttpSettings) {
                $bytes = [Convert]::FromBase64String([string]$s.WinHttpSettings)
                Set-ItemProperty -Path $winKey -Name WinHttpSettings -Value $bytes -Type Binary
            } else {
                Remove-ItemProperty -Path $winKey -Name WinHttpSettings
            }
        } else {
            netsh winhttp reset proxy | Out-Null
        }
        Remove-Item $stateFile -Force
    } else {
        Set-ItemProperty -Path $reg -Name ProxyEnable -Value 0
    }
    Remove-Item $flag -Force
    Write-Log "system proxy restored"
    break
}
