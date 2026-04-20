$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $scriptDir 'start-web.py'

$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source -3 $launcher @args
    exit $LASTEXITCODE
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source $launcher @args
    exit $LASTEXITCODE
}

Write-Error 'Python 3 was not found. Install Python first.'
exit 1
