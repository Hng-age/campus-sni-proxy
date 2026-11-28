# SNI Proxy Manager - 一键启动/停止
# 需要管理员权限：双击 bat 会自动请求提权，直接运行本脚本也会自动提权
# 2.0.0 起：支持 -Action 非交互模式（GUI 调用）；不带参数仍是原命令行菜单

param(
    [string]$Action = "",
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$Version = "3.5.1"

# 隐藏控制台中的提权脚本偶发“动作已执行完但 PowerShell 进程不退出”，
# 会让 GUI 的操作线程一直等待、按钮永久置灰。用硬退出规避该问题。
function Exit-Immediate([int]$code) {
    try { [Environment]::Exit($code) } catch { exit $code }
}

# 非交互模式：让重定向的输出按 UTF-8 编码（GUI 按 UTF-8 读取）
if ($Action -ne "") {
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
}
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TociExe = Join-Path $ScriptDir "toci.exe"
$CfgPy = Join-Path $ScriptDir "sni_proxy\config.py"
if (Test-Path $CfgPy) {
    try {
        $cfgText = Get-Content $CfgPy -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($cfgText -match 'VERSION\s*=\s*"([0-9]+(?:\.[0-9]+)+)"') {
            $Version = $Matches[1]
        }
    } catch { }
}
$ProxyScript = Join-Path $ScriptDir "mitm_sni_proxy.py"
$CertDir = Join-Path $ScriptDir "mitm_certs"
$CaCert = Join-Path $CertDir "ca_cert.crt"
$WildcardCert = Join-Path $CertDir "_wildcard.crt"
$CaName = "MITM SNI Proxy CA"
$LegacyCaSha256 = "b4fa5edf50dfc8a54ed8727bc96a7e41cce963b3b64db123104dce1664d30671"
$LegacyThumbFile = Join-Path $CertDir "legacy_ca.thumbprint"
$WatchdogScript = Join-Path $ScriptDir "proxy_watchdog.ps1"
$StateDir = Join-Path $ScriptDir "state"
$ProxyStateFile = Join-Path $StateDir "proxy_state.json"
$ActiveFlag = Join-Path $StateDir "proxy_active.flag"
$LogFile = Join-Path $ScriptDir "logs\proxy.log"
$TunPidFile = Join-Path $StateDir "tun.pid"
$TunActiveFlag = Join-Path $StateDir "tun_active.flag"
$TunYamlFile = Join-Path $StateDir "tun_mihomo.yaml"
$TunStateDir = Join-Path $StateDir "tun"
$TunConfigFile = Join-Path $ScriptDir "tun_config.json"
$TunLogFile = Join-Path $ScriptDir "logs\tun.log"
$TunErrFile = Join-Path $ScriptDir "logs\tun_err.log"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal -ArgumentList $id
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---------------- 管理员权限细分判断 ----------------
# 只有显式安装/卸载系统机器级根证书，或创建/销毁 TUN 虚拟网卡时才必须提权；日常 SNI 代理启停免提权
$adminRequired = $false
if ($Action -ne "") {
    $actLower = $Action.ToLower()
    if ($actLower -in @("install-ca", "remove-ca", "install-ca-machine", "remove-ca-machine", "start-tun", "stop-tun", "restart-tun")) {
        $adminRequired = $true
    }
}

if ($adminRequired -and (-not (Test-IsAdmin))) {
    if ($Action -ne "") {
        # GUI 非交互模式：提权子进程的输出写入临时文件，父进程等待后转发退码。
        $tag = [guid]::NewGuid().ToString("N")
        $actOut = Join-Path $env:TEMP "sni_action_$tag.out"
        $actErr = Join-Path $env:TEMP "sni_action_$tag.err"
        $actCmd = Join-Path $env:TEMP "sni_action_$tag.cmd"
        $pwshExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        $innerArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Action `"$Action`""
        if ($NonInteractive) { $innerArgs += " -NonInteractive" }
        $cmdLines = @(
            "@echo off",
            "`"$pwshExe`" $innerArgs > `"$actOut`" 2> `"$actErr`"",
            "exit /b %ERRORLEVEL%"
        )
        $exitCode = 1
        try {
            Set-Content -Path $actCmd -Value $cmdLines -Encoding OEM
            $p = Start-Process -FilePath $actCmd -Verb RunAs `
                -WindowStyle Hidden -PassThru
            # 不用 -Wait：超时后可强制结束，避免父进程永远等待提权子进程
            if (-not $p.WaitForExit(240000)) {
                try { $p.Kill() } catch { }
                Write-Host "  [!!] 提权子进程超时未返回，已终止"
                $exitCode = 124
            } else {
                foreach ($f in @($actOut, $actErr)) {
                    if (Test-Path $f) {
                        $text = Get-Content $f -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
                        if ($text) { Write-Host $text.TrimEnd() }
                    }
                }
                $exitCode = [int]$p.ExitCode
            }
        } catch {
            $native = 0
            try { $native = [int]$_.Exception.NativeErrorCode } catch { }
            if ($native -eq 1223 -or $_.Exception.Message -match "取消|cancel") {
                Write-Host "  [!!] 已取消 UAC 提权，证书未做任何修改。"
            } else {
                Write-Host "  [!!] 提权失败：$($_.Exception.Message)"
            }
            $exitCode = 1
        } finally {
            Remove-Item $actCmd, $actOut, $actErr -Force -ErrorAction SilentlyContinue
        }
        Exit-Immediate $exitCode
    }
    Write-Host ""
    Write-Host "  [!] 此操作需要管理员权限（安装/移除系统根证书）" -ForegroundColor Yellow
    Write-Host "      正在请求提权，请在 UAC 弹窗中点击“是”..." -ForegroundColor Yellow
    try {
        Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
        ) | Out-Null
    } catch {
        Write-Host "  [!!] 提权被取消，无法继续。" -ForegroundColor Red
        Read-Host "  按回车退出"
    }
    exit
}

# ---------------- 环境探测 ----------------
function Find-Python {
    $cands = New-Object System.Collections.Generic.List[string]

    foreach ($c in @(Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        if ($c.Source -and $c.Source -notlike "*\WindowsApps\*") { $cands.Add($c.Source) }
    }

    foreach ($pattern in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe"),
        "C:\Python3*\python.exe",
        "C:\Program Files\Python3*\python.exe",
        "C:\Program Files (x86)\Python3*\python.exe"
    )) {
        Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            ForEach-Object { $cands.Add($_.FullName) }
    }

    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $exe = (& $pyLauncher.Source -3 -c "import sys;print(sys.executable)" 2>$null | Select-Object -First 1)
            if ($exe -and $exe -notlike "*\WindowsApps\*") { $cands.Add($exe.Trim()) }
        } catch { }
    }

    foreach ($exe in ($cands | Select-Object -Unique)) {
        if (-not (Test-Path $exe)) { continue }
        try {
            & $exe -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { continue }
            $ver = (& $exe -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null | Select-Object -First 1)
            $w = $exe -replace 'python\.exe$', 'pythonw.exe'
            if (-not (Test-Path $w)) { $w = $null }
            return [pscustomobject]@{ Exe = $exe; Windowless = $w; Version = "$ver" }
        } catch {
            continue
        }
    }
    return $null
}

function Find-OpenSSL {
    foreach ($p in @(
        "C:\Program Files\Git\usr\bin\openssl.exe",
        "C:\Program Files (x86)\Git\usr\bin\openssl.exe",
        "C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
        "C:\Program Files\OpenSSL-Win32\bin\openssl.exe"
    )) {
        if (Test-Path $p) { return $p }
    }
    $cmd = Get-Command openssl.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Update-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (@($machine, $user) -join ";")
}

function Install-PythonRuntime {
    Write-Host "  [*] 未检测到 Python 3.8+，尝试自动安装 Python 3.12..." -ForegroundColor Yellow
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "  [*] 使用 winget 安装 Python（约 1-2 分钟）..." -ForegroundColor DarkGray
        try {
            Start-Process -FilePath $winget.Source -ArgumentList @(
                "install", "--id", "Python.Python.3.12", "-e", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity"
            ) -WindowStyle Hidden -Wait | Out-Null
            Update-ProcessPath
            $found = Find-Python
            if ($found) { return $found }
        } catch {
            Write-Host "  [!] winget 安装失败，改用官方安装包" -ForegroundColor DarkGray
        }
    }

    $urls = @(
        "https://mirrors.huaweicloud.com/python/3.12.7/python-3.12.7-amd64.exe",
        "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    )
    $exe = Join-Path $env:TEMP "python-3.12.7-amd64.exe"
    $downloaded = $false
    $oldProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        foreach ($u in $urls) {
            try {
                Write-Host "  [*] 下载 $u" -ForegroundColor DarkGray
                Invoke-WebRequest -Uri $u -OutFile $exe -UseBasicParsing -TimeoutSec 180
                if ((Test-Path $exe) -and ((Get-Item $exe).Length -gt 10MB)) {
                    $downloaded = $true
                    break
                }
            } catch {
                Write-Host "  [!] 下载失败：$($_.Exception.Message)" -ForegroundColor DarkGray
            }
        }
    } finally {
        $ProgressPreference = $oldProgress
    }
    if (-not $downloaded) { return $null }

    Write-Host "  [*] 正在静默安装 Python..." -ForegroundColor Yellow
    try {
        Start-Process -FilePath $exe -ArgumentList @(
            "/quiet", "InstallAllUsers=0", "PrependPath=1",
            "Include_pip=1", "Include_test=0", "Include_launcher=1"
        ) -Wait | Out-Null
    } catch {
        Write-Host "  [!!] Python 安装程序无法运行：$($_.Exception.Message)" -ForegroundColor Red
        return $null
    }
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    Update-ProcessPath
    Start-Sleep -Seconds 2
    return (Find-Python)
}

function Install-GitForWindows {
    Write-Host "  [*] 未检测到 openssl，尝试自动安装 Git for Windows..." -ForegroundColor Yellow
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "  [*] 使用 winget 安装 Git（约 1-2 分钟）..." -ForegroundColor DarkGray
        try {
            Start-Process -FilePath $winget.Source -ArgumentList @(
                "install", "--id", "Git.Git", "-e", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity"
            ) -WindowStyle Hidden -Wait | Out-Null
            Update-ProcessPath
            $found = Find-OpenSSL
            if ($found) { return $found }
        } catch {
            Write-Host "  [!] winget 安装失败，改用国内镜像安装包" -ForegroundColor DarkGray
        }
    }

    $exe = Join-Path $env:TEMP "Git-64-bit.exe"
    $downloaded = $false
    $oldProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        $base = "https://registry.npmmirror.com/-/binary/git-for-windows/"
        $dirs = Invoke-RestMethod -Uri $base -TimeoutSec 30
        $versions = foreach ($d in $dirs) {
            if ($d.type -ne "dir") { continue }
            if ($d.name -match '^v(\d+\.\d+\.\d+)\.windows\.\d+/?$') {
                [pscustomobject]@{ Version = [version]$Matches[1]; Dir = $d }
            }
        }
        $latest = $versions | Sort-Object Version | Select-Object -Last 1
        if (-not $latest) { throw "没有找到可用版本" }
        $files = Invoke-RestMethod -Uri $latest.Dir.url -TimeoutSec 30
        $asset = $files | Where-Object { $_.name -match '^Git-.*-64-bit\.exe$' } |
            Select-Object -First 1
        if (-not $asset) { throw "没有找到 64 位安装包" }
        $assetUrl = $asset.url
        if ($assetUrl -notmatch '^https?://') {
            $assetUrl = "https://registry.npmmirror.com" + $assetUrl
        }
        Write-Host "  [*] 下载 $($asset.name)（约 65 MB）..." -ForegroundColor DarkGray
        Invoke-WebRequest -Uri $assetUrl -OutFile $exe -UseBasicParsing -TimeoutSec 600
        if ((Test-Path $exe) -and ((Get-Item $exe).Length -gt 40MB)) {
            $downloaded = $true
        }
    } catch {
        Write-Host "  [!!] 自动下载 Git 失败：$($_.Exception.Message)" -ForegroundColor Red
    } finally {
        $ProgressPreference = $oldProgress
    }
    if (-not $downloaded) { return $null }

    Write-Host "  [*] 正在静默安装 Git for Windows..." -ForegroundColor Yellow
    try {
        Start-Process -FilePath $exe -ArgumentList @(
            "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-",
            "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"
        ) -Wait | Out-Null
    } catch {
        Write-Host "  [!!] Git 安装程序无法运行：$($_.Exception.Message)" -ForegroundColor Red
        return $null
    }
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    Update-ProcessPath
    return (Find-OpenSSL)
}

function Test-PythonHasCryptography([string]$pyExe) {
    if (-not $pyExe -or -not (Test-Path $pyExe)) { return $false }
    try {
        & $pyExe -c "import cryptography" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Ensure-Dependencies {
    # 便携版自带 toci.exe 时内置 Python + cryptography，无需安装外部 Python / Git
    if (Test-Path $TociExe) {
        return $true
    }

    $py = Find-Python
    if (-not $py) {
        Write-Host "  [!] 未检测到 Python，正在自动安装（首次运行需要联网）..." -ForegroundColor Yellow
        $py = Install-PythonRuntime
        if (-not $py) {
            Write-Host "  [!!] Python 自动安装失败，请手动安装 3.8+ 后重试：" -ForegroundColor Red
            Write-Host "       https://www.python.org/downloads/" -ForegroundColor Yellow
            return $false
        }
        Write-Host "  [OK] Python $($py.Version) 已就绪" -ForegroundColor Green
    }

    $needCerts = (-not (Test-Path $CaCert)) -or (-not (Test-Path $WildcardCert))
    if ($needCerts -and (-not (Test-PythonHasCryptography $py.Exe)) -and (-not (Find-OpenSSL))) {
        Write-Host "  [!] 首次运行需要生成设备证书，正在自动安装 Git for Windows..." -ForegroundColor Yellow
        $ossl = Install-GitForWindows
        if (-not $ossl) {
            Write-Host "  [!!] openssl 自动安装失败，请手动安装 Git for Windows 后重试：" -ForegroundColor Red
            Write-Host "       https://git-scm.com/download/win" -ForegroundColor Yellow
            return $false
        }
        $env:OPENSSL_EXE = $ossl
        Write-Host "  [OK] openssl 已就绪" -ForegroundColor Green
    }
    return $true
}

function Get-PortOwner {
    try {
        $conn = Get-NetTCPConnection -LocalPort 8888 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) { return "$($proc.ProcessName) (PID $($proc.Id))" }
            return "PID $($conn.OwningProcess)"
        }
    } catch { }
    return $null
}

# ---------------- 证书初始化 ----------------
function Initialize-Certs {
    if (-not (Ensure-Dependencies)) { return $false }

    $py = Find-Python
    $useToci = $false
    if (Test-Path $TociExe) {
        if ((-not $py) -or (-not (Test-PythonHasCryptography $py.Exe))) {
            $useToci = $true
        }
    }
    if ((-not $useToci) -and (-not $py)) {
        Write-Host "  [!!] 未检测到 Python，无法初始化设备证书" -ForegroundColor Red
        return $false
    }

    $ossl = Find-OpenSSL
    if ($ossl) { $env:OPENSSL_EXE = $ossl }

    $isLegacy = $false
    if (Test-Path $CaCert) {
        try {
            $isLegacy = ((Get-FileHash $CaCert -Algorithm SHA256).Hash.ToLower() -eq $LegacyCaSha256)
        } catch { }
    }
    $needNew = (-not (Test-Path $CaCert)) -or (-not (Test-Path $WildcardCert))
    if ((-not $useToci) -and ($needNew -or $isLegacy) -and (-not (Test-PythonHasCryptography $py.Exe)) -and (-not $ossl)) {
        Write-Host "  [!!] 首次使用/安全升级需要生成设备专属证书，但未检测到 cryptography 或 openssl" -ForegroundColor Red
        Write-Host "       请安装 Git for Windows（自带 openssl）或 cryptography 后重新运行" -ForegroundColor Yellow
        return $false
    }

    Write-Host "  [*] 检查设备证书..." -ForegroundColor Yellow
    $initOut = Join-Path $env:TEMP "sni_init_out.log"
    $initErr = Join-Path $env:TEMP "sni_init_err.log"
    Remove-Item $initOut, $initErr -ErrorAction SilentlyContinue
    try {
        # 用重定向文件接收输出，避免 Python 的 stderr 日志被 PowerShell
        # 当成 NativeCommandError 中断脚本
        if ($useToci) {
            $p = Start-Process -FilePath $TociExe `
                -ArgumentList @("--init-certs") `
                -WindowStyle Hidden -Wait -PassThru `
                -RedirectStandardOutput $initOut -RedirectStandardError $initErr
        } else {
            $p = Start-Process -FilePath $py.Exe `
                -ArgumentList @("`"$ProxyScript`"", "--init-certs") `
                -WindowStyle Hidden -Wait -PassThru `
                -RedirectStandardOutput $initOut -RedirectStandardError $initErr
        }
        $code = $p.ExitCode
    } catch {
        Write-Host "  [!!] 无法运行证书初始化：$($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
    if ($code -ne 0) {
        Write-Host "  [!!] 设备证书初始化失败（退出码 $code）" -ForegroundColor Red
        foreach ($f in @($initErr, $initOut)) {
            if (Test-Path $f) {
                Get-Content $f -Tail 6 | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
            }
        }
        return $false
    }
    Remove-Item $initOut, $initErr -ErrorAction SilentlyContinue

    # 1.0.2 的共享根证书已被轮换，从系统信任区移除（机器 + 当前用户）
    if (Test-Path $LegacyThumbFile) {
        $thumb = (Get-Content $LegacyThumbFile -Raw).Trim()
        if ($thumb) {
            $removed = 0
            foreach ($store in @("Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root")) {
                $old = Get-ChildItem $store -ErrorAction SilentlyContinue |
                    Where-Object { $_.Thumbprint -eq $thumb }
                if ($old) {
                    $removed += @($old).Count
                    $old | Remove-Item -Force -ErrorAction SilentlyContinue
                }
            }
            if ($removed -gt 0) {
                Write-Host "  [OK] 已移除 1.0.2 共享根证书" -ForegroundColor Green
            }
            $still = 0
            foreach ($store in @("Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root")) {
                $still += @(Get-ChildItem $store -ErrorAction SilentlyContinue |
                    Where-Object { $_.Thumbprint -eq $thumb }).Count
            }
            if ($still -gt 0) {
                Write-Host "  [!!] 旧共享根证书仍在信任库中（$still 个），请手动删除" -ForegroundColor Red
            } else {
                Write-Host "  [OK] 已确认旧共享根证书从信任库移除" -ForegroundColor Green
                Remove-Item $LegacyThumbFile -Force -ErrorAction SilentlyContinue
            }
        }
    }

    return ((Test-Path $CaCert) -and (Test-Path $WildcardCert))
}

# ---------------- 系统代理状态备份 / 恢复 ----------------
function Get-WinHttpSettingsB64 {
    $key = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Connections"
    $v = Get-ItemProperty -Path $key -Name WinHttpSettings -ErrorAction SilentlyContinue
    if ($null -eq $v) { return "" }
    $bytes = $v.WinHttpSettings
    if ($null -eq $bytes) { return "" }
    return [Convert]::ToBase64String([byte[]]$bytes)
}

function Restore-WinHttpSettingsB64([string]$b64) {
    $key = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Connections"
    try {
        if (-not (Test-Path $key)) { New-Item -Path $key -Force -ErrorAction Stop | Out-Null }
        if ($b64) {
            $bytes = [Convert]::FromBase64String($b64)
            Set-ItemProperty -Path $key -Name WinHttpSettings -Value $bytes -Type Binary -ErrorAction Stop
        } else {
            Remove-ItemProperty -Path $key -Name WinHttpSettings -ErrorAction SilentlyContinue
        }
        return $true
    } catch [System.Security.SecurityException] {
        Write-Host "  [提示] 无管理员权限，WinHTTP 代理设置未恢复（浏览器代理不受影响；全局模式请以管理员身份重试停止）" -ForegroundColor Yellow
        return $false
    } catch [System.UnauthorizedAccessException] {
        Write-Host "  [提示] 无管理员权限，WinHTTP 代理设置未恢复（浏览器代理不受影响；全局模式请以管理员身份重试停止）" -ForegroundColor Yellow
        return $false
    } catch {
        Write-Host "  [提示] WinHTTP 代理设置恢复失败：$($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

function Get-ProxyRegState {
    $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $p = Get-ItemProperty -Path $reg -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        ProxyEnable     = [int]($p.ProxyEnable)
        ProxyServer     = [string]$p.ProxyServer
        ProxyOverride  = [string]$p.ProxyOverride
        AutoConfigURL  = [string]$p.AutoConfigURL
        WinHttpSettings = Get-WinHttpSettingsB64
    }
}

function Test-IsSelfProxyValue([string]$val) {
    if (-not $val) { return $false }
    return ($val -like "*127.0.0.1:8888*" -or $val -like "*127.0.0.1:17897*")
}

function Save-OriginalProxyState {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    if (Test-Path $ProxyStateFile) { return }
    $s = Get-ProxyRegState
    # 若当前系统代理或 PAC 已指向本工具（8888 或 TUN 17897），按“直连（无代理）”记录，避免恢复死循环
    $isSelfServer = ($s.ProxyEnable -eq 1 -and (Test-IsSelfProxyValue $s.ProxyServer))
    $isSelfPac = (Test-IsSelfProxyValue $s.AutoConfigURL)
    if ($isSelfServer -or $isSelfPac) {
        $s.ProxyEnable = 0
        $s.ProxyServer = ""
        $s.ProxyOverride = ""
        $s.AutoConfigURL = ""
        $s.WinHttpSettings = ""
    }
    $s | ConvertTo-Json | Set-Content -Path $ProxyStateFile -Encoding UTF8
}

function Restore-OriginalProxyState {
    $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $winHttp = $null
    $hasWinHttp = $false
    if (Test-Path $ProxyStateFile) {
        try {
            $s = Get-Content $ProxyStateFile -Raw -Encoding UTF8 | ConvertFrom-Json
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
                $hasWinHttp = $true
                $winHttp = [string]$s.WinHttpSettings
            }
            Remove-Item $ProxyStateFile -Force
        } catch {
            Set-ItemProperty -Path $reg -Name ProxyEnable -Value 0
            Remove-ItemProperty -Path $reg -Name ProxyServer -ErrorAction SilentlyContinue
            Remove-ItemProperty -Path $reg -Name AutoConfigURL -ErrorAction SilentlyContinue
            Remove-Item $ProxyStateFile -Force -ErrorAction SilentlyContinue
        }
    } else {
        Set-ItemProperty -Path $reg -Name ProxyEnable -Value 0
        Remove-ItemProperty -Path $reg -Name ProxyServer -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path $reg -Name AutoConfigURL -ErrorAction SilentlyContinue
    }

    if ($hasWinHttp) {
        [void](Restore-WinHttpSettingsB64 $winHttp)
    } else {
        if (Test-IsAdmin) {
            try { netsh winhttp reset proxy 2>$null | Out-Null } catch { }
        } else {
            Write-Host "  [提示] 无管理员权限，已跳过 WinHTTP 重置（浏览器代理不受影响；全局模式请以管理员身份重试停止）" -ForegroundColor Yellow
        }
    }
}

function Start-Watchdog {
    Stop-Watchdog
    if (-not (Test-Path $WatchdogScript)) { return }
    try {
        # 用 WMI 启动，避免守护进程随管理器窗口关闭而退出。
        # 只设置 ShowWindow=0：实测可保持 PowerShell 存活且不显示任何窗口；
        # DETACHED_PROCESS 会让 PowerShell 立即退出，不能使用。
        $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$WatchdogScript`""
        $startup = ([wmiclass]"Win32_ProcessStartup").CreateInstance()
        $startup.ShowWindow = 0
        ([wmiclass]"Win32_Process").Create($cmd, $null, $startup) | Out-Null
    } catch { }
}

function Stop-Watchdog {
    try {
        Get-CimInstance Win32_Process |
            Where-Object { $_.Name -eq "powershell.exe" -and $_.CommandLine -like "*proxy_watchdog.ps1*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } catch { }
}

function Show-Logs {
    Write-Host ""
    if (-not (Test-Path $LogFile)) {
        Write-Host "  暂无日志（代理还没有运行过）" -ForegroundColor Yellow
        Write-Host ""
        return
    }
    Write-Host "  $LogFile" -ForegroundColor DarkGray
    Write-Host ""
    Get-Content $LogFile -Tail 40 -Encoding UTF8 | ForEach-Object {
        if ($_ -match "\[ERROR\]") { Write-Host "  $_" -ForegroundColor Red }
        elseif ($_ -match "\[WARNING\]") { Write-Host "  $_" -ForegroundColor Yellow }
        else { Write-Host "  $_" -ForegroundColor Gray }
    }
    Write-Host ""
}

# ---------------- 测速辅助 ----------------
function Invoke-CurlStat {
    param([string]$Url, [string]$Proxy, [int]$MaxTime = 12, [switch]$Head)
    $curlArgs = @("-s", "-o", "NUL", "-L", "-k", "--max-time", "$MaxTime",
        "-w", "%{http_code}|%{time_starttransfer}|%{time_total}")
    if ($Head) { $curlArgs += "-I" }
    if ($Proxy) { $curlArgs += @("--proxy", $Proxy) } else { $curlArgs += @("--noproxy", "*") }
    $curlArgs += $Url
    $out = (& curl.exe @curlArgs 2>$null | Out-String).Trim()
    if (-not $out) { return $null }
    $p = $out.Split("|")
    if ($p.Count -lt 3) { return $null }
    return [pscustomobject]@{
        Code      = $p[0]
        FirstByte = [double]$p[1]
        Total     = [double]$p[2]
    }
}

function Measure-DownloadSpeed {
    param([string]$Url, [string]$Proxy, [int]$Seconds = 8, [string]$InterfaceIp)
    $curlArgs = @("-s", "-o", "NUL", "-L", "-k", "--max-time", "$Seconds",
        "-w", "%{http_code}|%{speed_download}|%{size_download}")
    if ($Proxy) { $curlArgs += @("--proxy", $Proxy) } else { $curlArgs += @("--noproxy", "*") }
    if ($InterfaceIp) { $curlArgs += @("--interface", $InterfaceIp) }
    $curlArgs += $Url
    $out = (& curl.exe @curlArgs 2>$null | Out-String).Trim()
    if (-not $out) { return $null }
    $p = $out.Split("|")
    if ($p.Count -lt 3) { return $null }
    if ($p[0] -ne "200" -and $p[0] -ne "206") { return $null }
    return [pscustomobject]@{
        BytesPerSec = [double]$p[1]
        Bytes       = [double]$p[2]
    }
}

function Get-Uplinks {
    # default-route source IPs (same logic as the proxy's multi-path bonding)
    $ips = New-Object System.Collections.Generic.List[string]
    try {
        $out = route print -4
        foreach ($line in $out) {
            $p = @($line -split '\s+' | Where-Object { $_ -ne "" })
            if ($p.Count -ge 5 -and $p[0] -eq "0.0.0.0" -and $p[1] -eq "0.0.0.0") {
                $ip = $p[3]
                if ($ip -match '^127\.' -or $ip -match '^169\.254\.') { continue }
                if (-not $ips.Contains($ip)) { $ips.Add($ip) }
            }
        }
    } catch { }

    $result = @()
    foreach ($ip in $ips) {
        $alias = ""
        try {
            $ni = Get-NetIPAddress -IPAddress $ip -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($ni) { $alias = $ni.InterfaceAlias }
        } catch { }
        $result += [pscustomobject]@{ IP = $ip; Alias = $alias }
    }
    return $result
}

function Measure-MultiSpeed {
    # start one download per uplink at the same time, then sum the speeds
    param([string]$Url, [object[]]$Uplinks, [int]$Seconds = 8)
    $jobs = @()
    foreach ($u in $Uplinks) {
        $tmp = Join-Path $env:TEMP ("sni_speed_" + ($u.IP -replace '\.', '_') + ".txt")
        Remove-Item $tmp -ErrorAction SilentlyContinue
        $curlArgs = @("-s", "-o", "NUL", "-L", "-k", "--max-time", "$Seconds",
            "-w", "%{http_code}|%{speed_download}|%{size_download}",
            "--noproxy", "*", "--interface", $u.IP, $Url)
        $proc = $null
        try {
            $proc = Start-Process -FilePath "curl.exe" -ArgumentList $curlArgs -NoNewWindow -PassThru -RedirectStandardOutput $tmp
        } catch { }
        $jobs += [pscustomobject]@{ Proc = $proc; File = $tmp; Uplink = $u; Code = ""; Speed = 0 }
    }

    foreach ($j in $jobs) {
        if ($j.Proc) {
            [void]$j.Proc.WaitForExit(($Seconds + 15) * 1000)
            if (-not $j.Proc.HasExited) {
                try { $j.Proc.Kill() } catch { }
            }
        }
        if (Test-Path $j.File) {
            $raw = Get-Content $j.File -Raw -ErrorAction SilentlyContinue
            Remove-Item $j.File -ErrorAction SilentlyContinue
            if ($raw) {
                $p = $raw.Trim().Split("|")
                if ($p.Count -ge 3) {
                    $j.Code = $p[0]
                    $j.Speed = [double]$p[1]
                }
            }
        }
    }
    return $jobs
}

# ---------------- 状态检测 ----------------
function Get-ProxyListenerPid {
    try {
        $conn = Get-NetTCPConnection -LocalPort 8888 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($conn) { return [int]$conn.OwningProcess }
    } catch { }
    return $null
}

function Test-ProxyRunning {
    $listenerPid = Get-ProxyListenerPid
    if (-not $listenerPid) { return $false }
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid" -ErrorAction SilentlyContinue
    } catch {
        $proc = $null
    }
    if (-not $proc) { return $false }
    if ($proc.Name -notin @("python.exe", "pythonw.exe", "toci.exe")) { return $false }
    if ($proc.Name -eq "toci.exe") {
        if ($proc.CommandLine -and $proc.CommandLine -like "*--proxy*") { return $true }
    } elseif ($proc.CommandLine -and $proc.CommandLine -like "*mitm_sni_proxy*") {
        return $true
    }
    $pidFile = Join-Path $StateDir "proxy.pid"
    if (Test-Path $pidFile) {
        $saved = Get-Content $pidFile -Raw -ErrorAction SilentlyContinue
        if ($saved -and $saved.Trim() -eq [string]$listenerPid) { return $true }
    }
    return $false
}

function Test-CaInstalled {
    if (-not (Test-Path $CaCert)) { return $false }
    try {
        $ca = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CaCert)
        $mCert = Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue |
            Where-Object { $_.Thumbprint -eq $ca.Thumbprint }
        if ($mCert) { return $true }
        $uCert = Get-ChildItem Cert:\CurrentUser\Root -ErrorAction SilentlyContinue |
            Where-Object { $_.Thumbprint -eq $ca.Thumbprint }
        return ($null -ne $uCert)
    } catch {
        return $false
    }
}

# ---------------- 证书 / 代理 ----------------
function Install-CA {
    if (-not (Test-Path $CaCert)) {
        Write-Host "  [!!] 找不到设备根证书：$CaCert" -ForegroundColor Red
        Write-Host "       请先完成设备证书初始化（选 1 会自动处理）。" -ForegroundColor Red
        return $false
    }
    if (Test-CaInstalled) {
        Write-Host "  [OK] 设备根证书已安装" -ForegroundColor Green
        return $true
    }

    Write-Host "  [*] 正在安装设备根证书到“受信任的根证书颁发机构”..." -ForegroundColor Yellow
    $caOut = Join-Path $env:TEMP "sni_certutil_out.log"
    $caErr = Join-Path $env:TEMP "sni_certutil_err.log"
    Remove-Item $caOut, $caErr -ErrorAction SilentlyContinue

    $cArgs = @("-addstore", "-f", "Root", "`"$CaCert`"")
    if (-not (Test-IsAdmin)) {
        $cArgs = @("-user", "-addstore", "-f", "Root", "`"$CaCert`"")
    }

    try {
        $p = Start-Process -FilePath "certutil.exe" `
            -ArgumentList $cArgs `
            -WindowStyle Hidden -Wait -PassThru `
            -RedirectStandardOutput $caOut -RedirectStandardError $caErr
        $code = $p.ExitCode
    } catch {
        Write-Host "  [!!] 无法运行 certutil：$($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
    if ($code -ne 0) {
        Write-Host "  [!!] 根证书安装失败，多半被杀毒软件/安全卫士拦截" -ForegroundColor Red
        foreach ($f in @($caErr, $caOut)) {
            if (Test-Path $f) {
                Get-Content $f -Tail 5 | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
            }
        }
        Write-Host "       请临时关闭安全软件后重试。" -ForegroundColor Yellow
        return $false
    }
    Remove-Item $caOut, $caErr -ErrorAction SilentlyContinue
    if (-not (Test-CaInstalled)) {
        Write-Host "  [!!] 根证书安装后校验失败，请检查安全软件拦截" -ForegroundColor Red
        return $false
    }
    Write-Host "  [OK] 设备根证书已安装" -ForegroundColor Green
    return $true
}

function Remove-CA {
    $removed = 0
    foreach ($store in @("Cert:\LocalMachine\Root", "Cert:\CurrentUser\Root")) {
        $cert = Get-ChildItem $store -ErrorAction SilentlyContinue |
            Where-Object { $_.Subject -like "*$CaName*" }
        if ($cert) {
            Write-Host "  [*] 正在删除根证书（$store）..." -ForegroundColor Yellow
            $removed += @($cert).Count
            $cert | Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }
    if ($removed -gt 0) {
        Write-Host "  [OK] 根证书已删除" -ForegroundColor Green
    } else {
        Write-Host "  [OK] 根证书未安装，无需删除" -ForegroundColor Green
    }
}

function Start-Proxy {
    if (Test-ProxyRunning) {
        Write-Host "  [OK] 代理已在运行（127.0.0.1:8888）" -ForegroundColor Green
        return $true
    }

    $py = Find-Python
    $useToci = $false
    if (Test-Path $TociExe) {
        if (-not $py) { $useToci = $true }
    }
    if ((-not $useToci) -and (-not $py)) {
        Write-Host "  [!!] 未检测到 Python（需要 3.8 或更高版本）" -ForegroundColor Red
        Write-Host "       1) 打开 https://www.python.org/downloads/ 下载安装" -ForegroundColor Yellow
        Write-Host "       2) 安装第一步务必勾选 “Add python.exe to PATH”" -ForegroundColor Yellow
        Write-Host "       3) 装好后重新运行本程序" -ForegroundColor Yellow
        return $false
    }

    $ossl = Find-OpenSSL
    if ($ossl) {
        $env:OPENSSL_EXE = $ossl
    }

    if ((-not $useToci) -and (-not (Test-Path $ProxyScript))) {
        if (Test-Path $TociExe) {
            $useToci = $true
        } else {
            Write-Host "  [!!] 找不到代理程序：$ProxyScript" -ForegroundColor Red
            return $false
        }
    }

    $owner = Get-PortOwner
    if ($owner) {
        Write-Host "  [!!] 端口 8888 已被占用：$owner" -ForegroundColor Red
        Write-Host "       请先关闭该程序，再重新启动代理。" -ForegroundColor Yellow
        return $false
    }

    if ($useToci) {
        Write-Host "  [*] 运行模式: 便携版内置运行时 ($TociExe --proxy)" -ForegroundColor DarkGray
        $runner = $TociExe
        $runnerArgs = @("--proxy")
    } else {
        Write-Host "  [*] Python: $($py.Version)  ($($py.Exe))" -ForegroundColor DarkGray
        $runner = $py.Exe
        if ($py.Windowless) { $runner = $py.Windowless }
        $runnerArgs = @("`"$ProxyScript`"")
    }
    Write-Host "  [*] 正在启动代理..." -ForegroundColor Yellow

    $logOut = Join-Path $env:TEMP "sni_proxy_out.log"
    $logErr = Join-Path $env:TEMP "sni_proxy_err.log"
    Remove-Item $logOut, $logErr -ErrorAction SilentlyContinue

    $proc = $null
    try {
        $proc = Start-Process -FilePath $runner -ArgumentList $runnerArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput $logOut -RedirectStandardError $logErr
    } catch {
        Write-Host "  [!!] 无法启动代理进程：$($_.Exception.Message)" -ForegroundColor Red
        Write-Host "       可能被杀毒软件拦截，请允许运行后重试。" -ForegroundColor Yellow
        return $false
    }
    Start-Sleep -Seconds 3

    if (Test-ProxyRunning) {
        Write-Host "  [OK] 代理启动成功（PID $($proc.Id)，127.0.0.1:8888）" -ForegroundColor Green
        return $true
    }

    Write-Host "  [!!] 代理启动失败，错误信息：" -ForegroundColor Red
    foreach ($f in @($logErr, $logOut)) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 0) {
            Get-Content $f -Tail 8 | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
        }
    }
    return $false
}

