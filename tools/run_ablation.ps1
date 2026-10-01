<#
.SYNOPSIS
  Run the full 2x2 ablation (injection x attribution prompts) for N seeds.

.DESCRIPTION
  Sequential, unattended. Each cell gets the same framing, step count, and model,
  so the only things that vary across the batch are the two factors under study
  plus the seed label. Every run is logged and registered automatically.

  Order is interleaved by seed (seed 1 across all four cells, then seed 2, ...)
  so a batch that gets interrupted still has balanced partial coverage rather
  than four completed cells and one empty.

  Rough cost: ~12 min per 100-step run on this machine, so 4 cells x N seeds is
  about N * 48 minutes. Verify Ollama is up first: the launcher aborts if not.

.PARAMETER Seeds
  Comma-separated seed labels. Seeds are labels only - the local model is
  sampled, not seeded deterministically, so a different label does not give a
  reproducible run. Replicates are independent draws.

.EXAMPLE
  .\tools\run_ablation.ps1 -Seeds 1,2,3 -Steps 100

.EXAMPLE
  # quick structural check first, all four cells
  .\tools\run_ablation.ps1 -Seeds 1 -Steps 10
#>
[CmdletBinding()]
param(
  [string]$Seeds = '1,2,3',
  [int]$Steps = 100,
  [ValidateSet('explicit_unfair', 'merit_ambiguous')][string]$Framing = 'merit_ambiguous',
  [string]$Origin = 'base_the_ville_isabella_maria_klaus',
  [int]$ImportanceTriggerMax = 40,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'run_experiment.ps1'
$seedList = $Seeds.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }

try {
  $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
} catch {
  throw "Ollama is not reachable on 127.0.0.1:11434. Start it first: ollama serve"
}

$plan = @()
foreach ($seed in $seedList) {
  foreach ($inj in 0, 1) {
    foreach ($prm in 0, 1) {
      $plan += [pscustomobject]@{
        RunId     = "abl_i${inj}_p${prm}_s${seed}"
        Condition = if ($inj) { 'treatment' } else { 'control' }
        Prompts   = if ($prm) { 'attribution' } else { 'baseline' }
        Seed      = $seed
      }
    }
  }
}

Write-Host ''
Write-Host "Ablation plan: $($plan.Count) run(s), $Steps steps, framing=$Framing, reflect_trigger_max=$ImportanceTriggerMax" -ForegroundColor Cyan
Write-Host ''
$plan | Format-Table -AutoSize | Out-String | Write-Host

if ($DryRun) {
  Write-Host 'Dry run: nothing launched.' -ForegroundColor Yellow
  return
}

$results = @()
$index = 0
foreach ($job in $plan) {
  $index++
  Write-Host ''
  Write-Host ("=" * 70) -ForegroundColor DarkGray
  Write-Host "[$index/$($plan.Count)] $($job.RunId)" -ForegroundColor Cyan
  Write-Host ("=" * 70) -ForegroundColor DarkGray

  & $launcher -RunId $job.RunId -Condition $job.Condition -Prompts $job.Prompts `
      -Framing $Framing -Steps $Steps -Seed $job.Seed -Origin $Origin `
      -ImportanceTriggerMax $ImportanceTriggerMax
  $code = $LASTEXITCODE

  $results += [pscustomobject]@{
    RunId = $job.RunId
    Exit  = $code
  }

  if ($code -ne 0) {
    Write-Warning "$($job.RunId) exited $code - continuing with the rest of the plan"
  }
}

Write-Host ''
Write-Host 'Batch summary' -ForegroundColor Cyan
$results | Format-Table -AutoSize | Out-String | Write-Host
$failed = @($results | Where-Object { $_.Exit -ne 0 })
if ($failed.Count -gt 0) {
  Write-Warning "$($failed.Count) run(s) failed: $($failed.RunId -join ', ')"
}

Write-Host ''
Write-Host 'Score the batch:' -ForegroundColor Cyan
Write-Host "  .\.venv311\Scripts\python.exe analysis\evaluate_runs.py --cells"
Write-Host ''