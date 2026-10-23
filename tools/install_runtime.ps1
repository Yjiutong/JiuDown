﻿# JiuDown 首次安装（组件优先，离线可用）
#
# 组件包随仓库一起分发在 build_components/，所以克隆下来**断网也能装好**：
#   1) 优先用本地 build_components/manifest.json + 各组件 zip
#   2) 本地没有（例如只下载了源码包）才从 Release 拉
#   3) Release 上也没有组件清单时，回退整包 runtime.zip（约 339MB）
#   4) 顺带把 FFmpeg 精简版放到 runtime\ffmpeg.exe（本地包优先）
#
# 由「首次安装.bat」调用；也可单独在 PowerShell 中执行：
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_runtime.ps1

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$base = 'https://github.com/Yjiutong/JiuDown/releases/download/runtime'
$manifestUrl = "$base/manifest.json"
$runtime = Join-Path $root 'runtime'
$localDir = Join-Path $root 'build_components'

function Test-Installed {
    return (Test-Path (Join-Path $runtime 'python\python.exe'))
}

function Get-LocalManifest {
    $p = Join-Path $localDir 'manifest.json'
    if (Test-Path $p) {
        try { return (Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { }
    }
    return $null
}

function Test-Checksum([string]$path, [string]$expected) {
    if (-not $expected) { return $true }
    return ((Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLower() -eq $expected.ToLower())
}

function Install-Components($manifest, [bool]$fromLocal) {
    $names = @($manifest.components.PSObject.Properties.Name)
    $total = [math]::Round((($manifest.components.PSObject.Properties.Value | Measure-Object -Property size -Sum).Sum) / 1MB, 1)
    $origin = if ($fromLocal) { 'build_components (offline)' } else { 'GitHub Release' }
    Write-Host ("Components: {0}  total ~{1} MB  build {2}" -f $names.Count, $total, $manifest.build)
    Write-Host ("Source: $origin")
    Write-Host ""

    $idx = 0
    foreach ($name in $names) {
        $idx++
        $c = $manifest.components.$name
        $sizeMb = [math]::Round($c.size / 1MB, 1)
        Write-Host ("[{0}/{1}] {2}  {3} MB" -f $idx, $names.Count, $c.file, $sizeMb)

        $zip = Join-Path $localDir $c.file
        if (-not ((Test-Path $zip) -and (Test-Checksum $zip $c.sha256))) {
            if (Test-Path $zip) { Write-Host "  [i] local copy stale, fetching from release" }
            $zip = Join-Path $env:TEMP $c.file
            Invoke-WebRequest -Uri "$base/$($c.file)" -OutFile $zip -UseBasicParsing
        }

        if (-not (Test-Checksum $zip $c.sha256)) {
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
            throw "Checksum mismatch: $($c.file)"
        }

        Expand-Archive -Path $zip -DestinationPath $runtime -Force
        if ($zip.StartsWith($env:TEMP)) { Remove-Item $zip -Force }
    }
}

function Install-FFmpegLite {
    $dest = Join-Path $runtime 'ffmpeg.exe'
    if (Test-Path $dest) { return }

    $zip = Join-Path $localDir 'ffmpeg-lite.zip'
    $tmp = Join-Path $env:TEMP ("jiudown_ffmpeg_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        if (-not (Test-Path $zip)) {
            Write-Host "Fetching ffmpeg-lite.zip from release..."
            $zip = Join-Path $tmp 'ffmpeg-lite.zip'
            Invoke-WebRequest -Uri "$base/ffmpeg-lite.zip" -OutFile $zip -UseBasicParsing
        }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $exe = Get-ChildItem $tmp -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
        if (-not $exe) { Write-Host "[i] ffmpeg.exe not found in package"; return }
        Copy-Item $exe.FullName -Destination $dest -Force
        Write-Host "[OK] ffmpeg (lite) -> runtime\ffmpeg.exe"
    } catch {
        Write-Host "[i] FFmpeg install skipped ($($_.Exception.Message)); the app will retry on first start"
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (Test-Installed) {
    Write-Host "[OK] Runtime already installed: $runtime"
    Install-FFmpegLite
    exit 0
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null

# ---- 1) 本地组件优先 ----
$localManifest = Get-LocalManifest
if ($localManifest -and $localManifest.components) {
    Write-Host "Using bundled components (no download required)..."
    Install-Components $localManifest $true
    if (Test-Installed) {
        Install-FFmpegLite
        Write-Host ""
        Write-Host "[OK] Runtime installed from bundled components."
        exit 0
    }
    throw "Component install finished but python.exe is missing"
}

# ---- 2) Release 上的组件 ----
Write-Host "Fetching component manifest..."
$manifest = $null
try {
    $manifest = Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 60
} catch {
    Write-Host "[i] Component manifest not available ($($_.Exception.Message))"
}

if ($manifest -and $manifest.components) {
    Install-Components $manifest $false
    if (Test-Installed) {
        Install-FFmpegLite
        Write-Host ""
        Write-Host "[OK] Runtime installed from components."
        exit 0
    }
    throw "Component install finished but python.exe is missing"
}

# ---- 3) 回退：整包 ----
Write-Host "Falling back to full runtime.zip (~339 MB)..."
$zip = Join-Path $env:TEMP 'jiudown_runtime.zip'
Invoke-WebRequest -Uri "$base/runtime.zip" -OutFile $zip -UseBasicParsing

$tmp = Join-Path $env:TEMP ("jiudown_rt_" + [guid]::NewGuid().ToString('N'))
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Move-Item -Destination $runtime -Force
Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Installed) {
    Install-FFmpegLite
    Write-Host "[OK] Runtime installed from full package."
    exit 0
}
throw "Runtime install failed"
