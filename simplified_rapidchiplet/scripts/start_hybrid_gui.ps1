param([int]$Port = 8765, [string]$Out = 'simplified_rapidchiplet\results\gemini_rl')
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$guiPath = Join-Path $projectRoot 'simplified_rapidchiplet\hybrid_gui.py'
$outputPath = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path $projectRoot $Out }
& $pythonPath -X utf8 $guiPath --port $Port --out $outputPath
