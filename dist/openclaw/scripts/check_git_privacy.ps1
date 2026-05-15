param(
    [switch]$Json
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path (Join-Path $repoRoot 'scripts') 'git_privacy_guard.py'
$pythonHelper = Join-Path (Join-Path $repoRoot 'scripts') 'wewrite_python.ps1'

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Privacy guard script not found: $scriptPath"
}
if (-not (Test-Path -LiteralPath $pythonHelper)) {
    throw "Python helper script not found: $pythonHelper"
}
. $pythonHelper
$python = Resolve-WeWritePythonCommand -RepoRoot $repoRoot
Set-WeWritePythonPath -RepoRoot $repoRoot

$args = @($scriptPath)
if ($Json) {
    $args += '--json'
}

& $python @args
$commandSucceeded = $?
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not $commandSucceeded) {
    exit 1
}