function Stop-Proxy {
    Write-Host "  [*] 正在停止代理..." -ForegroundColor Yellow

    $procs = Get-CimInstance Win32_Process |
        Where-Object {
            (($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and $_.CommandLine -like "*mitm_sni_proxy*") -or
            ($_.Name -eq "toci.exe" -and $_.CommandLine -like "*--proxy*")
        }

    if ($procs) {
        foreach ($p in $procs) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  [OK] 已结束 PID $($p.ProcessId) ($($p.Name))" -ForegroundColor Green
        }
    }

    # 兜底：按端口占用进程结束（提权进程的 CommandLine 有时不可见）
    Start-Sleep -Milliseconds 500
    $conn = Get-NetTCPConnection -LocalPort 8888 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($conn) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and ($proc.ProcessName -in @("python", "pythonw", "toci"))) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Write-Host "  [OK] 已结束端口占用进程 PID $($proc.Id)" -ForegroundColor Green
        }
    }

    Start-Sleep -Seconds 1

    if (-not (Test-ProxyRunning)) {
        Write-Host "  [OK] 代理已停止" -ForegroundColor Green
    } else {
        Write-Host "  [!!] 端口 8888 仍被占用" -ForegroundColor Red
    }
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

function Set-SystemProxy {
    param([string]$Mode = "")
    Save-OriginalProxyState
    $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"

    if (-not $Mode) {
        $rulesFile = Join-Path $ScriptDir "rules.json"
        if (Test-Path $rulesFile) {
            try {
                $r = Get-Content $rulesFile -Raw -Encoding UTF8 | ConvertFrom-Json
                $Mode = $r.proxy_mode
            } catch { }
        }
    }
    if (-not $Mode) { $Mode = "pac" }

    if ($Mode -eq "pac") {
        Write-Host "  [*] 正在设置系统代理为 PAC 智能分流 (http://127.0.0.1:8888/proxy.pac)..." -ForegroundColor Yellow
        Set-ItemProperty -Path $reg -Name AutoConfigURL -Value "http://127.0.0.1:8888/proxy.pac"
        Set-ItemProperty -Path $reg -Name ProxyEnable -Value 0
        Remove-ItemProperty -Path $reg -Name ProxyServer -ErrorAction SilentlyContinue
    } else {
        Write-Host "  [*] 正在设置系统代理为全局模式 (127.0.0.1:8888)..." -ForegroundColor Yellow
        Remove-ItemProperty -Path $reg -Name AutoConfigURL -ErrorAction SilentlyContinue
        Set-ItemProperty -Path $reg -Name ProxyServer -Value "127.0.0.1:8888"
        Set-ItemProperty -Path $reg -Name ProxyEnable -Value 1
        netsh winhttp set proxy "127.0.0.1:8888" bypass-list="localhost;127.*;10.*;192.168.*" | Out-Null
    }

    Refresh-WinINet

    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    Set-Content -Path $ActiveFlag -Value (Get-Date).ToString("s") -Encoding ASCII
    Start-Watchdog
    Write-Host "  [OK] 系统代理已开启（$Mode 模式，异常退出会自动恢复）" -ForegroundColor Green
}

