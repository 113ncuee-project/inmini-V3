$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

$RepoRoot = Split-Path -Parent $ProjectRoot
$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Python = if (Test-Path -LiteralPath $VenvPython) { Get-Command $VenvPython } else { Get-Command python -ErrorAction SilentlyContinue }
$UsePyLauncher = $false

if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    $UsePyLauncher = $true
}

if (-not $Python) {
    throw "找不到 Python。請先安裝 Python 3.10 以上，或確認 python/py 已加入 PATH。"
}

if ($UsePyLauncher) {
    & $Python.Source -3 .\run.py --models resnet50 --preference balanced --budget 64 --out .\results\demo
} else {
    & $Python.Source .\run.py --models resnet50 --preference balanced --budget 64 --out .\results\demo
}
if ($LASTEXITCODE -ne 0) { throw 'DSE 執行失敗，請查看上方訊息。' }

Write-Host ""
Write-Host "完成。請打開 results\demo\report.html 查看報告。"
