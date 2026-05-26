param(
    [Parameter(Mandatory = $true)]
    [string]$Title,
    [string]$Author = '',
    [string]$SourceUrl = '',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonHelper = Join-Path (Join-Path $repoRoot 'scripts') 'wewrite_python.ps1'
. $pythonHelper
$python = Resolve-WeWritePythonCommand -RepoRoot $repoRoot -AdditionalSearchRoots @($repoRoot)
Set-WeWritePythonPath -RepoRoot $repoRoot

$args = @((Join-Path (Join-Path $repoRoot 'toolkit') 'cli.py'), 'new', '--title', $Title)
if (-not [string]::IsNullOrWhiteSpace($Author)) { $args += @('--author', $Author) }
if (-not [string]::IsNullOrWhiteSpace($SourceUrl)) { $args += @('--source-url', $SourceUrl) }
if ($Force) { $args += '--force' }

& $python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
