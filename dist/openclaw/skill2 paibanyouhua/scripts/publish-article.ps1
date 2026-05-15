param(
    [Parameter(Mandatory = $true)]
    [string]$ArticleDir,
    [switch]$AllowNativeLists,
    [string]$Config = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot 'publish-article.py'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Python publish script not found: $scriptPath"
}

$workflowRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $workflowRoot
$pythonHelper = Join-Path (Join-Path $repoRoot 'scripts') 'wewrite_python.ps1'
if (-not (Test-Path -LiteralPath $pythonHelper)) {
    throw "Python helper script not found: $pythonHelper"
}
. $pythonHelper

$publishArgs = @($scriptPath, '--article-dir', $ArticleDir, '--json')
if ($AllowNativeLists) {
    $publishArgs += '--allow-native-lists'
}
if (-not [string]::IsNullOrWhiteSpace($Config)) {
    $publishArgs += @('--config', $Config)
}
if ($DryRun) {
    $publishArgs += '--dry-run'
}

$python = Resolve-WeWritePythonCommand -RepoRoot $repoRoot -AdditionalSearchRoots @($workflowRoot)
Set-WeWritePythonPath -RepoRoot $repoRoot
& $python @publishArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
