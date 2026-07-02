$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$testDeps = Join-Path $repoRoot ".test_deps"

if (-not (Test-Path $testDeps)) {
    Write-Error "Missing .test_deps. Install test dependencies or restore the local dependency directory before running tests."
}

$env:PYTHONPATH = $testDeps

$pytestArgs = @($args)
$hasBaseTemp = $false
foreach ($arg in $pytestArgs) {
    $argText = [string]$arg
    if ($argText -eq "--basetemp" -or $argText.StartsWith("--basetemp=")) {
        $hasBaseTemp = $true
        break
    }
}

if (-not $hasBaseTemp) {
    $pytestArgs = @("--basetemp", (Join-Path $repoRoot ".pytest_tmp")) + $pytestArgs
}

python -m pytest @pytestArgs
exit $LASTEXITCODE
