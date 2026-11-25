# Proxy watchdog - restores direct / original system proxy if SNI Proxy or TUN drops unexpectedly
$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$sniFlag = Join-Path $root "state\proxy_active.flag"
$sniPidFile = Join-Path $root "state\proxy.pid"
$tunFlag = Join-Path $root "state\tun_active.flag"
$tunPidFile = Join-Path $root "state\tun.pid"
$stateFile = Join-Path $root "state\proxy_state.json"
$logFile = Join-Path $root "state\watchdog.log"
$reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
$winKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Connections"

function Write-Log([string]$msg) {
    $line = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") + " " + $msg
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

function Test-IsSelfProxyValue([string]$val) {
    if (-not $val) { return $false }
    return ($val -like "*127.0.0.1:8888*" -or $val -like "*127.0.0.1:17897*")
}

function Refresh-WinINet {
    try {
        $sig = @"
[DllImport("wininet.dll", SetLastError = true, CharSet=CharSet.Auto)]
public static extern bool InternetSetOption(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);
"@
        if (-not ([System.Management.Automation.PSTypeName]"ProxyHelper.WinINetNotify").Type) {
            Add-Type -MemberDefinition $sig -Name "WinINetNotify" -Namespace "ProxyHelper" -PassThru -ErrorAction SilentlyContinue | Out-Null
        }
        [ProxyHelper.WinINetNotify]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) | Out-Null
        [ProxyHelper.WinINetNotify]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) | Out-Null
    } catch { }
}

function Restore-SystemDirect {
    if (Test-Path $stateFile) {
        try {
            $s = Get-Content $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $srv = [string]$s.ProxyServer
            $pac = [string]$s.AutoConfigURL
            $en = [int]$s.ProxyEnable
            if ((Test-IsSelfProxyValue $srv) -or (Test-IsSelfProxyValue $pac)) {
                $en = 0
                $srv = ""
                $pac = ""
            }
            Set-ItemProperty -Path $reg -Name ProxyEnable -Value $en
            if ($srv) {
                Set-ItemProperty -Path $reg -Name ProxyServer -Value $srv
            } else {
                Remove-ItemProperty -Path $reg -Name ProxyServer -ErrorAction SilentlyContinue
            }
            if ($s.ProxyOverride -and -not (Test-IsSelfProxyValue $srv)) {
                Set-ItemProperty -Path $reg -Name ProxyOverride -Value $s.ProxyOverride
            } else {
                Remove-ItemProperty -Path $reg -Name ProxyOverride -ErrorAction SilentlyContinue
            }
            if ($pac) {
                Set-ItemProperty -Path $reg -Name AutoConfigURL -Value $pac
            } else {
                Remove-ItemProperty -Path $reg -Name AutoConfigURL -ErrorAction SilentlyContinue
            }
            if ($s.PSObject.Properties.Name -contains "WinHttpSettings") {
                if ($s.WinHttpSettings) {
                    $bytes = [Convert]::FromBase64String([string]$s.WinHttpSettings)
                    Set-ItemProperty -Path $winKey -Name WinHttpSettings -Value $bytes -Type Binary
                } else {
                    Remove-ItemProperty -Path $winKey -Name WinHttpSettings -ErrorAction SilentlyContinue
                }
            } else {
                netsh winhttp reset proxy | Out-Null
            }
        } catch {
            Set-ItemProperty -Path $reg -Name ProxyEnable -Value 0
            Remove-ItemProperty -Path $reg -Name ProxyServer -ErrorAction SilentlyContinue
            Remove-ItemProperty -Path $reg -Name AutoConfigURL -ErrorAction SilentlyContinue
        }
        Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
    } else {
        Set-ItemProperty -Path $reg -Name ProxyEnable -Value 0
        Remove-ItemProperty -Path $reg -Name ProxyServer -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path $reg -Name AutoConfigURL -ErrorAction SilentlyContinue
    }
    Refresh-WinINet
    Write-Log "system proxy restored to direct / pre-proxy state"
}

function Test-SniAlive {
    $portOpen = $false
    try {
        $conn = Get-NetTCPConnection -LocalPort 8888 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) {
            $portOpen = $true
            $ownerPid = [int]$conn.OwningProcess
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
            if ($proc -and ($proc.Name -eq "python.exe" -or $proc.Name -eq "pythonw.exe")) {
                if ($proc.CommandLine -and $proc.CommandLine -like "*mitm_sni_proxy*") {
                    return @($true, $true)
                } elseif (Test-Path $sniPidFile) {
                    $saved = Get-Content $sniPidFile -Raw -ErrorAction SilentlyContinue
                    if ($saved -and $saved.Trim() -eq [string]$ownerPid) { return @($true, $true) }
                }
            }
        }
    } catch { }
    return @($false, $portOpen)
}

function Test-TunAlive {
    try {
        if (Test-Path $tunPidFile) {
            $rawPid = Get-Content $tunPidFile -Raw -ErrorAction SilentlyContinue
            if ($rawPid -and $rawPid.Trim() -match "^\d+$") {
                $proc = Get-Process -Id ([int]$rawPid.Trim()) -ErrorAction SilentlyContinue
                if ($proc -and -not $proc.HasExited) { return $true }
            }
        }
        $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { ($_.Name -like "*mihomo*") -and $_.CommandLine -like "*tun_mihomo.yaml*" }
        return ($null -ne $procs)
    } catch {
        return $false
    }
}

$sniDownCount = 0
$tunDownCount = 0

while ((Test-Path $sniFlag) -or (Test-Path $tunFlag)) {
    Start-Sleep -Seconds 3
    $hasSni = Test-Path $sniFlag
    $hasTun = Test-Path $tunFlag
    if (-not $hasSni -and -not $hasTun) { break }

    if ($hasSni) {
        $res = Test-SniAlive
        $alive = [bool]$res[0]
        $portOpen = [bool]$res[1]
        if ($alive) {
            $sniDownCount = 0
        } else {
            if ($portOpen) {
                Write-Log "port 8888 is owned by another process; treating SNI proxy as down"
            }
            $sniDownCount++
            if ($sniDownCount -ge 2) {
                Write-Log "SNI proxy is down, restoring system proxy"
                Remove-Item $sniFlag -Force -ErrorAction SilentlyContinue
                if (-not (Test-Path $tunFlag)) {
                    Restore-SystemDirect
                }
                $sniDownCount = 0
            }
        }
    } else {
        $sniDownCount = 0
    }

    if ($hasTun) {
        if (Test-TunAlive) {
            $tunDownCount = 0
        } else {
            $tunDownCount++
            if ($tunDownCount -ge 2) {
                Write-Log "TUN core is down, restoring system proxy to direct"
                Remove-Item $tunFlag -Force -ErrorAction SilentlyContinue
                Remove-Item $tunPidFile -Force -ErrorAction SilentlyContinue
                if (-not (Test-Path $sniFlag)) {
                    Restore-SystemDirect
                }
                $tunDownCount = 0
            }
        }
    } else {
        $tunDownCount = 0
    }
}
