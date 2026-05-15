param(
    [Parameter(Mandatory = $true)]
    [string]$Title,
    [string]$Author = '',
    [string]$SourceUrl = '',
    [switch]$Force
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$workflowRoot = Join-Path $repoRoot 'skill2 paibanyouhua'
$scriptPath = Join-Path (Join-Path $workflowRoot 'scripts') 'new-article.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Template article script not found: $scriptPath"
}

& $scriptPath -Title $Title -Author $Author -SourceUrl $SourceUrl -Force:$Force
