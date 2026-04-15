[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs')]
    [string]$Action = 'start',

    [Alias('Host')]
    [string]$BindHost = '127.0.0.1',

    [int]$Port = 8080,

    [string]$CondaEnv = 'base',

    [int]$StartupTimeoutSec = 45,

    [int]$LogTailLines = 80,

    [switch]$InstallPythonDeps,

    [switch]$SkipFrontendBuild,

    [switch]$Follow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$FrontendDir = Join-Path $ProjectRoot 'web\frontend'
$LogDir = Join-Path $ProjectRoot 'web-logs'
$StateFile = Join-Path $LogDir ("web-{0}.state.json" -f $Port)

function Write-Section {
    param([string]$Title)

    Write-Host ""
    Write-Host ("=== {0} ===" -f $Title)
}

function Write-Step {
    param(
        [int]$Current,
        [int]$Total,
        [string]$Message
    )

    Write-Host ("[{0}/{1}] {2}" -f $Current, $Total, $Message)
}

function Ensure-Directory {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-State {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    catch {
        throw "Failed to read state file: $Path"
    }
}

function Save-State {
    param(
        [string]$Path,
        [pscustomobject]$State
    )

    $State | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Remove-State {
    param([string]$Path)

    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Get-StatePropertyValue {
    param(
        $State,
        [string]$Name
    )

    if (-not $State) {
        return $null
    }

    $property = $State.PSObject.Properties[$Name]
    if ($property) {
        return $property.Value
    }

    return $null
}

function Get-StatePid {
    param($State)

    $pidValue = Get-StatePropertyValue -State $State -Name 'pid'
    if ($null -eq $pidValue) {
        $pidValue = Get-StatePropertyValue -State $State -Name 'launcherPid'
    }

    if ($null -eq $pidValue) {
        return $null
    }

    return [int]$pidValue
}

function Get-StateLauncherPid {
    param($State)

    $pidValue = Get-StatePropertyValue -State $State -Name 'launcherPid'
    if ($null -eq $pidValue) {
        return $null
    }

    return [int]$pidValue
}

function Get-StateBindHost {
    param($State)

    $bindHost = Get-StatePropertyValue -State $State -Name 'bindHost'
    if ($bindHost) {
        return [string]$bindHost
    }

    $legacyHost = Get-StatePropertyValue -State $State -Name 'host'
    if ($legacyHost) {
        return [string]$legacyHost
    }

    return '127.0.0.1'
}

function Get-StateCondaEnv {
    param($State)

    $condaEnvValue = Get-StatePropertyValue -State $State -Name 'condaEnv'
    if ($condaEnvValue) {
        return [string]$condaEnvValue
    }

    return 'base'
}

function Resolve-CondaExecutable {
    if ($env:CONDA_EXE -and (Test-Path -LiteralPath $env:CONDA_EXE)) {
        return $env:CONDA_EXE
    }

    foreach ($name in @('conda.exe', 'conda.bat', 'conda')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Source
        }
    }

    throw "Conda was not found. Initialize Conda in this shell or add Conda to PATH."
}

function Get-CondaEnvironmentEntries {
    param([string]$CondaExecutable)

    $envListRaw = & $CondaExecutable env list --json 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $envListRaw) {
        throw "Unable to query Conda environments. Check that Conda is installed correctly."
    }

    $envList = $envListRaw | ConvertFrom-Json
    $entries = @()

    if ($envList.envs_details) {
        foreach ($property in $envList.envs_details.PSObject.Properties) {
            $prefix = $property.Name
            $details = $property.Value
            $name = $details.name
            if (-not $name) {
                $name = Split-Path -Leaf $prefix
            }

            $entries += [pscustomobject]@{
                Name = [string]$name
                Prefix = [string]$prefix
            }
        }
    }
    else {
        foreach ($prefix in $envList.envs) {
            $name = Split-Path -Leaf $prefix
            if (-not $name) {
                $name = $prefix
            }

            $entries += [pscustomobject]@{
                Name = [string]$name
                Prefix = [string]$prefix
            }
        }
    }

    return @($entries | Sort-Object -Property Name -Unique)
}

function Resolve-CondaPrefix {
    param(
        [string]$CondaExecutable,
        [string]$EnvironmentName
    )

    if ([string]::IsNullOrWhiteSpace($EnvironmentName)) {
        throw "Conda environment name cannot be empty."
    }

    if (Test-Path -LiteralPath $EnvironmentName) {
        return (Resolve-Path -LiteralPath $EnvironmentName).Path
    }

    if ($EnvironmentName -ieq 'base') {
        $basePrefix = (& $CondaExecutable info --base 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $basePrefix) {
            return $basePrefix.Trim()
        }
    }

    $envEntries = Get-CondaEnvironmentEntries -CondaExecutable $CondaExecutable
    foreach ($entry in $envEntries) {
        if ($entry.Name -ieq $EnvironmentName) {
            return $entry.Prefix
        }
    }

    $availableNames = @($envEntries | ForEach-Object { $_.Name })
    if ($availableNames.Count -gt 0) {
        throw ("Conda environment '{0}' was not found. Available environments: {1}" -f $EnvironmentName, ($availableNames -join ', '))
    }

    throw "Conda environment '$EnvironmentName' was not found."
}

function Resolve-NpmCommand {
    foreach ($name in @('npm.cmd', 'npm')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Source
        }
    }

    throw "npm was not found. Install Node.js first."
}

function Resolve-NodeCommand {
    foreach ($name in @('node.exe', 'node')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Source
        }
    }

    throw "Node.js was not found. Install Node.js first."
}

