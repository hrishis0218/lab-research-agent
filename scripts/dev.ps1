param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
if (-not $SkipInstall) {
    conda run -n labagent python -m pip install -r requirements-v1.txt
    if ($LASTEXITCODE) { throw 'Python dependency installation failed' }
    Push-Location frontend
    try { npm ci; if ($LASTEXITCODE) { throw 'npm ci failed' } } finally { Pop-Location }
}
Push-Location frontend
try { npm run build; if ($LASTEXITCODE) { throw 'Frontend build failed' } } finally { Pop-Location }
Write-Host 'Workspace: http://127.0.0.1:8000 (Ctrl+C to stop). Existing Streamlit remains separate.'
conda run --no-capture-output -n labagent python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
