# Inicia o UltronPro como aplicação estritamente local em http://127.0.0.1:8741.
param([switch]$NoBrowser, [switch]$UseBundledUI)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path '.venv\Scripts\python.exe')) {
  Write-Host "Ambiente não instalado. Executando setup..." -ForegroundColor Yellow
  & "$PSScriptRoot\setup.ps1"
}

$existing = Get-NetTCPConnection -LocalPort 8741 -State Listen -ErrorAction SilentlyContinue
if (-not $existing) {
  Write-Host "[UltronPro] Iniciando API local em http://127.0.0.1:8741" -ForegroundColor Cyan
  Start-Process -FilePath "$Root\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port','8741' -WorkingDirectory $Root -WindowStyle Minimized
  # O servidor sobe em processo separado; a interface exibirá o estado de conexão durante os primeiros segundos.
  Start-Sleep -Seconds 2
  if (-not (Get-NetTCPConnection -LocalPort 8741 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Warning "A API ainda está inicializando em segundo plano. Aguarde alguns segundos e atualize a interface."
  }
}

if (-not $UseBundledUI) {
  Write-Host "[UltronPro] Iniciando interface local em http://127.0.0.1:5173" -ForegroundColor Cyan
  Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev' -WorkingDirectory "$Root\apps\ui" -WindowStyle Minimized
  $Url = 'http://127.0.0.1:5173'
} else {
  $Url = 'http://127.0.0.1:8741'
}
if (-not $NoBrowser) { Start-Process $Url }
Write-Host "[UltronPro] Online: $Url" -ForegroundColor Green
Write-Host "Atalho de parada: Ctrl+Shift+F12 na interface (e botão STOP ULTRON)." -ForegroundColor DarkGray