function Unset-SystemProxy {
    Write-Host "  [*] 正在恢复系统代理..." -ForegroundColor Yellow
    Remove-Item $ActiveFlag -Force -ErrorAction SilentlyContinue
    if (Test-Path $TunActiveFlag) {
        Write-Host "  [提示] TUN 模式仍在运行，保留其系统代理设置与看门狗" -ForegroundColor Yellow
        return
    }
    Stop-Watchdog
    $restored = $true
    try {
        Restore-OriginalProxyState
    } catch {
        $restored = $false
        Write-Host "  [!!] 系统代理恢复未完全成功：$($_.Exception.Message)" -ForegroundColor Yellow
    }
    Refresh-WinINet
    if ($restored) {
        Write-Host "  [OK] 系统代理已恢复为启动前的设置" -ForegroundColor Green
    } else {
        Write-Host "  [提示] 浏览器代理已按备份恢复；其余项目可稍后用管理员权限重试" -ForegroundColor Yellow
    }
}

# ---------------- 界面 ----------------
function Show-Menu {
    Clear-Host
    Write-Host ""
    Write-Host "  ======================================" -ForegroundColor Cyan
    Write-Host "   校园网 SNI 代理 $Version - 一键管理" -ForegroundColor Cyan
    Write-Host "  ======================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   [1] 启动代理与系统代理（日常免提权秒启）" -ForegroundColor Green
    Write-Host "   [2] 停止代理并恢复系统设置（保留证书，免提权）" -ForegroundColor Yellow
    Write-Host "   [3] 仅启动代理（不改系统设置）" -ForegroundColor White
    Write-Host "   [4] 仅停止代理（保留证书，恢复系统代理）" -ForegroundColor White
    Write-Host "   [5] 查看状态 / 连通性测试" -ForegroundColor White
    Write-Host "   [6] 测速（网络出口 + 单/多网络 + 代理对比）" -ForegroundColor White
    Write-Host "   [7] 查看运行日志" -ForegroundColor White
    Write-Host "   [8] 卸载设备根证书（彻底清理）" -ForegroundColor Gray
    Write-Host "   [0] 退出" -ForegroundColor Gray
    Write-Host ""
}

