Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

param(
    [switch]$VerifyOnly
)

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command -Name "bash")) {
    Write-Error "bash is required. Install Git Bash or WSL, then retry."
}

if ($VerifyOnly) {
    Write-Host "Verifying Grok CLI installation..."
    bash -lc "~/.grok/bin/grok --version && ~/.grok/bin/agent --version"
    exit $LASTEXITCODE
}

Write-Host "Installing Grok CLI via bash-safe installer..."
bash -lc "curl -fsSL https://x.ai/cli/install.sh | bash"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Grok installer failed."
}

Write-Host "Verifying Grok CLI binaries..."
bash -lc "~/.grok/bin/grok --version && ~/.grok/bin/agent --version"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Install finished but version check failed."
}

Write-Host "Grok CLI install complete."
