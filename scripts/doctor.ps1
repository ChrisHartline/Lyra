Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Write-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][bool]$Ok,
        [string]$Detail = ""
    )

    if ($Ok) {
        Write-Host "[OK] $Label $Detail"
    } else {
        Write-Host "[FAIL] $Label $Detail"
    }
}

function Get-EnvFileValue {
    param(
        [Parameter(Mandatory = $true)][string]$EnvFilePath,
        [Parameter(Mandatory = $true)][string]$Key
    )

    if (-not (Test-Path -LiteralPath $EnvFilePath)) {
        return $null
    }

    $line = Select-String -Path $EnvFilePath -Pattern "^\s*$Key\s*=" | Select-Object -First 1
    if (-not $line) {
        return $null
    }

    $raw = $line.Line
    return ($raw -replace "^\s*$Key\s*=\s*", "").Trim()
}

$repoRoot = (Get-Location).Path
$envPath = Join-Path $repoRoot ".env"

Write-Host "Lyra Doctor - environment diagnostics"
Write-Host "Repo: $repoRoot"
Write-Host ""

# Toolchain checks
$hasBash = Test-Command -Name "bash"
$hasCurlExe = Test-Command -Name "curl.exe"

Write-Check -Label "bash available" -Ok $hasBash
Write-Check -Label "curl.exe available" -Ok $hasCurlExe

$grokVersionOk = $false
$agentVersionOk = $false
$grokVersion = ""
$agentVersion = ""

if ($hasBash) {
    try {
        $grokVersion = bash -lc "~/.grok/bin/grok --version" 2>$null
        if ($LASTEXITCODE -eq 0 -and $grokVersion) {
            $grokVersionOk = $true
        }
    } catch {
        $grokVersionOk = $false
    }

    try {
        $agentVersion = bash -lc "~/.grok/bin/agent --version" 2>$null
        if ($LASTEXITCODE -eq 0 -and $agentVersion) {
            $agentVersionOk = $true
        }
    } catch {
        $agentVersionOk = $false
    }
}

Write-Check -Label "grok binary works" -Ok $grokVersionOk -Detail $grokVersion
Write-Check -Label "agent binary works" -Ok $agentVersionOk -Detail $agentVersion

# .env checks (presence only)
$envExists = Test-Path -LiteralPath $envPath
Write-Check -Label ".env exists" -Ok $envExists -Detail $envPath

$requiredKeys = @("GROK_API_KEY")
foreach ($key in $requiredKeys) {
    $value = Get-EnvFileValue -EnvFilePath $envPath -Key $key
    $present = -not [string]::IsNullOrWhiteSpace($value)
    $masked = if ($present) { "(set)" } else { "(missing or empty)" }
    Write-Check -Label "$key in .env" -Ok $present -Detail $masked
}

Write-Host ""
if ($hasBash -and $hasCurlExe -and $grokVersionOk -and $agentVersionOk) {
    Write-Host "Doctor complete: base toolchain looks good."
} else {
    Write-Host "Doctor complete: issues found. Run install helper:"
    Write-Host "  ./scripts/install-grok.ps1"
}