function Get-ManagedProcess {
    param($State)

    if (-not $State) {
        return $null
    }

    $statePid = Get-StatePid -State $State
    if ($null -eq $statePid) {
        return $null
    }

    return Get-Process -Id $statePid -ErrorAction SilentlyContinue
}

function Get-PortOwner {
    param([int]$TargetPort)

    $netstatLines = netstat -ano -p tcp 2>$null
    foreach ($line in $netstatLines) {
        if ($line -match '^\s*TCP\s+(?<local>\S+):(?<port>\d+)\s+\S+\s+LISTENING\s+(?<pid>\d+)\s*$') {
            if ([int]$Matches.port -ne $TargetPort) {
                continue
            }

            $matchedPid = [int]$Matches.pid
            $process = Get-Process -Id $matchedPid -ErrorAction SilentlyContinue
            return [pscustomobject]@{
                OwningPid = $matchedPid
                ProcessName = if ($process) { $process.ProcessName } else { 'unknown' }
                LocalAddress = $Matches.local
                LocalPort = $TargetPort
            }
        }
    }

    $connection = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue |
        Sort-Object -Property OwningProcess |
        Select-Object -First 1

    if (-not $connection) {
        return $null
    }

    $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        OwningPid = $connection.OwningProcess
        ProcessName = if ($process) { $process.ProcessName } else { 'unknown' }
        LocalAddress = $connection.LocalAddress
        LocalPort = $connection.LocalPort
    }
}

function Test-PortAvailable {
    param([int]$TargetPort)

    return -not [bool](Get-PortOwner -TargetPort $TargetPort)
}

function Test-WebDependencies {
    param([string]$PythonExecutable)

    & $PythonExecutable -c 'import fastapi, uvicorn'
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    return $true
}

function Install-PythonDependencies {
    param([string]$PythonExecutable)

    Write-Step 3 7 'Installing Python web dependencies'
    & $PythonExecutable -m pip install -e '.[web]'
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Python web dependencies."
    }
}

function Invoke-FrontendBuild {
    param([string]$NpmCommand)

    if (-not (Test-Path -LiteralPath $FrontendDir)) {
        throw "Frontend directory not found: $FrontendDir"
    }

    Push-Location $FrontendDir
    try {
        if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir 'node_modules'))) {
            Write-Step 5 7 'Installing frontend dependencies'
            & $NpmCommand install
            if ($LASTEXITCODE -ne 0) {
                throw "npm install failed."
            }
        }
        else {
            Write-Step 5 7 'Frontend dependencies already installed'
        }

        Write-Step 6 7 'Building frontend assets'
        & $NpmCommand run build
        if ($LASTEXITCODE -ne 0) {
            throw "npm run build failed."
        }
    }
    finally {
        Pop-Location
    }
}

function Get-ProbeHost {
    param([string]$RequestedHost)

    if ([string]::IsNullOrWhiteSpace($RequestedHost)) {
        return '127.0.0.1'
    }

    if ($RequestedHost -in @('0.0.0.0', '::', '[::]', '*')) {
        return '127.0.0.1'
    }

    return $RequestedHost
}

