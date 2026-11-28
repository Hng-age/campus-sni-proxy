"""GitHub release updater: check, download, stage and apply in place.

The GUI only needs :func:`fetch_latest` for the check and
:func:`download_and_stage` + :func:`apply_update` for the one-click update.
Everything here is Qt-free so it can be unit tested without PySide6.
"""

import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from sni_proxy import config

GITHUB_REPO = "Hng-age/campus-sni-proxy"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
API_HEADERS = {
    "User-Agent": f"toci-updater/{config.VERSION}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
REQUIRED_FILES = ("toci.exe", "proxy_manager.ps1",
                  os.path.join("sni_proxy", "server.py"))


class UpdateError(RuntimeError):
    """Raised when the release cannot be checked, downloaded or staged."""


# ----------------------------------------------------------------------
# Version helpers
# ----------------------------------------------------------------------
def parse_version(text):
    """'v3.5.1' -> (3, 5, 1); empty/invalid -> ()."""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:4]) if nums else ()


def is_newer(remote, local=None):
    """True when *remote* is a strictly newer version than *local*."""
    return parse_version(remote) > parse_version(local or config.VERSION)


# ----------------------------------------------------------------------
# HTTP helpers (direct first, local toci proxy as fallback)
# ----------------------------------------------------------------------
def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _opener(use_proxy):
    handlers = [urllib.request.HTTPSHandler(context=_ssl_context())]
    if use_proxy:
        proxy = f"http://127.0.0.1:{config.LISTEN_PORT}"
        handlers.append(urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def _open_url(url, timeout, use_proxy, headers=None):
    req = urllib.request.Request(url, headers=headers or API_HEADERS)
    return _opener(use_proxy).open(req, timeout=timeout)


def _request_json(url, timeout=10):
    errors = []
    for use_proxy in (False, True):
        try:
            with _open_url(url, timeout, use_proxy) as resp:
                return json.loads(resp.read(2 * 1024 * 1024).decode("utf-8"))
        except Exception as e:      # noqa: BLE001 - try the other route
            errors.append(f"{'代理' if use_proxy else '直连'}: {e}")
    raise UpdateError("无法连接 GitHub（" + "；".join(errors) + "）")


def pick_asset(assets, version):
    """Choose the portable zip that matches *version*."""
    zips = [a for a in assets or []
            if str(a.get("name", "")).lower().endswith(".zip")]
    wanted = f"toci-{version}-portable.zip".lower()
    for a in zips:
        if str(a.get("name", "")).lower() == wanted:
            return a
    for a in zips:
        name = str(a.get("name", "")).lower()
        if name.startswith("toci-") and "portable" in name:
            return a
    return zips[0] if zips else None


def fetch_latest(timeout=10):
    """Return release info for the newest GitHub release.

    Raises :class:`UpdateError` when the API is unreachable or the release
    has no portable zip attached.
    """
    data = _request_json(API_LATEST, timeout=timeout)
    tag = str(data.get("tag_name") or data.get("name") or "")
    version = ".".join(str(n) for n in parse_version(tag))
    if not version:
        raise UpdateError("无法解析最新版本号")
    asset = pick_asset(data.get("assets") or [], version)
    if asset is None:
        raise UpdateError("最新版本未附带 portable 压缩包")
    return {
        "version": version,
        "tag": tag,
        "name": data.get("name") or f"toci v{version}",
        "notes": data.get("body") or "",
        "published_at": data.get("published_at") or "",
        "asset_name": asset.get("name") or f"toci-{version}-portable.zip",
        "asset_url": asset.get("browser_download_url")
                     or asset.get("url") or "",
        "asset_size": int(asset.get("size") or 0),
        "asset_digest": asset.get("digest") or "",
    }


# ----------------------------------------------------------------------
# Download + extract
# ----------------------------------------------------------------------
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(512 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_asset_url(url):
    """Allow only HTTPS downloads from GitHub release hosts."""
    from urllib.parse import urlparse
    p = urlparse(str(url or "").strip())
    host = (p.hostname or "").lower()
    allowed = (
        host == "github.com"
        or host == "api.github.com"
        or host.endswith(".githubusercontent.com")
    )
    if p.scheme != "https" or not allowed:
        raise UpdateError(f"更新地址不受信任，已拒绝下载：{url}")


def _download_stream(info, dest, use_proxy, on_progress=None,
                     should_cancel=None):
    url = info["asset_url"]
    _validate_asset_url(url)
    total = int(info.get("asset_size") or 0)
    headers = dict(API_HEADERS)
    headers["Accept"] = "application/octet-stream"
    done = 0
    with _open_url(url, 30, use_proxy=use_proxy, headers=headers) as resp, \
            open(dest, "wb") as f:
        try:
            total = int(resp.headers.get("Content-Length") or total or 0)
        except (TypeError, ValueError):
            pass
        if on_progress:
            on_progress(0, total, "download")
        while True:
            if should_cancel and should_cancel():
                raise UpdateError("已取消")
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total, "download")


def download(info, dest, on_progress=None, should_cancel=None):
    """Download the release asset, trying direct and then the local proxy."""
    errors = []
    for use_proxy in (False, True):
        try:
            _download_stream(info, dest, use_proxy, on_progress, should_cancel)
            break
        except UpdateError:
            raise
        except Exception as e:      # noqa: BLE001 - try the other route
            errors.append(f"{'代理' if use_proxy else '直连'}: {e}")
            try:
                if os.path.exists(dest):
                    os.remove(dest)
            except OSError:
                pass
    else:
        raise UpdateError("下载更新失败（" + "；".join(errors) + "）")

    digest = str(info.get("asset_digest") or "").strip()
    if not digest.lower().startswith("sha256:"):
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        raise UpdateError("发布包缺少 SHA256 校验摘要，已终止更新")
    expected = digest.split(":", 1)[1].strip().lower()
    actual = _sha256(dest).lower()
    if not expected or actual != expected:
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        raise UpdateError("更新包校验失败（SHA256 不匹配），已终止")


def _safe_extract(zip_path, dest_dir):
    root = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = os.path.abspath(os.path.join(root, member.filename))
            if os.path.commonpath([root, target]) != root:
                raise UpdateError("更新包包含非法路径，已终止")
        zf.extractall(dest_dir)


def find_app_root(directory):
    """Locate the folder that contains toci.exe (zip root may wrap it)."""
    if os.path.isfile(os.path.join(directory, "toci.exe")):
        return directory
    entries = [os.path.join(directory, n) for n in os.listdir(directory)]
    dirs = [p for p in entries if os.path.isdir(p)]
    if len(dirs) == 1 and os.path.isfile(os.path.join(dirs[0], "toci.exe")):
        return dirs[0]
    return None


def download_and_stage(info, on_progress=None, should_cancel=None):
    """Download and extract the release; return staging metadata."""
    work_dir = tempfile.mkdtemp(prefix="toci_update_")
    zip_path = os.path.join(work_dir, info.get("asset_name")
                            or "toci-portable.zip")
    try:
        download(info, zip_path, on_progress, should_cancel)
        if on_progress:
            on_progress(1, 1, "extract")
        new_dir = os.path.join(work_dir, "new")
        os.makedirs(new_dir, exist_ok=True)
        _safe_extract(zip_path, new_dir)
        app_root = find_app_root(new_dir)
        if app_root is None:
            raise UpdateError("更新包结构异常：未找到 toci.exe")
        missing = [name for name in REQUIRED_FILES
                   if not os.path.isfile(os.path.join(app_root, name))]
        if missing:
            raise UpdateError("更新包缺少必要文件：" + "、".join(missing))
        return {
            "work_dir": work_dir,
            "zip_path": zip_path,
            "app_root": app_root,
            "version": info.get("version", ""),
        }
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


# ----------------------------------------------------------------------
# Apply in place
# ----------------------------------------------------------------------
UPDATER_SCRIPT = r"""param(
  [Parameter(Mandatory=$true)][string]$AppDir,
  [Parameter(Mandatory=$true)][string]$SrcDir,
  [int]$WaitPid = 0,
  [string]$ExeName = "toci.exe",
  [string]$LogFile = "",
  [switch]$NoStart
)
$ErrorActionPreference = "Continue"
function Write-Log([string]$msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  if ($LogFile) { Add-Content -Path $LogFile -Value $line -Encoding UTF8 }
}
Write-Log "update start: src=$SrcDir app=$AppDir"
if ($WaitPid -gt 0) {
  try {
    Wait-Process -Id $WaitPid -Timeout 180 -ErrorAction Stop
    Write-Log "waited for pid $WaitPid"
  } catch {
    Write-Log "wait for pid $WaitPid failed: $($_.Exception.Message)"
  }
  Start-Sleep -Milliseconds 700
}
if (-not (Test-Path (Join-Path $SrcDir $ExeName))) {
  Write-Log "source exe missing, abort"
  exit 2
}
$restartProxy = $false
try {
  $appNorm = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\')
  $proxyProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq $ExeName -and $_.CommandLine -like "*--proxy*" -and $_.ExecutablePath -and ([System.IO.Path]::GetDirectoryName($_.ExecutablePath).TrimEnd('\') -eq $appNorm)
  }
  foreach ($pp in $proxyProcs) {
    Stop-Process -Id $pp.ProcessId -Force -ErrorAction SilentlyContinue
    $restartProxy = $true
    Write-Log "stopped headless proxy pid $($pp.ProcessId)"
  }
  if ($restartProxy) { Start-Sleep -Milliseconds 500 }
} catch { }
if (Test-Path (Join-Path $SrcDir "_internal")) {
  $oldInternal = Join-Path $AppDir "_internal"
  if (Test-Path $oldInternal) {
    Remove-Item $oldInternal -Recurse -Force -ErrorAction SilentlyContinue
    Write-Log "cleaned old _internal"
  }
}
foreach ($stale in @("config.py", "rules_manager.py", "server.py")) {
  $sp = Join-Path $AppDir $stale
  if (Test-Path $sp) {
    Remove-Item $sp -Force -ErrorAction SilentlyContinue
    Write-Log "removed stale top-level $stale"
  }
}
$excludeFiles = @("rules.json", "tun_config.json")
$excludeDirs = @("logs", "state", "mitm_certs", "__pycache__")
$copyArgs = @($SrcDir, $AppDir, "/E", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
$copyArgs += "/XD"
$copyArgs += $excludeDirs
$copyArgs += "/XF"
$copyArgs += $excludeFiles
& robocopy @copyArgs | Out-Null
$code = $LASTEXITCODE
Write-Log "robocopy exit=$code"
foreach ($f in $excludeFiles) {
  $dst = Join-Path $AppDir $f
  if (-not (Test-Path $dst)) {
    $src = Join-Path $SrcDir $f
    if (Test-Path $src) {
      Copy-Item $src $dst -Force
      Write-Log "created default $f"
    }
  }
}
Write-Log "files copied"
if (-not $NoStart) {
  $exe = Join-Path $AppDir $ExeName
  if (Test-Path $exe) {
    if ($restartProxy) {
      Start-Process -FilePath $exe -ArgumentList "--proxy" -WorkingDirectory $AppDir -WindowStyle Hidden
      Write-Log "restarted headless proxy $exe"
    }
    Start-Process -FilePath $exe -WorkingDirectory $AppDir
    Write-Log "restarted $exe"
  } else {
    Write-Log "target exe missing, abort restart"
    exit 3
  }
}
Write-Log "update done"
"""


def apply_update(app_root, app_dir, wait_pid=None, work_dir=None,
                 exe_name="toci.exe"):
    """Spawn a detached updater and return the log path.

    The caller must quit the GUI right after calling this; the script waits
    for *wait_pid* to exit before replacing files.
    """
    work_dir = work_dir or tempfile.mkdtemp(prefix="toci_apply_")
    script_path = os.path.join(work_dir, "apply_update.ps1")
    log_path = os.path.join(work_dir, "update.log")
    with open(script_path, "w", encoding="utf-8-sig") as f:
        f.write(UPDATER_SCRIPT)
    cmd = [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", script_path,
        "-AppDir", app_dir,
        "-SrcDir", app_root,
        "-WaitPid", str(int(wait_pid or 0)),
        "-ExeName", exe_name,
        "-LogFile", log_path,
    ]
    subprocess.Popen(cmd, close_fds=True, creationflags=config.NO_WINDOW)
    return log_path
