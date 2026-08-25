[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$PrivateRoot,
  [Parameter(Mandatory = $true)][ValidateSet('calibration', 'validation', 'unseen')][string]$Split,
  [string]$Seeds = '53',
  [ValidateSet('full_plan', 'short_horizon', 'next_action')][string]$Mode = 'full_plan',
  [string]$Model = 'ollama',
  [int]$OrderSeed = 20260825,
  [string]$Resume = '',
  [switch]$DryRun,
  [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $PythonPath) { $PythonPath = Join-Path $Root '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Python não encontrado: $PythonPath" }

$logRoot = Join-Path $Root 'data\artifacts\research\general_reasoning_v1\launcher_logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logPath = Join-Path $logRoot ("pair_{0}_{1}.log" -f $Split, $stamp)
$errorPath = "$logPath.err"
$pidPath = "$logPath.pid.json"

function Quote-Argument([string]$Value) {
  return '"' + $Value.Replace('"', '\"') + '"'
}

$arguments = @(
  (Quote-Argument 'scripts\run_general_reasoning_pair.py'),
  (Quote-Argument '--private-root'), (Quote-Argument $PrivateRoot),
  (Quote-Argument '--split'), (Quote-Argument $Split),
  (Quote-Argument '--seeds'), (Quote-Argument $Seeds),
  (Quote-Argument '--modes'), (Quote-Argument $Mode),
  (Quote-Argument '--model'), (Quote-Argument $Model),
  (Quote-Argument '--order-seed'), (Quote-Argument ([string]$OrderSeed))
)
if ($Resume) { $arguments += @((Quote-Argument '--resume'), (Quote-Argument $Resume)) }
if ($DryRun) { $arguments += (Quote-Argument '--dry-run') }

$process = Start-Process -FilePath $PythonPath -ArgumentList $arguments -WorkingDirectory $Root -RedirectStandardOutput $logPath -RedirectStandardError $errorPath -WindowStyle Hidden -PassThru
[ordered]@{
  schema = 'general_reasoning_v1_launcher_v1'
  pid = $process.Id
  started_at = (Get-Date).ToString('o')
  split = $Split
  seeds = $Seeds
  mode = $Mode
  model = $Model
  order_seed = $OrderSeed
  resume = if ($Resume) { $Resume } else { $null }
  dry_run = [bool]$DryRun
  log_path = (Resolve-Path $logPath).Path
  error_path = (Resolve-Path $errorPath).Path
  detached = $true
} | ConvertTo-Json | Set-Content -LiteralPath $pidPath -Encoding UTF8
Write-Output ($pidPath)
