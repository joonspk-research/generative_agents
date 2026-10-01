<#
.SYNOPSIS
  Launch a just-world Generative Agents run headlessly and log it to the registry.

.DESCRIPTION
  Wraps reverie.py's non-interactive mode so every run has the same env vars,
  the same interpreter, a captured log, and a registry row. Intended for A/B
  cells, so the only things that vary between runs are the ones you pass in.

  The Django frontend server is NOT required. Do not start it.

.EXAMPLE
  .\tools\run_experiment.ps1 -RunId abl_inj1_prm1_s1 -Condition treatment -Prompts attribution -Steps 100 -Seed 1

.EXAMPLE
  # run the full 2x2 for one seed
  foreach ($inj in 0,1) { foreach ($prm in 0,1) {
    $c = if ($inj) { 'treatment' } else { 'control' }
    $p = if ($prm) { 'attribution' } else { 'baseline' }
    .\tools\run_experiment.ps1 -RunId "abl_i${inj}_p${prm}_s1" -Condition $c -Prompts $p -Steps 100 -Seed 1
  }}
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$RunId,
  [ValidateSet('control', 'treatment')][string]$Condition = 'treatment',
  [ValidateSet('baseline', 'attribution')][string]$Prompts = 'attribution',
  [ValidateSet('explicit_unfair', 'merit_ambiguous')][string]$Framing = 'merit_ambiguous',
  [int]$Steps = 100,
  [string]$Seed = 'a',
  [string]$Origin = 'base_the_ville_isabella_maria_klaus',
  [int]$ImportanceTriggerMax = 0,
  [string]$Python = '',
  [switch]$SkipRegistry
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $repoRoot '.venv311\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) {
  throw "interpreter not found: $Python`nCreate it with: py -3.11 -m venv .venv311; .\.venv311\Scripts\pip install openai==0.27.0 'numpy<2'"
}

# --- preflight ------------------------------------------------------------
try {
  $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw "Ollama is not reachable on 127.0.0.1:11434. Start it first: ollama serve"
}

$runFolder = Join-Path $repoRoot "environment\frontend_server\storage\$RunId"
if (Test-Path -LiteralPath $runFolder) {
  throw "run folder already exists: $runFolder`nPick a different -RunId or delete it first."
}

$logDir = Join-Path $repoRoot 'runs\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir "$RunId.log"
$errFile = Join-Path $logDir "$RunId.err.log"

# --- experiment env -------------------------------------------------------
$env:JW_EXPERIMENT = if ($Condition -eq 'treatment') { '1' } else { '0' }
$env:JW_ATTRIBUTION_PROMPTS = if ($Prompts -eq 'attribution') { '1' } else { '0' }
$env:JW_FRAMING = $Framing

# Reflection only fires once the accumulated importance of perceived events
# exhausts importance_trigger_max (upstream default 150). At the default the
# observer reflects roughly once per 100 steps, which is far too few insights to
# compare conditions. Override it to raise the reflection rate; keep the value
# IDENTICAL across every cell of an ablation so it is not itself a confound.
if ($ImportanceTriggerMax -gt 0) {
  $env:JW_IMPORTANCE_TRIGGER_MAX = "$ImportanceTriggerMax"
} else {
  # Clear it explicitly. run_ablation.ps1 calls this script in-process, so
  # without this an omitted -ImportanceTriggerMax would silently inherit the
  # previous cell's value and quietly make the cadence a confound.
  Remove-Item Env:JW_IMPORTANCE_TRIGGER_MAX -ErrorAction SilentlyContinue
}
$triggerNote = if ($env:JW_IMPORTANCE_TRIGGER_MAX) { $env:JW_IMPORTANCE_TRIGGER_MAX } else { '150 (upstream default)' }

Write-Host ''
Write-Host '=== just-world run ===' -ForegroundColor Cyan
Write-Host "  run_id     : $RunId"
Write-Host "  condition  : $Condition  (JW_EXPERIMENT=$($env:JW_EXPERIMENT))"
Write-Host "  prompts    : $Prompts  (JW_ATTRIBUTION_PROMPTS=$($env:JW_ATTRIBUTION_PROMPTS))"
Write-Host "  framing    : $Framing"
Write-Host "  steps      : $Steps"
Write-Host "  seed       : $Seed"
Write-Host "  reflect@   : $triggerNote"
Write-Host "  interpreter: $Python"
Write-Host "  log        : $($logFile.Substring($repoRoot.Length + 1))"
Write-Host ''

$backend = Join-Path $repoRoot 'reverie\backend_server\reverie.py'
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# A crashing simulation writes a Python traceback to stderr. With
# $ErrorActionPreference = 'Stop' that becomes a terminating NativeCommandError,
# which would abort this script before the registry row and the traceback copy
# were written. Relax the preference for the duration of the run only, and keep
# stderr in its own file so the traceback survives.
$prevErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
Push-Location (Join-Path $repoRoot 'reverie\backend_server')
try {
  & $Python $backend --origin $Origin --target $RunId --run-steps $Steps `
      --offline-auto-advance --save-and-exit 2> $errFile | Tee-Object -FilePath $logFile
  $exit = $LASTEXITCODE
} finally {
  Pop-Location
  $ErrorActionPreference = $prevErrorActionPreference
  $sw.Stop()
}

$elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)
Write-Host ''
Write-Host "exit=$exit  elapsed=${elapsed}s" -ForegroundColor Yellow
if ($exit -ne 0) {
  Write-Host "run FAILED - traceback (if any) in $($errFile.Substring($repoRoot.Length + 1)):" -ForegroundColor Red
  if (Test-Path -LiteralPath $errFile) { Get-Content -LiteralPath $errFile | Select-Object -Last 40 | Write-Host }
}

# --- registry -------------------------------------------------------------
if (-not $SkipRegistry) {
  $status = if ($exit -eq 0) { 'completed' } else { 'failed' }
  & $Python (Join-Path $repoRoot 'tools\registry.py') add `
      --run-id $RunId `
      --injection $(if ($Condition -eq 'treatment') { 1 } else { 0 }) `
      --prompts $(if ($Prompts -eq 'attribution') { 1 } else { 0 }) `
      --framing $Framing `
      --steps $Steps `
      --seed $Seed `
      --status $status `
      --artifacts-present $(if ($exit -eq 0) { 1 } else { 0 }) `
      --notes "launched by tools/run_experiment.ps1, ${elapsed}s wall clock, exit=$exit, reflect_trigger_max=$triggerNote, log=runs/logs/$RunId.log" `
      --defaults-model --allow-create
}

Write-Host ''
Write-Host 'Next:' -ForegroundColor Cyan
Write-Host "  .\.venv311\Scripts\python.exe analysis\evaluate_runs.py --run-id $RunId --cells"
Write-Host ''
exit $exit