# UltronPro local setup — execute em PowerShell no diretório raiz do projeto.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[UltronPro] Preparando ambiente local..." -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.12+ não foi encontrado no PATH." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js/npm não foi encontrado no PATH." }

if (-not (Test-Path '.venv')) {
  python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Push-Location apps\ui
npm install
Pop-Location

$Folders = @('data\workspaces','data\vectors','data\artifacts','data\backups','data\browser_profiles\ultron','skills')
foreach ($Folder in $Folders) { New-Item -ItemType Directory -Force -Path $Folder | Out-Null }

if (-not (Test-Path 'config\local.yaml')) {
  @"
# Sobrescritas locais opcionais. Este arquivo não deve conter segredos.
# Para usar Ollama localmente, descomente:
# models:
#   primary: ollama
#   registry:
#     ollama:
#       enabled: true
"@ | Set-Content -Path 'config\local.yaml' -Encoding utf8
}

Write-Host "[UltronPro] Instalação concluída. Execute .\scripts\start.ps1" -ForegroundColor Green
