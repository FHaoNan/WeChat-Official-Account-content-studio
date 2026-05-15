function Get-WeWriteHostPlatform {
    if ((Get-Variable IsWindows -ErrorAction SilentlyContinue) -and $IsWindows) {
        return 'Windows'
    }
    if ((Get-Variable IsMacOS -ErrorAction SilentlyContinue) -and $IsMacOS) {
        return 'macOS'
    }
    if ((Get-Variable IsLinux -ErrorAction SilentlyContinue) -and $IsLinux) {
        return 'Linux'
    }
    if ($env:OS -eq 'Windows_NT') {
        return 'Windows'
    }

    return 'Unix'
}

function Get-WeWriteVenvPythonCandidates {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [string]$Platform
    )

    $venvRoot = Join-Path $Root '.venv'
    if ($Platform -eq 'Windows') {
        return @((Join-Path (Join-Path $venvRoot 'Scripts') 'python.exe'))
    }

    return @((Join-Path (Join-Path $venvRoot 'bin') 'python'))
}

function Get-WeWriteFallbackPythonCandidates {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Platform
    )

    if ($Platform -eq 'Windows') {
        return @('python', 'py')
    }

    return @('python3', 'python')
}

function Get-WeWriteVenvSitePackageCandidates {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$Platform
    )

    $venvRoot = Join-Path $RepoRoot '.venv'
    if ($Platform -eq 'Windows') {
        return @((Join-Path (Join-Path $venvRoot 'Lib') 'site-packages'))
    }

    $libRoot = Join-Path $venvRoot 'lib'
    if (-not (Test-Path -LiteralPath $libRoot)) {
        return @()
    }

    return @(
        Get-ChildItem -LiteralPath $libRoot -Directory -Filter 'python*' |
            ForEach-Object { Join-Path $_.FullName 'site-packages' }
    )
}

function Resolve-WeWritePythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [string[]]$AdditionalSearchRoots = @()
    )

    $candidates = @()
    $platform = Get-WeWriteHostPlatform

    if (-not [string]::IsNullOrWhiteSpace($env:WEWRITE_PYTHON)) {
        $candidates += $env:WEWRITE_PYTHON
    }

    $roots = @($RepoRoot) + $AdditionalSearchRoots | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

    foreach ($root in $roots) {
        foreach ($venvPython in (Get-WeWriteVenvPythonCandidates -Root $root -Platform $platform)) {
            if (Test-Path -LiteralPath $venvPython) {
                $candidates += $venvPython
            }
        }
    }

    $candidates += Get-WeWriteFallbackPythonCandidates -Platform $platform

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        try {
            & $candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
        catch {
            continue
        }
    }

    throw 'Python 3.10+ was not found. Set WEWRITE_PYTHON to a compatible interpreter, or create a local .venv with the project requirements installed.'
}

function Set-WeWritePythonPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $platform = Get-WeWriteHostPlatform
    $sitePackages = @(
        Get-WeWriteVenvSitePackageCandidates -RepoRoot $RepoRoot -Platform $platform |
            Where-Object { Test-Path -LiteralPath $_ }
    )

    if ($sitePackages.Count -eq 0) {
        return
    }

    $paths = @($sitePackages)
    if (-not [string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
        $paths += ($env:PYTHONPATH -split [System.IO.Path]::PathSeparator)
    }

    $env:PYTHONPATH = ($paths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique) -join [System.IO.Path]::PathSeparator
}
