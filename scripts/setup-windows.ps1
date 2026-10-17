#Requires -Version 5.1
<#
.SYNOPSIS
    Ensure Windows-side tooling (gh, specify CLI) is installed when missing.

.DESCRIPTION
    - gh: if no working `gh` is found (`.tools\gh\bin\gh.exe`, then PATH),
      downloads the pinned official release asset, verifies its SHA-256 and
      extracts it into the git-ignored `.tools` directory.
    - specify CLI: only needed for scaffold-level Spec Kit work
      (`specify init`, new integrations, upgrades). The `/speckit*` agent
      commands run from `.specify/scripts/` helpers without it. When missing
      and `uv` is available, installs the pinned `specify-cli` via
      `uv tool install`.

    Authentication is intentionally not automated: run `gh auth login`
    yourself so no token is ever written into the repository.

.PARAMETER ToolsDir
    Directory for extracted tools. Defaults to <repo>\.tools.

.PARAMETER GhVersion
    Pinned GitHub CLI version. Defaults to 2.102.0.

.PARAMETER GhSha256
    Expected SHA-256 of the gh release asset. Defaults to the official
    checksum for 2.102.0 (see deps/windows/README.md).

.PARAMETER SpecifyVersion
    Pinned specify-cli version. Defaults to `.specify/init-options.json`
    `speckit_version` when that file exists, otherwise 1.2.1.

.PARAMETER Force
    Reinstall even when working tools are already available. Note: for
    specify-cli this reinstall is quieter than a first install; check the
    version line at the end.

.PARAMETER SkipGh
    Skip the gh check/install step.

.PARAMETER SkipSpecify
    Skip the specify CLI check/install step.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1
#>
[CmdletBinding()]
param(
    [string]$ToolsDir,
    [string]$GhVersion = "2.102.0",
    [string]$GhSha256 = "ae64e556ecc240b200f7eba60d550e4bb60d78e860e69dd88c449405b86067f4",
    [string]$SpecifyVersion,
    [switch]$Force,
    [switch]$SkipGh,
    [switch]$SkipSpecify
)

$ErrorActionPreference = "Stop"

$scriptDir = $PSScriptRoot
if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$repoRoot = Split-Path -Parent $scriptDir

if (-not $ToolsDir) { $ToolsDir = Join-Path $repoRoot ".tools" }

if (-not $SpecifyVersion) {
    $SpecifyVersion = "1.2.1"
    $initOptions = Join-Path $repoRoot ".specify\init-options.json"
    if (Test-Path $initOptions) {
        try {
            $parsed = Get-Content $initOptions -Raw | ConvertFrom-Json
            if ($parsed.speckit_version) { $SpecifyVersion = [string]$parsed.speckit_version }
        } catch {
            Write-Warning "Could not read ${initOptions}, using default specify-cli ${SpecifyVersion}."
        }
    }
}

function Find-Gh {
    param([string]$ToolsDir)

    $local = Join-Path $ToolsDir "gh\bin\gh.exe"
    if (Test-Path $local) { return $local }

    $command = Get-Command gh -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    return $null
}

function Install-Gh {
    param(
        [string]$ToolsDir,
        [string]$GhVersion,
        [string]$GhSha256
    )

    $asset = "gh_${GhVersion}_windows_amd64.zip"
    $url = "https://github.com/cli/cli/releases/download/v$GhVersion/$asset"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) $asset

    Write-Host "Downloading gh $GhVersion from $url ..."
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --retry 3 --connect-timeout 30 --max-time 300 -o $tmp $url
        if ($LASTEXITCODE -ne 0) {
            throw "curl.exe failed to download $url (exit $LASTEXITCODE)"
        }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -TimeoutSec 300
    }

    $actual = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $GhSha256.ToLowerInvariant()) {
        throw "Checksum mismatch for ${asset}: expected ${GhSha256}, got ${actual}"
    }

    $destination = Join-Path $ToolsDir "gh"
    if (Test-Path $destination) {
        Remove-Item -Path $destination -Recurse -Force
    }

    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    Expand-Archive -Path $tmp -DestinationPath $destination -Force
    Remove-Item -Path $tmp -Force -ErrorAction SilentlyContinue

    $gh = Join-Path $destination "bin\gh.exe"
    if (-not (Test-Path $gh)) {
        throw "gh.exe was not found after extracting $asset"
    }

    return $gh
}

if (-not $SkipGh) {
    $existing = Find-Gh -ToolsDir $ToolsDir
    if ($existing -and -not $Force) {
        Write-Host "gh already available: $existing"
        Write-Host (& $existing --version | Select-Object -First 1)
    } else {
        $gh = Install-Gh -ToolsDir $ToolsDir -GhVersion $GhVersion -GhSha256 $GhSha256
        Write-Host "Installed gh to $gh"
        Write-Host (& $gh --version | Select-Object -First 1)
        Write-Host "Authenticate with: & `"$gh`" auth login --hostname github.com --git-protocol https --web"
    }
}

if (-not $SkipSpecify) {
    $specify = Get-Command specify -ErrorAction SilentlyContinue
    if ($specify -and -not $Force) {
        Write-Host "specify already available: $($specify.Source)"
        Write-Host (& specify --version | Select-Object -First 1)
    } elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host "Installing specify-cli ${SpecifyVersion} via uv ..."
        & uv tool install "specify-cli==${SpecifyVersion}" --python 3.11 --force 2>&1 | Select-Object -Last 3
        $uvBin = Join-Path $HOME ".local\bin\specify.exe"
        if (Test-Path $uvBin) {
            Write-Host "specify installed at $uvBin (uv tool bin dir; add to PATH to call it directly)."
            Write-Host (& $uvBin --version | Select-Object -First 1)
        } else {
            Write-Host "specify-cli ${SpecifyVersion} installed via uv. Run 'uv tool update-shell' so 'specify' is on PATH."
        }
    } else {
        Write-Host "specify CLI not found and uv is unavailable."
        Write-Host "Install uv (https://docs.astral.sh/uv/), then run:"
        Write-Host "uv tool install `"specify-cli==${SpecifyVersion}`" --python 3.11"
        Write-Host "Note: the specify CLI is optional — /speckit* commands run from .specify/scripts/ without it."
    }
}