function Show-Status {
    Write-Host ""
    Write-Host "  --- 状态检查（v$Version）---" -ForegroundColor Cyan
    Write-Host ""

    $running = Test-ProxyRunning
    if ($running) {
        Write-Host "  代理进程:   [运行中] 端口 8888" -ForegroundColor Green
        $procs = Get-CimInstance Win32_Process |
            Where-Object {
                (($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and $_.CommandLine -like "*mitm_sni_proxy*") -or
                ($_.Name -eq "toci.exe" -and $_.CommandLine -like "*--proxy*")
            }
        foreach ($p in $procs) {
            $memMB = [math]::Round($p.WorkingSetSize / 1MB, 1)
            Write-Host "               PID $($p.ProcessId)，内存 ${memMB}MB" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  代理进程:   [未运行]" -ForegroundColor Red
        $owner = Get-PortOwner
        if ($owner) {
            Write-Host "  端口占用:   [冲突] 8888 被 $owner 占用，请先关闭该程序" -ForegroundColor Red
        }
    }

    if (Test-CaInstalled) {
        try {
            $ca = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($CaCert)
            Write-Host "  根证书:     [已安装] 指纹 $($ca.Thumbprint) 到期 $($ca.NotAfter.ToString('yyyy-MM-dd'))" -ForegroundColor Green
        } catch {
            Write-Host "  根证书:     [已安装]" -ForegroundColor Green
        }
    } else {
        Write-Host "  根证书:     [未安装]（选 1 会自动初始化并安装）" -ForegroundColor Red
    }

    $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $proxyEnabled = (Get-ItemProperty -Path $reg -Name ProxyEnable -ErrorAction SilentlyContinue).ProxyEnable
    $proxyServer = (Get-ItemProperty -Path $reg -Name ProxyServer -ErrorAction SilentlyContinue).ProxyServer
    if ($proxyEnabled -eq 1) {
        Write-Host "  系统代理:   [开] $proxyServer" -ForegroundColor Green
    } else {
        Write-Host "  系统代理:   [关]" -ForegroundColor DarkGray
    }
    if (Test-Path $ProxyStateFile) {
        Write-Host "  代理备份:   [已保存] 停止时会恢复启动前的设置" -ForegroundColor DarkGray
    }

    $py = Find-Python
    if ($py) {
        Write-Host "  Python:     [正常] $($py.Version)" -ForegroundColor Green
    } else {
        Write-Host "  Python:     [未找到] 需要 3.8+，安装时勾选 Add to PATH" -ForegroundColor Red
    }

    $ossl = Find-OpenSSL
    if ($ossl) {
        Write-Host "  OpenSSL:    [正常] $ossl" -ForegroundColor Green
    } else {
        Write-Host "  OpenSSL:    [未找到] 首次使用/安全升级初始化需要（装 Git for Windows）" -ForegroundColor Yellow
    }

    if (Test-Path $WildcardCert) {
        Write-Host "  通配符证书: [就绪]" -ForegroundColor Green
    } else {
        Write-Host "  通配符证书: [缺失] 选 1 会自动生成" -ForegroundColor Yellow
    }

    Write-Host "  日志文件:   $LogFile" -ForegroundColor DarkGray

    if ($running) {
        Write-Host ""
        Write-Host "  --- 连通性测试 ---" -ForegroundColor Cyan
        $testSites = @(
            @("www.douyin.com", "抖音"),
            @("www.bilibili.com", "B 站"),
            @("www.baidu.com", "百度（对照）")
        )
        foreach ($site in $testSites) {
            $result = curl.exe -s -o NUL -w "%{http_code}" --proxy "http://127.0.0.1:8888" "https://$($site[0])" --max-time 8 -k 2>$null
            if ($result -eq "200" -or $result -eq "302" -or $result -eq "301") {
                Write-Host "  $($site[1]): [通过] HTTP $result" -ForegroundColor Green
            } else {
                Write-Host "  $($site[1]): [失败] $result" -ForegroundColor Red
            }
        }
    }

    Write-Host ""
}

# ---------------- 测速 ----------------
function Test-Speed {
    Write-Host ""
    Write-Host "  --- 测速 ---" -ForegroundColor Cyan
    Write-Host ""

    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
        Write-Host "  [!!] 系统缺少 curl.exe（Windows 10 1803+ 自带），无法测速" -ForegroundColor Red
        return
    }

    $proxy = "http://127.0.0.1:8888"
    $running = Test-ProxyRunning

    # [1/4] network uplinks
    Write-Host "  [1/4] 网络出口检测" -ForegroundColor White
    $uplinks = @(Get-Uplinks)
    if ($uplinks.Count -eq 0) {
        Write-Host "  未检测到可用网络出口" -ForegroundColor Red
    } else {
        Write-Host ("  已连接 {0} 个网络出口：" -f $uplinks.Count) -ForegroundColor Green
        $idx = 1
        foreach ($u in $uplinks) {
            $alias = "-"
            if ($u.Alias) { $alias = $u.Alias }
            Write-Host ("    {0}) {1,-16} {2}" -f $idx, $u.IP, $alias) -ForegroundColor DarkGray
            $idx++
        }
        if ($uplinks.Count -eq 1) {
            Write-Host "  提示：同时连接校园网 + 手机热点/USB 共享，可做多网络叠加对比" -ForegroundColor Yellow
        }
    }
    Write-Host ""

    # [2/4] target latency through the proxy
    if ($running) {
        Write-Host "  [2/4] 目标站点延迟（通过代理）" -ForegroundColor White
        $sites = @(
            @("抖音", "https://www.douyin.com"),
            @("B 站", "https://www.bilibili.com"),
            @("小红书", "https://www.xiaohongshu.com"),
            @("豆包", "https://www.doubao.com")
        )
        foreach ($s in $sites) {
            $r = Invoke-CurlStat -Url $s[1] -Proxy $proxy -MaxTime 12
            if ($r -and ($r.Code -eq "200" -or $r.Code -eq "301" -or $r.Code -eq "302")) {
                Write-Host ("  {0,-6} HTTP {1}  首字节 {2:N2}s  总耗时 {3:N2}s" -f $s[0], $r.Code, $r.FirstByte, $r.Total) -ForegroundColor Green
            } else {
                $code = "超时/失败"
                if ($r) { $code = "HTTP $($r.Code)" }
                Write-Host ("  {0,-6} [失败] {1}" -f $s[0], $code) -ForegroundColor Red
            }
        }
        Write-Host ""
    } else {
        Write-Host "  [2/4] 目标站点延迟：代理未运行，跳过" -ForegroundColor Yellow
        Write-Host ""
    }

    # pick a speed-test mirror
    $mirrors = @(
        "https://mirrors.tuna.tsinghua.edu.cn/ubuntu-releases/22.04/ubuntu-22.04.5-live-server-amd64.iso",
        "https://mirrors.ustc.edu.cn/ubuntu-releases/22.04/ubuntu-22.04.5-live-server-amd64.iso",
        "https://mirrors.aliyun.com/ubuntu-releases/22.04/ubuntu-22.04.5-live-server-amd64.iso"
    )
    $url = $null
    foreach ($m in $mirrors) {
        $probe = Invoke-CurlStat -Url $m -Proxy $null -MaxTime 6 -Head
        if ($probe -and ($probe.Code -eq "200" -or $probe.Code -eq "206")) { $url = $m; break }
    }
    if (-not $url) {
        Write-Host "  [!!] 内置测速地址都连不上，可手动输入一个可下载的大文件 URL" -ForegroundColor Red
        $url = Read-Host "  测速 URL（直接回车跳过）"
        if (-not $url) {
            Write-Host "  已跳过下载测速"
            Write-Host ""
            return
        }
    }

    # [3/4] single vs multi network
    Write-Host "  [3/4] 单网络 / 多网络下载速度（8 秒采样）" -ForegroundColor White
    $single = @()
    foreach ($u in $uplinks) {
        $r = Measure-DownloadSpeed -Url $url -Proxy $null -Seconds 8 -InterfaceIp $u.IP
        if ($r) {
            Write-Host ("    {0,-16} {1,8:N2} MB/s" -f $u.IP, ($r.BytesPerSec / 1MB)) -ForegroundColor Green
            $single += [pscustomobject]@{ IP = $u.IP; Speed = $r.BytesPerSec; Bytes = $r.Bytes }
        } else {
            Write-Host ("    {0,-16} [失败]" -f $u.IP) -ForegroundColor Red
        }
    }

    $best = 0
    $direct = $null
    if ($single.Count -gt 0) {
        $best = ($single | Measure-Object Speed -Maximum).Maximum
        Write-Host ("    单网络最快: {0:N2} MB/s" -f ($best / 1MB)) -ForegroundColor DarkGray
        if ($single.Count -eq 1) {
            # only one uplink: reuse this measurement as the direct baseline
            $direct = [pscustomobject]@{ BytesPerSec = $single[0].Speed; Bytes = $single[0].Bytes }
        }
    }

    if ($uplinks.Count -ge 2) {
        $multi = @(Measure-MultiSpeed -Url $url -Uplinks $uplinks -Seconds 8)
        $total = ($multi | Measure-Object Speed -Sum).Sum
        Write-Host ("    多网络并行合计: {0:N2} MB/s" -f ($total / 1MB)) -ForegroundColor Green
        foreach ($m in $multi) {
            Write-Host ("      {0,-16} {1,8:N2} MB/s" -f $m.Uplink.IP, ($m.Speed / 1MB)) -ForegroundColor DarkGray
        }
        if ($best -gt 0) {
            $gain = [math]::Round(($total - $best) / $best * 100, 0)
            $sign = "+"
            if ($gain -lt 0) { $sign = "" }
            Write-Host ("    多网络 vs 单网络最快: {0}{1}%" -f $sign, $gain) -ForegroundColor DarkGray
        }
    } elseif ($uplinks.Count -eq 1) {
        Write-Host "    只有 1 个网络出口，跳过并行叠加测试" -ForegroundColor DarkGray
    }
    Write-Host ""

    # [4/4] direct vs proxy
    Write-Host "  [4/4] 直连 vs 代理（8 秒采样）" -ForegroundColor White
    if (-not $direct) {
        $direct = Measure-DownloadSpeed -Url $url -Proxy $null -Seconds 8
    }
    if ($direct) {
        Write-Host ("  直连:   {0,8:N2} MB/s   ({1:N1} MB / 8s)" -f ($direct.BytesPerSec / 1MB), ($direct.Bytes / 1MB)) -ForegroundColor Green
    } else {
        Write-Host "  直连:   [失败]" -ForegroundColor Red
    }

    if ($running) {
        $via = Measure-DownloadSpeed -Url $url -Proxy $proxy -Seconds 8
        if ($via) {
            Write-Host ("  代理:   {0,8:N2} MB/s   ({1:N1} MB / 8s)" -f ($via.BytesPerSec / 1MB), ($via.Bytes / 1MB)) -ForegroundColor Green
            if ($direct -and $direct.BytesPerSec -gt 0) {
                $ratio = [math]::Round($via.BytesPerSec / $direct.BytesPerSec * 100, 0)
                Write-Host ("  代理速度是直连的 {0}%" -f $ratio) -ForegroundColor DarkGray
            }
        } else {
            Write-Host "  代理:   [失败]" -ForegroundColor Red
        }
    } else {
        Write-Host "  代理:   代理未运行，跳过" -ForegroundColor DarkGray
    }

    Write-Host ""
}

# ---------------- TUN / VPN 管理 ----------------
function Find-Mihomo {
    $cands = New-Object System.Collections.Generic.List[string]
    $cands.Add((Join-Path $ScriptDir "bin\mihomo.exe"))
    $cands.Add((Join-Path $ScriptDir "bin\verge-mihomo.exe"))
    $cands.Add((Join-Path $ScriptDir "mihomo.exe"))
    $cands.Add("D:\Clash Verge\verge-mihomo.exe")
    $cands.Add("C:\Program Files\Clash Verge\verge-mihomo.exe")
    $cands.Add("C:\Program Files (x86)\Clash Verge\verge-mihomo.exe")
    foreach ($p in $cands) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    foreach ($cmdName in @("mihomo.exe", "verge-mihomo.exe")) {
        $cmd = Get-Command $cmdName -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and (Test-Path $cmd.Source)) { return $cmd.Source }
    }
    return $null
}

