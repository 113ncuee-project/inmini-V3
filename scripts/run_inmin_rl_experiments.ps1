# Pass-through launcher. Does not change global execution policy or power settings.
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$runnerPath = Join-Path $projectRoot 'simplified_rapidchiplet/scripts/run_local_rl_diagnostics.py'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Missing .venv/Scripts/python.exe. See docs/LOCAL_RL_EXPERIMENTS_README.md.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -X utf8 $runnerPath @args
    $runnerExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $runnerExitCode
