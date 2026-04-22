param(
    [int]$Duration = 900,
    [double]$Interval = 2.0,
    [string]$SavePolicy = "changes",
    [switch]$SaveCrops,
    [switch]$CaptureOutsideBattle
)

$env:PYTHONIOENCODING = "utf-8"
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"

$srcDir = Join-Path $PSScriptRoot 'src'
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcDir;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcDir
}

$arguments = @(
    "battle_debug_recorder.py",
    "--duration", $Duration,
    "--interval", $Interval,
    "--save-policy", $SavePolicy,
    "--vote-frames", "1",
    "--vote-interval", "0",
    "--unknown-retries", "0"
)

if ($SaveCrops) {
    $arguments += "--save-crops"
}

if ($CaptureOutsideBattle) {
    $arguments += "--capture-outside-battle"
}

python @arguments