function Test-TunRunning {
    if (Test-Path $TunPidFile) {
        $rawPid = (Get-Content $TunPidFile -Raw -ErrorAction SilentlyContinue)
        if ($rawPid -and $rawPid.Trim() -match "^\d+$") {
            $proc = Get-Process -Id ([int]$rawPid.Trim()) -ErrorAction SilentlyContinue
            if ($proc -and -not $proc.HasExited) { return $true }
        }
    }
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { ($_.Name -like "*mihomo*") -and $_.CommandLine -like "*tun_mihomo.yaml*" }
    return ($null -ne $procs)
}

function Stop-Tun {
    Write-Host "  [*] 正在停止 TUN/VPN 服务..." -ForegroundColor Yellow

    if (Test-Path $TunActiveFlag) {
        if (-not (Test-Path $ActiveFlag)) {
            Stop-Watchdog
        }
        Remove-Item $TunActiveFlag -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $ActiveFlag)) {
            Restore-OriginalProxyState
            Refresh-WinINet
            Write-Host "  [OK] 系统代理已恢复为启动前设置" -ForegroundColor Green
        }
    }

    if (Test-Path $TunPidFile) {
        $rawPid = (Get-Content $TunPidFile -Raw -ErrorAction SilentlyContinue)
        if ($rawPid -and $rawPid.Trim() -match "^\d+$") {
            $pidInt = [int]$rawPid.Trim()
            $proc = Get-Process -Id $pidInt -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $pidInt -Force -ErrorAction SilentlyContinue
                Write-Host "  [OK] 已结束 TUN 内核进程 PID $pidInt" -ForegroundColor Green
            }
        }
        Remove-Item $TunPidFile -Force -ErrorAction SilentlyContinue
    }

    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { ($_.Name -like "*mihomo*") -and $_.CommandLine -like "*tun_mihomo.yaml*" }
    if ($procs) {
        foreach ($p in $procs) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  [OK] 已结束 TUN 残留进程 PID $($p.ProcessId)" -ForegroundColor Green
        }
    }

    Start-Sleep -Milliseconds 600
    if (-not (Test-TunRunning)) {
        Write-Host "  [OK] TUN 虚拟网卡已安全关闭" -ForegroundColor Green
        return $true
    }
    Write-Host "  [!!] TUN 进程未能完全退出" -ForegroundColor Red
    return $false
}

