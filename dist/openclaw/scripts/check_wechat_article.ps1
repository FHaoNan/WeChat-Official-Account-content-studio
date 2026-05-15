param(
    [Parameter(Mandatory = $true)]
    [string]$ArticleDir,
    [switch]$Strict
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$workflowRoot = Join-Path $repoRoot 'skill2 paibanyouhua'
$pythonHelper = Join-Path (Join-Path $repoRoot 'scripts') 'wewrite_python.ps1'
if (-not (Test-Path -LiteralPath $pythonHelper)) {
    throw "Python helper script not found: $pythonHelper"
}
. $pythonHelper
$python = Resolve-WeWritePythonCommand -RepoRoot $repoRoot -AdditionalSearchRoots @($workflowRoot)
Set-WeWritePythonPath -RepoRoot $repoRoot

function Resolve-ManagedArticleDir {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        if (-not (Test-Path -LiteralPath $PathValue)) {
            throw "Article folder not found: $PathValue"
        }
        return (Resolve-Path -LiteralPath $PathValue).Path
    }

    $candidates = @(
        (Join-Path $repoRoot $PathValue),
        (Join-Path (Join-Path $repoRoot 'output') $PathValue)
    ) | Select-Object -Unique

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Article folder not found. Tried: $($candidates -join ', ')"
}

$resolvedArticleDir = Resolve-ManagedArticleDir -PathValue $ArticleDir

if (-not (Test-Path -LiteralPath $resolvedArticleDir)) {
    throw "Article folder not found: $resolvedArticleDir"
}

$scriptPath = Join-Path (Join-Path $workflowRoot 'scripts') 'run-quality-gates.py'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Quality gate script not found: $scriptPath"
}

$args = @($scriptPath, '--article-dir', $resolvedArticleDir, '--strict')

$env:WEWRITE_REQUIRE_IMAGE_CONFIG = '0'
& $python @args
$commandSucceeded = $?
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not $commandSucceeded) {
    exit 1
}
