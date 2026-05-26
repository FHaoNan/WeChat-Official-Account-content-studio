param(
    [Parameter(Mandatory = $true)]
    [string]$ArticleDir,
    [switch]$AllowNativeLists,
    [string]$Config = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonHelper = Join-Path (Join-Path $repoRoot 'scripts') 'wewrite_python.ps1'
. $pythonHelper
$python = Resolve-WeWritePythonCommand -RepoRoot $repoRoot -AdditionalSearchRoots @($repoRoot)
Set-WeWritePythonPath -RepoRoot $repoRoot

$args = @((Join-Path (Join-Path $repoRoot 'toolkit') 'cli.py'), 'publish-draft', '--article-dir', $ArticleDir)
if ($AllowNativeLists) { $args += '--allow-native-lists' }
if (-not [string]::IsNullOrWhiteSpace($Config)) { $args += @('--config', $Config) }
if ($DryRun) { $args += '--dry-run' }

& $python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
