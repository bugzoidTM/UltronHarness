$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$runDir = Join-Path $root "data\artifacts\research\hermes\transfer100"
New-Item -ItemType Directory -Force $runDir | Out-Null

$report = Join-Path $runDir "transfer100_json_compact_multiseed_42_51.json"
$stdout = Join-Path $runDir "transfer100_background.stdout.log"
$stderr = Join-Path $runDir "transfer100_background.stderr.log"
$state = Join-Path $runDir "transfer100_background_state.json"
$python = Join-Path $root ".venv\Scripts\python.exe"

$active = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match "run_transfer20\.py" -and $_.CommandLine -match "transfer100"
}
if ($active) {
    throw "Já existe uma execução Transfer-100 em segundo plano: PID(s) $($active.ProcessId -join ', ')"
}

$arguments = "scripts\run_transfer20.py --benchmark transfer100 --batch-by-family --batch-size 20 --model ollama_research --seeds 42 43 44 45 46 47 48 49 50 51 --timeout-seconds 300 --report `"$report`""

$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
$metadata = [ordered]@{
    pid = $process.Id
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    report = $report
    stdout = $stdout
    stderr = $stderr
    requested_seeds = @(42, 43, 44, 45, 46, 47, 48, 49, 50, 51)
    status = "running"
}
$metadata | ConvertTo-Json | Set-Content -Path $state -Encoding utf8
$metadata | ConvertTo-Json -Depth 3
