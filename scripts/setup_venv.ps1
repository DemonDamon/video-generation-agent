# Windows: 在干净虚拟环境中安装依赖，避免 base 环境元数据损坏
# 用法: .\scripts\setup_venv.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

$venvPath = Join-Path $projectRoot ".venv"
Write-Host "Project: $projectRoot"
Write-Host "Creating venv at: $venvPath"

if (Test-Path $venvPath) {
    Write-Host "Removing existing .venv..."
    Remove-Item -Recurse -Force $venvPath
}

python -m venv $venvPath
& "$venvPath\Scripts\Activate.ps1"
pip install --upgrade pip
pip install -r (Join-Path $projectRoot "requirements.txt")

Write-Host ""
Write-Host "Done. Activate with: .\.venv\Scripts\Activate.ps1"
