# Inicia o UltronPro como aplicação estritamente local em http://127.0.0.1:8741.
param(
  [switch]$NoBrowser,
  [switch]$UseBundledUI,
  [ValidateSet('default', 'local-fast', 'local-capable')]
  [string]$ModelProfile = 'default',
  [ValidateSet('default', 'gr1', 'gr1-gr2')]
  [string]$CognitionProfile = 'default',
  [ValidateSet('default', 'full')]
  [string]$LifeProfile = 'default'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path '.venv\Scripts\python.exe')) {
  Write-Host "Ambiente não instalado. Executando setup..." -ForegroundColor Yellow
  & "$PSScriptRoot\setup.ps1"
}

$existing = Get-NetTCPConnection -LocalPort 8741 -State Listen -ErrorAction SilentlyContinue
if (-not $existing) {
  $previousModelOverride = $env:ULTRON_MODEL_PRIMARY
  $previousCognitionProfile = $env:ULTRON_COGNITION_PROFILE
  $previousLifeProfile = $env:ULTRON_LIFE_PROFILE
  try {
    switch ($ModelProfile) {
      'local-fast' { $env:ULTRON_MODEL_PRIMARY = 'ollama' }
      'local-capable' { $env:ULTRON_MODEL_PRIMARY = 'ollama_research' }
      default { Remove-Item Env:ULTRON_MODEL_PRIMARY -ErrorAction SilentlyContinue }
    }
    if ($CognitionProfile -eq 'default') {
      Remove-Item Env:ULTRON_COGNITION_PROFILE -ErrorAction SilentlyContinue
    } else {
      $env:ULTRON_COGNITION_PROFILE = $CognitionProfile
    }
    if ($LifeProfile -eq 'default') {
      Remove-Item Env:ULTRON_LIFE_PROFILE -ErrorAction SilentlyContinue
    } else {
      $env:ULTRON_LIFE_PROFILE = $LifeProfile
    }
    Write-Host "[UltronPro] Iniciando API local em http://127.0.0.1:8741 (modelo: $ModelProfile; cognição: $CognitionProfile; LIFE: $LifeProfile)" -ForegroundColor Cyan
    Start-Process -FilePath "$Root\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port','8741' -WorkingDirectory $Root -WindowStyle Minimized
  } finally {
    if ($null -eq $previousModelOverride) {
      Remove-Item Env:ULTRON_MODEL_PRIMARY -ErrorAction SilentlyContinue
    } else {
      $env:ULTRON_MODEL_PRIMARY = $previousModelOverride
    }
    if ($null -eq $previousCognitionProfile) {
      Remove-Item Env:ULTRON_COGNITION_PROFILE -ErrorAction SilentlyContinue
    } else {
      $env:ULTRON_COGNITION_PROFILE = $previousCognitionProfile
    }
    if ($null -eq $previousLifeProfile) {
      Remove-Item Env:ULTRON_LIFE_PROFILE -ErrorAction SilentlyContinue
    } else {
      $env:ULTRON_LIFE_PROFILE = $previousLifeProfile
    }
  }
  # O servidor sobe em processo separado; a interface exibirá o estado de conexão durante os primeiros segundos.
  Start-Sleep -Seconds 2
  if (-not (Get-NetTCPConnection -LocalPort 8741 -State Listen -ErrorAction SilentlyContinue)) {
    Write-Warning "A API ainda está inicializando em segundo plano. Aguarde alguns segundos e atualize a interface."
  }
} elseif ($ModelProfile -ne 'default' -or $CognitionProfile -ne 'default' -or $LifeProfile -ne 'default') {
  Write-Warning "A API já está ativa; os perfis solicitados só serão aplicados após reiniciar a API."
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
