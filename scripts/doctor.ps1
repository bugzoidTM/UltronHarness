# Diagnóstico local do UltronPro. Não altera configurações ou instalações.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Report([string]$Name, [bool]$Ok, [string]$Detail) {
  $Color = if ($Ok) { 'Green' } else { 'Yellow' }
  $Flag = if ($Ok) { 'OK' } else { 'CHECK' }
  Write-Host ("[{0}] {1,-18} {2}" -f $Flag, $Name, $Detail) -ForegroundColor $Color
}

$python = Get-Command python -ErrorAction SilentlyContinue
$node = Get-Command node -ErrorAction SilentlyContinue
$npm = Get-Command npm -ErrorAction SilentlyContinue
$git = Get-Command git -ErrorAction SilentlyContinue
Report 'Windows' $true ((Get-CimInstance Win32_OperatingSystem).Caption)
Report 'Python' ($null -ne $python) (if ($python) { python --version } else { 'Instale Python 3.12+' })
Report 'Node' ($null -ne $node) (if ($node) { node --version } else { 'Instale Node.js LTS' })
Report 'npm' ($null -ne $npm) (if ($npm) { npm --version } else { 'Indisponível' })
Report 'Git' ($null -ne $git) (if ($git) { git --version } else { 'Opcional para experimentos' })
Report 'venv' (Test-Path '.venv\Scripts\python.exe') (if (Test-Path '.venv\Scripts\python.exe') { 'Ambiente criado' } else { 'Execute .\scripts\setup.ps1' })
Report 'UI deps' (Test-Path 'apps\ui\node_modules') (if (Test-Path 'apps\ui\node_modules') { 'node_modules presentes' } else { 'Execute setup' })

$memory = Get-CimInstance Win32_ComputerSystem
$freeMemoryGB = [math]::Round((Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue / 1024, 2)
$disk = Get-PSDrive -Name (Split-Path -Qualifier $Root).TrimEnd(':')
Report 'RAM livre' ($freeMemoryGB -ge 4) "$freeMemoryGB GB disponíveis"
Report 'Disco livre' ($disk.Free / 1GB -ge 20) ("{0:N1} GB no volume do projeto" -f ($disk.Free / 1GB))

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
Report 'Ollama' ($null -ne $ollama) (if ($ollama) { 'Disponível; execute ollama pull qwen2.5:3b se desejar' } else { 'Opcional; configure Ollama ou llama.cpp para LLM generativo local' })
try { $ollamaHealth = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; Report 'Ollama API' $true ("{0} modelos encontrados" -f $ollamaHealth.models.Count) } catch { Report 'Ollama API' $false 'Não está escutando em 127.0.0.1:11434' }
try { $ultron = Invoke-RestMethod 'http://127.0.0.1:8741/api/system/health' -TimeoutSec 2; Report 'Ultron API' $true ("{0}; modelo={1}" -f $ultron.status,$ultron.model.active) } catch { Report 'Ultron API' $false 'Não está executando (normal antes do start)' }

$port = Get-NetTCPConnection -LocalPort 8741 -State Listen -ErrorAction SilentlyContinue
Report 'Porta 8741' ($null -eq $port) (if ($port) { 'Em uso pela API ou outro processo' } else { 'Disponível' })
Write-Host "\nDiagnóstico concluído. Nenhuma alteração foi realizada." -ForegroundColor Cyan
