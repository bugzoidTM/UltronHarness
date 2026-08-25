# Teste de fumaça do UltronPro. Requer API em http://127.0.0.1:8741.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Api = 'http://127.0.0.1:8741/api'

function Invoke-UltronJson([string]$Method, [string]$Path, [object]$Body = $null) {
  $Arguments = @('--fail', '--silent', '--show-error', '--max-time', '10', '-X', $Method, "$Api$Path")
  if ($null -ne $Body) {
    $json = $Body | ConvertTo-Json -Compress -Depth 8
    $temp = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($temp, $json, [System.Text.UTF8Encoding]::new($false))
    $Arguments = @('--fail', '--silent', '--show-error', '--max-time', '10', '-H', 'Content-Type: application/json', '-X', $Method, '--data-binary', "@$temp", "$Api$Path")
  }
  try { return (& curl.exe @Arguments | ConvertFrom-Json) }
  finally { if ($temp -and (Test-Path $temp)) { Remove-Item $temp -Force } }
}

Write-Host '[1/7] Health' -ForegroundColor Cyan
$health = Invoke-UltronJson 'GET' '/system/health'
if (-not $health.database) { throw 'Banco SQLite não está saudável.' }

Write-Host '[2/7] Create supervised mission' -ForegroundColor Cyan
$task = Invoke-UltronJson 'POST' '/tasks' @{ title = 'Smoke test workspace artifact'; objective = 'Criar um arquivo de relatório no workspace e verificar a conclusão.'; workspace = 'smoke_test'; autonomy_mode = 2 }

Write-Host '[3/7] Run planner and policy' -ForegroundColor Cyan
$null = Invoke-UltronJson 'POST' "/tasks/$($task.id)/run"
$state = $null
for ($attempt = 0; $attempt -lt 360; $attempt++) {
  Start-Sleep -Milliseconds 350
  $state = Invoke-UltronJson 'GET' "/tasks/$($task.id)"
  if ($state.status -in @('waiting_approval','completed','failed')) { break }
}
if ($state.status -ne 'waiting_approval') { throw "Esperava waiting_approval; recebido $($state.status)." }

Write-Host '[4/7] Approve controlled modification' -ForegroundColor Cyan
$approval = (Invoke-UltronJson 'GET' '/approvals' | Where-Object { $_.task_id -eq $task.id -and $_.status -eq 'pending' } | Select-Object -First 1)
if (-not $approval) { throw 'Aprovação de escrita não criada.' }
$null = Invoke-UltronJson 'POST' "/approvals/$($approval.id)" @{ approved = $true; note = 'Aprovado pelo smoke test local.' }

Write-Host '[5/7] Verify completion and operational trace' -ForegroundColor Cyan
$final = Invoke-UltronJson 'GET' "/tasks/$($task.id)"
if ($final.status -ne 'completed') { throw "Tarefa não concluída: $($final.status)." }
if ($final.events.Count -lt 6) { throw 'Histórico operacional insuficiente.' }
if (-not (Test-Path 'data\workspaces\smoke_test\ultron_task_note.md')) { throw 'Artefato de workspace não foi criado.' }

Write-Host '[6/7] Verify persistent experience memory' -ForegroundColor Cyan
$memories = Invoke-UltronJson 'GET' '/memories'
if (-not ($memories | Where-Object { $_.task_id -eq $task.id })) { throw 'Experiência não foi persistida em memória.' }

Write-Host '[7/7] Verify local UI' -ForegroundColor Cyan
$ui = & curl.exe --fail --silent --show-error --max-time 10 -I http://127.0.0.1:5173
if (-not ($ui -match '200 OK')) { throw 'Interface local não respondeu com HTTP 200.' }

Write-Host "SMOKE PASS: tarefa=$($task.id); eventos=$($final.events.Count); memória persistida; UI local disponível." -ForegroundColor Green