function Start-Tun {
    $mihomo = Find-Mihomo
    if (-not $mihomo) {
        Write-Host "  [!!] 未找到 TUN 内核文件 (bin\mihomo.exe)" -ForegroundColor Red
        return $false
    }
    if (-not (Test-Path $TunYamlFile)) {
        Write-Host "  [!!] 未找到 TUN 配置文件：$TunYamlFile，请先在 GUI 中保存配置。" -ForegroundColor Red
        return $false
    }

    New-Item -ItemType Directory -Force -Path $TunStateDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path $TunLogFile) | Out-Null

    Write-Host "  [*] 正在校验 TUN 配置文件..." -ForegroundColor Yellow
    $valOut = & $mihomo -d $TunStateDir -f $TunYamlFile -t 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [!!] TUN 配置校验失败：" -ForegroundColor Red
        $valOut | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
        return $false
    }

    if (Test-TunRunning) {
        Write-Host "  [*] 检测到旧 TUN 实例正在运行，先清理..." -ForegroundColor Yellow
        [void](Stop-Tun)
    }

    $apiPort = 19090
    $mixedPort = 17897
    $setSysProxy = $true
    $serverIp = ""
    $devName = "SNI-Proxy-TUN"
    if (Test-Path $TunConfigFile) {
        try {
            $tc = Get-Content $TunConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($tc.api_port) { $apiPort = [int]$tc.api_port }
            if ($tc.mixed_port) { $mixedPort = [int]$tc.mixed_port }
            if ($null -ne $tc.also_set_sys_proxy) { $setSysProxy = [bool]$tc.also_set_sys_proxy }
            if ($tc.server) { $serverIp = [string]$tc.server }
            if ($tc.device_name) { $devName = [string]$tc.device_name }
        } catch { }
    }

    Remove-Item $TunLogFile, $TunErrFile -Force -ErrorAction SilentlyContinue
    Write-Host "  [*] 正在启动 TUN 内核 ($mihomo)..." -ForegroundColor Yellow
    try {
        $proc = Start-Process -FilePath $mihomo `
            -ArgumentList @("-d", "`"$TunStateDir`"", "-f", "`"$TunYamlFile`"") `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $TunLogFile -RedirectStandardError $TunErrFile
    } catch {
        Write-Host "  [!!] 无法启动 TUN 内核：$($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
    Set-Content -Path $TunPidFile -Value ([string]$proc.Id) -Encoding ASCII

    $ready = $false
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Milliseconds 400
        if ($proc.HasExited) { break }
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $ar = $tcp.BeginConnect("127.0.0.1", $apiPort, $null, $null)
            if ($ar.AsyncWaitHandle.WaitOne(250, $false) -and $tcp.Connected) {
                $tcp.Close()
                $ready = $true
                break
            }
            $tcp.Close()
        } catch { }
    }

    if (-not $ready) {
        Write-Host "  [!!] TUN 启动超时或异常退出，最近日志：" -ForegroundColor Red
        foreach ($f in @($TunErrFile, $TunLogFile)) {
            if ((Test-Path $f) -and (Get-Item $f).Length -gt 0) {
                Get-Content $f -Tail 10 -Encoding UTF8 -ErrorAction SilentlyContinue |
                    ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
            }
        }
        [void](Stop-Tun)
        return $false
    }

    if ($setSysProxy) {
        Stop-Watchdog
        Save-OriginalProxyState
        if (Test-Path $ActiveFlag) {
            Remove-Item $ActiveFlag -Force -ErrorAction SilentlyContinue
        }
        $reg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        Remove-ItemProperty -Path $reg -Name AutoConfigURL -ErrorAction SilentlyContinue
        Set-ItemProperty -Path $reg -Name ProxyServer -Value "127.0.0.1:$mixedPort"
        Set-ItemProperty -Path $reg -Name ProxyEnable -Value 1
        $bypass = "localhost;127.*;10.*;192.168.*;<local>"
        if ($serverIp) { $bypass = "$bypass;$serverIp" }
        Set-ItemProperty -Path $reg -Name ProxyOverride -Value $bypass
        Refresh-WinINet
        Set-Content -Path $TunActiveFlag -Value (Get-Date).ToString("s") -Encoding ASCII
        Start-Watchdog
        Write-Host "  [OK] 系统代理已同步指向 TUN 混合端口 127.0.0.1:$mixedPort（已启用掉线自动恢复直连守护）" -ForegroundColor Green
    }

    Start-Sleep -Milliseconds 500
    $nic = Get-NetAdapter -Name $devName -ErrorAction SilentlyContinue
    if ($nic -and $nic.Status -eq "Up") {
        Write-Host "  [OK] TUN 虚拟网卡 [$devName] 已就绪 (PID $($proc.Id))" -ForegroundColor Green
    } else {
        Write-Host "  [OK] TUN 内核已启动 (PID $($proc.Id))，正在等待虚拟网卡路由接管完成" -ForegroundColor Green
    }
    return $true
}

# ---------------- 启动前恢复 ----------------
if ((Test-Path $ProxyStateFile) -and -not (Test-ProxyRunning) -and -not (Test-TunRunning)) {
    Write-Host ""
    Write-Host "  [恢复] 检测到上次代理异常退出，正在恢复系统代理..." -ForegroundColor Yellow
    Remove-Item $ActiveFlag, $TunActiveFlag -Force -ErrorAction SilentlyContinue
    Stop-Watchdog
    Restore-OriginalProxyState
    Write-Host "  [OK] 已恢复启动前的系统代理设置" -ForegroundColor Green
    Start-Sleep -Seconds 1
}

# ---------------- 非交互模式（GUI 调用，动作与菜单语义一致） ----------------
if ($Action -ne "") {
    switch ($Action.ToLower()) {
        "start-tun" {
            if (-not (Start-Tun)) { Exit-Immediate 1 }
        }
        "stop-tun" {
            if (-not (Stop-Tun)) { Exit-Immediate 1 }
        }
        "restart-tun" {
            [void](Stop-Tun)
            if (-not (Start-Tun)) { Exit-Immediate 1 }
        }
        "start" {
            if (-not (Initialize-Certs)) { Write-Host "  [!!] 设备证书初始化失败"; Exit-Immediate 1 }
            if (-not (Test-CaInstalled)) {
                if (-not (Install-CA)) { Write-Host "  [!!] 根证书安装失败"; Exit-Immediate 1 }
            }
            if (-not (Start-Proxy)) { Write-Host "  [!!] 代理未启动，已跳过系统代理设置"; Exit-Immediate 1 }
            Set-SystemProxy
        }
        "stop" {
            Unset-SystemProxy
            Stop-Proxy
        }
        "restart" {
            Unset-SystemProxy
            Stop-Proxy
            if (-not (Initialize-Certs)) { Write-Host "  [!!] 设备证书初始化失败"; Exit-Immediate 1 }
            if (-not (Test-CaInstalled)) {
                if (-not (Install-CA)) { Write-Host "  [!!] 根证书安装失败"; Exit-Immediate 1 }
            }
            if (-not (Start-Proxy)) { Write-Host "  [!!] 代理未启动"; Exit-Immediate 1 }
            Set-SystemProxy
        }
        "set-proxy" {
            Set-SystemProxy
        }
        "unset-proxy" {
            Unset-SystemProxy
        }
        "start-proxy" {
            if (-not (Initialize-Certs)) { Exit-Immediate 1 }
            if (-not (Start-Proxy)) { Exit-Immediate 1 }
            Write-Host "  [提示] 请手动把浏览器代理设为 127.0.0.1:8888 或使用 PAC 脚本"
        }
        "stop-proxy" {
            Remove-Item $ActiveFlag -Force -ErrorAction SilentlyContinue
            Stop-Watchdog
            Stop-Proxy
            Restore-OriginalProxyState
            Refresh-WinINet
        }
        "restore-proxy" {
            Remove-Item $ActiveFlag -Force -ErrorAction SilentlyContinue
            Stop-Watchdog
            if (Test-Path $ProxyStateFile) {
                Restore-OriginalProxyState
                Refresh-WinINet
                Write-Host "  [OK] 已从备份恢复系统代理设置"
            } else {
                Write-Host "  [!!] 没有可用的系统代理备份，未做任何修改"
                Exit-Immediate 1
            }
        }
        "install-ca" {
            if (-not (Initialize-Certs)) { Exit-Immediate 1 }
            if (-not (Install-CA)) { Exit-Immediate 1 }
        }
        "remove-ca" {
            Remove-CA
        }
        "status" { Show-Status }
        "logs" { Show-Logs }
        default {
            Write-Host "  [!!] 未知 Action: $Action"
            Exit-Immediate 2
        }
    }
    Exit-Immediate 0
}

# ---------------- 主循环 ----------------
while ($true) {
    Show-Menu
    $choice = Read-Host "  请选择 (0-8)"

    switch ($choice) {
        "1" {
            Write-Host ""
            Write-Host "  === 启动 ===" -ForegroundColor Cyan
            if (-not (Initialize-Certs)) {
                Write-Host ""
                Write-Host "  [!!] 设备证书初始化失败，已中止启动" -ForegroundColor Red
                continue
            }
            $caOk = $true
            if (-not (Test-CaInstalled)) {
                $caOk = Install-CA
            }
            if ($caOk) {
                if (Start-Proxy) {
                    Set-SystemProxy
                    Write-Host ""
                    Write-Host "  [完成] 已就绪，打开浏览器访问 douyin.com 试试" -ForegroundColor Green
                } else {
                    Write-Host ""
                    Write-Host "  [!!] 代理没启动，已跳过系统代理设置（避免全部网页打不开）" -ForegroundColor Red
                }
            }
        }
        "2" {
            Write-Host ""
            Write-Host "  === 停止 ===" -ForegroundColor Cyan
            Unset-SystemProxy
            Stop-Proxy
            Write-Host ""
            Write-Host "  [完成] 代理已停止，系统代理已恢复。" -ForegroundColor Green
        }
        "3" {
            Write-Host ""
            Write-Host "  === 仅启动代理 ===" -ForegroundColor Cyan
            if (-not (Initialize-Certs)) {
                Write-Host "  [!!] 设备证书初始化失败，已中止启动" -ForegroundColor Red
                continue
            }
            if (Start-Proxy) {
                Write-Host ""
                Write-Host "  [提示] 请手动把浏览器代理设为 127.0.0.1:8888 或使用 PAC 脚本" -ForegroundColor Yellow
            }
        }
        "4" {
            Write-Host ""
            Write-Host "  === 仅停止代理 ===" -ForegroundColor Cyan
            Remove-Item $ActiveFlag -Force -ErrorAction SilentlyContinue
            Stop-Watchdog
            Stop-Proxy
            Restore-OriginalProxyState
            Refresh-WinINet
            Write-Host "  [OK] 系统代理已恢复" -ForegroundColor Green
        }
        "5" {
            Show-Status
        }
        "6" {
            Test-Speed
        }
        "7" {
            Show-Logs
        }
        "8" {
            Write-Host ""
            Write-Host "  === 卸载设备根证书 ===" -ForegroundColor Cyan
            Remove-CA
        }
        "0" {
            exit
        }
        default {
            Write-Host "  无效选项" -ForegroundColor Red
        }
    }

    if ($choice -ne "0") {
        Write-Host ""
        Write-Host "  按任意键继续..." -ForegroundColor DarkGray
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
}
