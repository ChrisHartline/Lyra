Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command -Name "bash")) {
    Write-Error "bash is required. Install Git Bash or WSL, then retry."
}

Write-Host "Checking Grok CLI location and versions..."
bash -lc "command -v grok || true; command -v agent || true; ~/.grok/bin/grok --version && ~/.grok/bin/agent --version"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Grok CLI verification failed."
}

Write-Host "Grok CLI is installed and reachable."
