param(
    [double]$Interval = 3.0,
    [double]$Duration = 0.0
)

$env:PYTHONIOENCODING = "utf-8"
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"

$srcDir = Join-Path $PSScriptRoot 'src'
$entryScript = Join-Path $PSScriptRoot 'screenshot_sampler.py'
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcDir;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $srcDir
}

$arguments = @(
    $entryScript,
    "--interval", $Interval,
    "--duration", $Duration
)

python @arguments
