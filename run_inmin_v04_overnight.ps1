[CmdletBinding()]
param(
    [string[]]$Models = @('resnet18'),
    [int[]]$Seeds = @(7, 17, 37),
    [ValidateRange(4, 1000000)][int]$Queries = 256,
    [ValidateRange(1, 604800)][int]$SecondsPerMethod = 3600,
    [ValidateRange(1, 86400)][int]$EvaluationTimeout = 300,
    [ValidateSet('balanced', 'edp', 'latency', 'energy')][string]$Objective = 'balanced',
    [ValidateSet('guided', 'generic')][string]$Generator = 'guided',
    [ValidateSet('on', 'off')][string]$BottleneckFeatures = 'on',
    [switch]$NoInner,
    [string]$Methods = 'replay_rl,random,sa',
    [string]$OutputRoot = 'output/replay_v04_overnight',
    [switch]$Resume,
    [switch]$KeepAwake,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Runner = Join-Path $ProjectRoot 'simplified_rapidchiplet\replay_mapping_dse.py'
$Analyzer = Join-Path $ProjectRoot 'simplified_rapidchiplet\scripts\analyze_replay_mapping.py'
$OutputPath = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutputRoot))
if (-not (Test-Path -LiteralPath $Python)) { throw "Python environment missing: $Python" }
if (-not (Test-Path -LiteralPath $Runner)) { throw "Runner missing: $Runner" }
if (-not $OutputPath.StartsWith($ProjectRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputRoot must stay inside this project. Use a new versioned folder.'
}
foreach ($method in $Methods.Split(',')) {
    if ($method -notin @('replay_rl', 'random', 'sa', 'greedy')) { throw "Unknown method: $method" }
}

function Get-SeedCase([string]$Model) {
    $portable = Join-Path $ProjectRoot "inputs\replay_v04\$Model"
    if (Test-Path -LiteralPath (Join-Path $portable 'seed_attempts.json')) { return $portable }
    if ($Model -eq 'resnet18') {
        return (Join-Path $ProjectRoot 'output\local_rl_v03_r18\cases\resnet18\7\methods')
    }
    if ($Model -in @('resnet50','mobilenet_v2')) {
        return (Join-Path $ProjectRoot "output\local_rl_v03_p4\cases\$Model\7\methods")
    }
    throw "Unknown model or missing portable seed input: $Model"
}

function Run-Checked([string[]]$Arguments) {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Experiment stopped/failed (exit $LASTEXITCODE). Read runner.log and status.json. Remaining cases were not launched." }
}

function Get-SourceIdentity {
    $scripts = Join-Path $ProjectRoot 'simplified_rapidchiplet\scripts'
    $identity = & $Python -c 'import sys; sys.path.insert(0,sys.argv[1]); from run_local_rl_diagnostics import sources,sha; print(sha(sources()))' $scripts
    if ($LASTEXITCODE -ne 0) { throw 'Could not hash experiment sources.' }
    return ([string]$identity).Trim()
}

$SourceIdentity = Get-SourceIdentity
$WrapperIdentity = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
$ProtocolFile = Join-Path $OutputPath 'overnight_protocol.json'
if ((Test-Path -LiteralPath $ProtocolFile) -and $Resume) {
    $saved = Get-Content -LiteralPath $ProtocolFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($saved.source_identity -ne $SourceIdentity) { throw 'Live source differs from the overnight cohort. Individual completed/incomplete cases retain frozen code and can be resumed with the Python CLI; use a new OutputRoot for a new cohort.' }
    if ($saved.wrapper_identity -ne $WrapperIdentity) { throw 'Overnight wrapper differs from the saved protocol. Resume individual frozen cases or use a new OutputRoot.' }
    $Models = @($saved.models)
    $Seeds = @($saved.seeds)
    $Queries = [int]$saved.queries
    $SecondsPerMethod = [int]$saved.seconds_per_method
    $EvaluationTimeout = [int]$saved.evaluation_timeout
    $Objective = [string]$saved.objective
    $Methods = [string]$saved.methods
    $Generator = [string]$saved.generator
    $BottleneckFeatures = [string]$saved.bottleneck_features
    $NoInner = [bool]$saved.no_inner
} elseif (Test-Path -LiteralPath $ProtocolFile) {
    throw 'An overnight protocol already exists. Use -Resume or a new OutputRoot.'
} elseif (-not $DryRun) {
    New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
    @{source_identity=$SourceIdentity; wrapper_identity=$WrapperIdentity; models=$Models; seeds=$Seeds; queries=$Queries;
      seconds_per_method=$SecondsPerMethod; evaluation_timeout=$EvaluationTimeout;
      objective=$Objective; methods=$Methods; generator=$Generator;
      bottleneck_features=$BottleneckFeatures; no_inner=[bool]$NoInner} | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $ProtocolFile -Encoding UTF8
}

Write-Host "INMIN v0.4: methods=$Methods, queries=$Queries, seconds/method=$SecondsPerMethod"
Write-Host 'Each RNG seed uses the SAME fixed best Tangram-style seed for its model.'
Write-Host 'No cloud model, Codex quota, network access or recurring automation is used.'
$awake = $false
try {
    if ($KeepAwake -and -not $DryRun) {
        if (-not ('InminPower' -as [type])) {
            Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public static class InminPower { [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags); }'
        }
        if ([InminPower]::SetThreadExecutionState([uint32]2147483649) -eq 0) { throw 'Windows rejected temporary sleep prevention.' }
        $awake = $true
    }
    foreach ($model in $Models) {
        $seedCase = Get-SeedCase $model
        foreach ($name in @('seed_attempts.json', 'workload.json', 'source_identity.json')) {
            if (-not (Test-Path -LiteralPath (Join-Path $seedCase $name))) { throw "Missing seed input: $seedCase\$name" }
        }
        foreach ($rng in $Seeds) {
            if ((Get-SourceIdentity) -ne $SourceIdentity) { throw 'Sources changed during the queue. Current frozen case is preserved; refusing to mix source versions in later cases.' }
            $out = Join-Path $OutputPath "$model\$rng"
            $config = Join-Path $out 'effective_config.json'
            if (Test-Path -LiteralPath $config) {
                if (-not $Resume) { throw "Output already exists: $out. Use -Resume or a different OutputRoot." }
                $argv = @('-u','-X','utf8',$Runner,'--resume','--out',$out)
            } else {
                $argv = @('-u','-X','utf8',$Runner,'--seed-case',$seedCase,'--out',$out,
                    '--methods',$Methods,'--seed',"$rng",'--queries',"$Queries",'--seconds',"$SecondsPerMethod",
                    '--eval-timeout',"$EvaluationTimeout",'--objective',$Objective,'--generator',$Generator,
                    '--bottleneck-features',$BottleneckFeatures,'--save-candidate-sets')
                if ($NoInner) { $argv += '--no-inner' }
            }
            Write-Host "Model=$model RNG=$rng Output=$out"
            if ($DryRun) {
                Write-Host ('Python arguments: ' + ($argv -join ' '))
                continue
            }
            Run-Checked $argv
            Run-Checked @('-X','utf8',$Analyzer,'--out',$out)
        }
    }
    if ($DryRun) {
        Write-Host 'Dry run finished. No PPA was started.'
    } else {
        Write-Host 'Requested cases completed. Read each analysis\ANALYSIS.md and comparison.csv.'
    }
} finally {
    if ($awake) { [InminPower]::SetThreadExecutionState([uint32]2147483648) | Out-Null }
}
