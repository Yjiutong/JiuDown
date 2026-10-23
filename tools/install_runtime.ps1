# JiuDown 运行时安装（组件优先）
#
# 1) 先读 release 上的 manifest.json，按组件逐个下载（每个 < 100MB，合计约 100MB）
# 2) 清单不可用时，回退下载整包 runtime.zip（约 339MB）
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

function Test-Installed {
    return (Test-Path (Join-Path $runtime 'python\python.exe'))
}

if (Test-Installed) {
    Write-Host "[OK] Runtime already installed: $runtime"
    exit 0
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null

Write-Host "Fetching component manifest..."
$manifest = $null
try {
    $manifest = Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 60
} catch {
    Write-Host "[i] Component manifest not available ($($_.Exception.Message))"
}

if ($manifest -and $manifest.components) {
    $names = @($manifest.components.PSObject.Properties.Name)
    $total = [math]::Round((($manifest.components.PSObject.Properties.Value | Measure-Object -Property size -Sum).Sum) / 1MB, 1)
    Write-Host ("Components: {0}  total ~{1} MB  build {2}" -f $names.Count, $total, $manifest.build)
    Write-Host ""

    $idx = 0
    foreach ($name in $names) {
        $idx++
        $c = $manifest.components.$name
        $sizeMb = [math]::Round($c.size / 1MB, 1)
        Write-Host ("[{0}/{1}] {2}  {3} MB" -f $idx, $names.Count, $c.file, $sizeMb)

        $zip = Join-Path $env:TEMP $c.file
        Invoke-WebRequest -Uri "$base/$($c.file)" -OutFile $zip -UseBasicParsing

        if ($c.sha256) {
            $h = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
            if ($h -ne $c.sha256.ToLower()) {
                Remove-Item $zip -Force -ErrorAction SilentlyContinue
                throw "Checksum mismatch: $($c.file)"
            }
        }

        Expand-Archive -Path $zip -DestinationPath $runtime -Force
        Remove-Item $zip -Force
    }

    if (Test-Installed) {
        Write-Host ""
        Write-Host "[OK] Runtime installed from components."
        exit 0
    }
    throw "Component install finished but python.exe is missing"
}

# ---- 回退：整包 ----
Write-Host "Falling back to full runtime.zip (~339 MB)..."
$zip = Join-Path $env:TEMP 'jiudown_runtime.zip'
Invoke-WebRequest -Uri "$base/runtime.zip" -OutFile $zip -UseBasicParsing

$tmp = Join-Path $env:TEMP ("jiudown_rt_" + [guid]::NewGuid().ToString('N'))
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = Get-ChildItem $tmp -Directory | Select-Object -First 1
Get-ChildItem $src.FullName -Force | Move-Item -Destination $runtime -Force
Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Installed) {
    Write-Host "[OK] Runtime installed from full package."
    exit 0
}
throw "Runtime install failed"
