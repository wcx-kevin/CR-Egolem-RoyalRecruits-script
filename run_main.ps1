param(
    [string]$DeviceId = $env:CR_DEVICE_ID,
    [string]$AdbExe = $env:CR_ADB_EXE,
    [string]$Deck = $env:CR_DECK,
    [switch]$DirectBattle,
    [string]$TimeStage = $env:CR_DIRECT_TIME_STAGE,
    [string]$ElixirStage = $env:CR_DIRECT_ELIXIR_STAGE,
    [switch]$Init,
    [switch]$SkipDoctor,
    [switch]$RunAfterInit
)

$srcDir = Join-Path $PSScriptRoot 'src'
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcDir;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcDir
}

$defaultTencentAdb = 'E:\Program Files\Tencent\GameAssist\Application\6.10.5410.485\adb.exe'
$defaultMuMuAdb = 'E:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe'

if (-not $AdbExe -and (Test-Path $defaultMuMuAdb)) {
    $AdbExe = $defaultMuMuAdb
}

if (-not $AdbExe -and (Test-Path $defaultTencentAdb)) {
    $AdbExe = $defaultTencentAdb
}

if ($AdbExe) {
    $env:CR_ADB_EXE = $AdbExe
    $adbDir = Split-Path -Parent $AdbExe
    if ($adbDir -and ($env:PATH -notlike "*$adbDir*")) {
        $env:PATH = "$adbDir;$env:PATH"
    }
}

if ($DeviceId) {
    $env:CR_DEVICE_ID = $DeviceId
}

function Resolve-DeckId {
    param(
        [string]$Value
    )

    if (-not $Value) {
        return $null
    }

    $normalized = ($Value.ToLower() -replace '[^a-z0-9]', '')
    switch ($normalized) {
        'elixirgolem' { return 'elixir_golem' }
        'egolem' { return 'elixir_golem' }
        'royalrecruits' { return 'royal_recruits' }
        'rr' { return 'royal_recruits' }
        default { return $null }
    }
}

if (-not $Deck) {
    $Deck = Read-Host 'Select deck [elixir_golem/e_golem / royal_recruits/rr]'
}

$resolvedDeck = Resolve-DeckId -Value $Deck
if (-not $resolvedDeck) {
    Write-Host "Unsupported deck '$Deck'. Use elixir_golem/e_golem or royal_recruits/rr." -ForegroundColor Yellow
    exit 1
}

$env:CR_DECK = $resolvedDeck

function Get-AdbDevices {
    if ($env:CR_ADB_EXE) {
        return & $env:CR_ADB_EXE devices
    }

    return adb devices
}

function Invoke-AdbConnect {
    param(
        [string]$Target
    )

    if (-not $Target -or ($Target -notmatch ':')) {
        return
    }

    Write-Host "Trying adb connect $Target ..."
    if ($env:CR_ADB_EXE) {
        & $env:CR_ADB_EXE connect $Target | ForEach-Object { Write-Host $_ }
    } else {
        adb connect $Target | ForEach-Object { Write-Host $_ }
    }
}

Write-Host "CR_ADB_EXE=$env:CR_ADB_EXE"
Write-Host "CR_DEVICE_ID=$env:CR_DEVICE_ID"
Write-Host "CR_DECK=$env:CR_DECK"
if ($DirectBattle) {
    Write-Host "CR_DIRECT_BATTLE=True"
    if ($TimeStage) {
        Write-Host "CR_DIRECT_TIME_STAGE=$TimeStage"
    }
    if ($ElixirStage) {
        Write-Host "CR_DIRECT_ELIXIR_STAGE=$ElixirStage"
    }
}

$deviceOutput = Get-AdbDevices
$deviceOutput | ForEach-Object { Write-Host $_ }

$onlineDevice = $deviceOutput | Select-String -Pattern '^\S+\s+device$' | Select-Object -First 1
if (-not $onlineDevice) {
    Invoke-AdbConnect -Target $env:CR_DEVICE_ID
    $deviceOutput = Get-AdbDevices
    $deviceOutput | ForEach-Object { Write-Host $_ }
    $onlineDevice = $deviceOutput | Select-String -Pattern '^\S+\s+device$' | Select-Object -First 1
}

if (-not $onlineDevice) {
    Write-Host 'No online adb device. Open MuMu or another ADB-capable emulator, wait until Android is fully loaded, then run this script again.' -ForegroundColor Yellow
    exit 1
}

if (-not $env:CR_DEVICE_ID) {
    $env:CR_DEVICE_ID = ($onlineDevice.ToString().Split()[0])
    Write-Host "Auto detected device: $env:CR_DEVICE_ID"
}

if ($Init) {
    python -m uiautomator2 init --serial $env:CR_DEVICE_ID
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    if (-not $RunAfterInit) {
        exit 0
    }
}

python -c "from cr_bot.config.device_config import ADB_EXE, DEVICE_ID; print(f'Using ADB: {ADB_EXE}'); print(f'Using Device: {DEVICE_ID}')"
if (-not $SkipDoctor) {
    python .\doctor.py --strict-resolution --deck $env:CR_DECK
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$pythonArgs = @(".\\main.py", "--deck", $env:CR_DECK)

if ($DirectBattle) {
    $pythonArgs += "--direct-battle"
    if ($TimeStage) {
        $env:CR_DIRECT_TIME_STAGE = $TimeStage
        $pythonArgs += @("--time-stage", $TimeStage)
    }
    if ($ElixirStage) {
        $env:CR_DIRECT_ELIXIR_STAGE = $ElixirStage
        $pythonArgs += @("--elixir-stage", $ElixirStage)
    }
}

python @pythonArgs