function Test-ServiceEndpoint {
    param(
        [string]$RequestedHost,
        [int]$TargetPort
    )

    $probeHost = Get-ProbeHost -RequestedHost $RequestedHost
    $uri = "http://{0}:{1}/api/settings" -f $probeHost, $TargetPort

    try {
        $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 3
        return [bool]($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    }
    catch [System.Net.WebException] {
        if ($_.Exception.Response) {
            return $true
        }

        return $false
    }
    catch {
        return $false
    }
}

function Wait-ForServiceReady {
    param(
        [string]$RequestedHost,
        [int]$TargetPort,
        [int]$LauncherPid,
        [int]$TimeoutSec
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $owner = Get-PortOwner -TargetPort $TargetPort
        $ready = Test-ServiceEndpoint -RequestedHost $RequestedHost -TargetPort $TargetPort
        if ($ready) {
            if ($owner) {
                return $owner
            }

            $launcherProcess = Get-Process -Id $LauncherPid -ErrorAction SilentlyContinue
            if ($launcherProcess) {
                return [pscustomobject]@{
                    OwningPid = $launcherProcess.Id
                    ProcessName = $launcherProcess.ProcessName
                    LocalAddress = Get-ProbeHost -RequestedHost $RequestedHost
                    LocalPort = $TargetPort
                }
            }
        }

        $launcherProcess = Get-Process -Id $LauncherPid -ErrorAction SilentlyContinue
        if (-not $launcherProcess -and -not $owner) {
            return $null
        }

        Start-Sleep -Milliseconds 700
    }

    return $null
}

function Show-RecentLogs {
    param(
        [string]$StdoutPath,
        [string]$StderrPath,
        [int]$TailLines
    )

    if ($StdoutPath -and (Test-Path -LiteralPath $StdoutPath)) {
        Write-Section 'Recent Stdout'
        Get-Content -LiteralPath $StdoutPath -Tail $TailLines
    }

    if ($StderrPath -and (Test-Path -LiteralPath $StderrPath)) {
        Write-Section 'Recent Stderr'
        Get-Content -LiteralPath $StderrPath -Tail $TailLines
    }
}

function Stop-ServiceProcess {
    param($State)

    $pidCandidates = @()
    $managedPid = Get-StatePid -State $State
    $launcherPid = Get-StateLauncherPid -State $State

    if ($null -ne $managedPid) {
        $pidCandidates += $managedPid
    }
    if ($null -ne $launcherPid -and $launcherPid -ne $managedPid) {
        $pidCandidates += $launcherPid
    }

    if ($pidCandidates.Count -eq 0) {
        return $false
    }

    foreach ($candidatePid in ($pidCandidates | Select-Object -Unique)) {
        Stop-Process -Id $candidatePid -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 2

    foreach ($candidatePid in ($pidCandidates | Select-Object -Unique)) {
        $stillRunning = Get-Process -Id $candidatePid -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Stop-Process -Id $candidatePid -Force -ErrorAction SilentlyContinue
        }
    }

    Start-Sleep -Seconds 1

    foreach ($candidatePid in ($pidCandidates | Select-Object -Unique)) {
        if (Get-Process -Id $candidatePid -ErrorAction SilentlyContinue) {
            return $false
        }
    }

    return $true
}

function Show-Status {
    $state = Get-State -Path $StateFile
    $owner = Get-PortOwner -TargetPort $Port
    $managedProcess = Get-ManagedProcess -State $state

    Write-Section 'Service Status'

    if ($state -and $managedProcess -and $owner -and $owner.OwningPid -eq $state.pid) {
        $stateBindHost = Get-StateBindHost -State $state
        Write-Host 'State    : RUNNING'
        Write-Host ("URL      : http://{0}:{1}" -f $stateBindHost, $state.port)
        Write-Host ("PID      : {0}" -f (Get-StatePid -State $state))
        $launcherPid = Get-StateLauncherPid -State $state
        if ($null -ne $launcherPid -and $launcherPid -ne (Get-StatePid -State $state)) {
            Write-Host ("Launcher : {0}" -f $launcherPid)
        }
        Write-Host ("Process  : {0}" -f $owner.ProcessName)
        Write-Host ("Conda    : {0}" -f (Get-StateCondaEnv -State $state))
        Write-Host ("Started  : {0}" -f (Get-StatePropertyValue -State $state -Name 'startedAt'))
        Write-Host ("Stdout   : {0}" -f (Get-StatePropertyValue -State $state -Name 'stdoutLog'))
        Write-Host ("Stderr   : {0}" -f (Get-StatePropertyValue -State $state -Name 'stderrLog'))
        return
    }

    if ($state -and $managedProcess -and -not $owner) {
        Write-Host 'State    : STARTED BUT NOT LISTENING'
        Write-Host ("PID      : {0}" -f (Get-StatePid -State $state))
        Write-Host ("Conda    : {0}" -f (Get-StateCondaEnv -State $state))
        Write-Host ("Stdout   : {0}" -f (Get-StatePropertyValue -State $state -Name 'stdoutLog'))
        Write-Host ("Stderr   : {0}" -f (Get-StatePropertyValue -State $state -Name 'stderrLog'))
        return
    }

    if ($owner -and (-not $state -or $owner.OwningPid -ne (Get-StatePid -State $state))) {
        Write-Host 'State    : PORT IN USE BY ANOTHER PROCESS'
        Write-Host ("Port     : {0}" -f $Port)
        Write-Host ("PID      : {0}" -f $owner.OwningPid)
        Write-Host ("Process  : {0}" -f $owner.ProcessName)
        return
    }

    if ($state -and -not $managedProcess) {
        Write-Host 'State    : STOPPED (STALE STATE FILE)'
        Write-Host ("Port     : {0}" -f $state.port)
        Write-Host ("Last PID : {0}" -f (Get-StatePid -State $state))
        Write-Host ("Stdout   : {0}" -f (Get-StatePropertyValue -State $state -Name 'stdoutLog'))
        Write-Host ("Stderr   : {0}" -f (Get-StatePropertyValue -State $state -Name 'stderrLog'))
        return
    }

    Write-Host 'State    : STOPPED'
    Write-Host ("Port     : {0}" -f $Port)
}

function Start-Service {
    Ensure-Directory -Path $LogDir

    $state = Get-State -Path $StateFile
    $currentProcess = Get-ManagedProcess -State $state
    $portOwner = Get-PortOwner -TargetPort $Port

    if ($state -and $currentProcess -and $portOwner -and $portOwner.OwningPid -eq (Get-StatePid -State $state)) {
        $stateBindHost = Get-StateBindHost -State $state
        Write-Section 'Already Running'
        Write-Host ("Service is already running at http://{0}:{1}" -f $stateBindHost, $state.port)
        Write-Host ("PID      : {0}" -f (Get-StatePid -State $state))
        return
    }

    if ($state -and $currentProcess -and -not $portOwner) {
        [void](Stop-ServiceProcess -State $state)
        Remove-State -Path $StateFile
    }

    if ($state -and -not $currentProcess -and -not $portOwner) {
        Remove-State -Path $StateFile
    }

    if (-not (Test-PortAvailable -TargetPort $Port)) {
        $owner = Get-PortOwner -TargetPort $Port
        throw ("Port {0} is already in use by PID {1} ({2})." -f $Port, $owner.OwningPid, $owner.ProcessName)
    }

    Write-Section 'Codex Session Patcher Web UI'
    Write-Step 1 7 'Checking Conda'
    $condaExecutable = Resolve-CondaExecutable

    Write-Step 2 7 ("Resolving Conda environment '{0}'" -f $CondaEnv)
    $condaPrefix = Resolve-CondaPrefix -CondaExecutable $condaExecutable -EnvironmentName $CondaEnv
    $pythonExecutable = Join-Path $condaPrefix 'python.exe'
    if (-not (Test-Path -LiteralPath $pythonExecutable)) {
        throw "python.exe was not found in the selected Conda environment: $condaPrefix"
    }

    Write-Step 3 7 'Checking Python web dependencies'
    $hasWebDependencies = Test-WebDependencies -PythonExecutable $pythonExecutable
    if (-not $hasWebDependencies) {
        if ($InstallPythonDeps) {
            Install-PythonDependencies -PythonExecutable $pythonExecutable
        }
        else {
            throw ("Missing Python web dependencies in Conda environment '{0}'. Run `pip install -e "".[web]""` in that environment, or start the script with -InstallPythonDeps." -f $CondaEnv)
        }
    }

    Write-Step 4 7 'Checking Node.js toolchain'
    [void](Resolve-NodeCommand)
    $npmCommand = Resolve-NpmCommand

    if ($SkipFrontendBuild) {
        Write-Step 5 7 'Skipping frontend build'
        Write-Step 6 7 'Skipping frontend build'
    }
    else {
        Invoke-FrontendBuild -NpmCommand $npmCommand
    }

    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutLog = Join-Path $LogDir ("web-{0}-{1}.out.log" -f $Port, $timestamp)
    $stderrLog = Join-Path $LogDir ("web-{0}-{1}.err.log" -f $Port, $timestamp)

    Write-Step 7 7 ("Starting backend on http://{0}:{1}" -f $BindHost, $Port)
    $arguments = @(
        '-m', 'uvicorn', 'web.backend.main:app',
        '--host', $BindHost,
        '--port', [string]$Port
    )

    $process = Start-Process -FilePath $pythonExecutable `
        -ArgumentList $arguments `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru `
        -WindowStyle Hidden

    $serviceOwner = Wait-ForServiceReady -RequestedHost $BindHost -TargetPort $Port -LauncherPid $process.Id -TimeoutSec $StartupTimeoutSec
    if (-not $serviceOwner) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $portOwner = Get-PortOwner -TargetPort $Port
        if ($portOwner) {
            Stop-Process -Id $portOwner.OwningPid -Force -ErrorAction SilentlyContinue
        }
        Remove-State -Path $StateFile
        Write-Section 'Startup Failed'
        Show-RecentLogs -StdoutPath $stdoutLog -StderrPath $stderrLog -TailLines 40
        throw "The web service did not become ready on port $Port within $StartupTimeoutSec seconds."
    }

    $stateObject = [pscustomobject]@{
        bindHost = $BindHost
        port = $Port
        pid = $serviceOwner.OwningPid
        launcherPid = $process.Id
        condaEnv = $CondaEnv
        condaPrefix = $condaPrefix
        stdoutLog = $stdoutLog
        stderrLog = $stderrLog
        startedAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    }
    Save-State -Path $StateFile -State $stateObject

    Write-Section 'Started'
    Write-Host ("URL      : http://{0}:{1}" -f $BindHost, $Port)
    Write-Host ("PID      : {0}" -f $serviceOwner.OwningPid)
    if ($serviceOwner.OwningPid -ne $process.Id) {
        Write-Host ("Launcher : {0}" -f $process.Id)
    }
    Write-Host ("Conda    : {0}" -f $CondaEnv)
    Write-Host ("Stdout   : {0}" -f $stdoutLog)
    Write-Host ("Stderr   : {0}" -f $stderrLog)
    Write-Host ("State    : {0}" -f $StateFile)
}

function Stop-Service {
    $state = Get-State -Path $StateFile
    $owner = Get-PortOwner -TargetPort $Port

    Write-Section 'Stopping Service'

    if ($state) {
        $stopped = Stop-ServiceProcess -State $state
        if ($stopped) {
            Remove-State -Path $StateFile
            Write-Host ("Stopped managed service on port {0}." -f $Port)
            return
        }

        if (-not (Get-ManagedProcess -State $state)) {
            Remove-State -Path $StateFile
            Write-Host ("Removed stale state file for port {0}." -f $Port)
            return
        }

        Write-Host ("Managed service PID {0} did not stop cleanly." -f (Get-StatePid -State $state))
        return
    }

    if ($owner) {
        Write-Host ("Port {0} is in use by PID {1} ({2}), but it is not managed by this script." -f $Port, $owner.OwningPid, $owner.ProcessName)
        return
    }

    Write-Host ("No managed service is running on port {0}." -f $Port)
}

function Restart-Service {
    $state = Get-State -Path $StateFile
    $effectiveBindHost = $BindHost
    $effectiveCondaEnv = $CondaEnv

    if ($state) {
        if (-not $PSBoundParameters.ContainsKey('BindHost') -and -not $PSBoundParameters.ContainsKey('Host')) {
            $effectiveBindHost = Get-StateBindHost -State $state
        }
        if (-not $PSBoundParameters.ContainsKey('CondaEnv')) {
            $effectiveCondaEnv = Get-StateCondaEnv -State $state
        }
    }

    Stop-Service
    $script:BindHost = $effectiveBindHost
    $script:CondaEnv = $effectiveCondaEnv
    Start-Service
}

function Show-Logs {
    $state = Get-State -Path $StateFile
    if (-not $state) {
        throw "No managed service state file was found for port $Port."
    }

    $stdoutLog = Get-StatePropertyValue -State $state -Name 'stdoutLog'
    $stderrLog = Get-StatePropertyValue -State $state -Name 'stderrLog'

    if ($stdoutLog -and (Test-Path -LiteralPath $stdoutLog)) {
        Write-Section 'Stdout'
        if ($Follow) {
            Get-Content -LiteralPath $stdoutLog -Tail $LogTailLines -Wait
        }
        else {
            Get-Content -LiteralPath $stdoutLog -Tail $LogTailLines
        }
    }

    if ($stderrLog -and (Test-Path -LiteralPath $stderrLog)) {
        Write-Section 'Stderr'
        Get-Content -LiteralPath $stderrLog -Tail $LogTailLines
    }
}

switch ($Action) {
    'start' {
        Start-Service
    }
    'stop' {
        Stop-Service
    }
    'restart' {
        Restart-Service
    }
    'status' {
        Show-Status
    }
    'logs' {
        Show-Logs
    }
    default {
        throw "Unsupported action: $Action"
    }
}
