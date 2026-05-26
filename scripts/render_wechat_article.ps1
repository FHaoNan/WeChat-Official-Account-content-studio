param(
    [Parameter(Mandatory = $true)]
    [string]$ArticleDir,
    [string]$Theme = ''
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonHelper = Join-Path (Join-Path $repoRoot 'scripts') 'wewrite_python.ps1'
. $pythonHelper
$python = Resolve-WeWritePythonCommand -RepoRoot $repoRoot -AdditionalSearchRoots @($repoRoot)
Set-WeWritePythonPath -RepoRoot $repoRoot

$args = @((Join-Path (Join-Path $repoRoot 'toolkit') 'cli.py'), 'render', '--article-dir', $ArticleDir)
if (-not [string]::IsNullOrWhiteSpace($Theme)) { $args += @('--theme', $Theme) }

& $python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
