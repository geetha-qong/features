# GPU Worker Setup for Windows
# Run once in PowerShell as Administrator from C:\qong_poc\
#
# Prerequisites:
#   - Python 3.11 installed (https://www.python.org/downloads/)
#   - NSSM installed: choco install nssm  OR  download from https://nssm.cc/download
#   - Tailscale connected and GCP VM visible at 100.127.190.88

$ErrorActionPreference = "Stop"
$REDIS_URL = "redis://100.127.190.88:6379/0"
$PYTHON = "C:\Python311\python.exe"
$WORKER_DIR = $PSScriptRoot | Split-Path -Parent   # parent of workers/
$WORKER_SCRIPT = Join-Path $WORKER_DIR "workers\gpu_worker.py"

Write-Host "=== Qong GPU Worker Setup ===" -ForegroundColor Cyan

# ── 1. Install Python deps ─────────────────────────────────────────────────────
Write-Host "[1/4] Installing Python dependencies..."
& $PYTHON -m pip install --upgrade rq redis requests

# ── 2. Test Redis connectivity ─────────────────────────────────────────────────
Write-Host "[2/4] Testing Redis at $REDIS_URL ..."
$result = & $PYTHON -c "import redis; r=redis.Redis.from_url('$REDIS_URL'); print(r.ping())"
if ($result -ne "True") {
    Write-Host "ERROR: Cannot reach Redis. Is Tailscale connected?" -ForegroundColor Red
    exit 1
}
Write-Host "  Redis OK" -ForegroundColor Green

# ── 3. Install NSSM service ────────────────────────────────────────────────────
Write-Host "[3/4] Installing NSSM service 'QongGpuWorker'..."
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $nssm) {
    Write-Host "  NSSM not found. Install with: choco install nssm" -ForegroundColor Yellow
    Write-Host "  Then re-run this script." -ForegroundColor Yellow
    exit 1
}

nssm install QongGpuWorker $PYTHON $WORKER_SCRIPT
nssm set QongGpuWorker AppDirectory $WORKER_DIR
nssm set QongGpuWorker AppEnvironmentExtra "REDIS_URL=$REDIS_URL"
nssm set QongGpuWorker AppStdout "C:\qong_logs\gpu_worker.log"
nssm set QongGpuWorker AppStderr "C:\qong_logs\gpu_worker_err.log"
nssm set QongGpuWorker AppRotateFiles 1
nssm set QongGpuWorker AppRotateSeconds 86400

New-Item -ItemType Directory -Force -Path "C:\qong_logs" | Out-Null

# ── 4. Start service ───────────────────────────────────────────────────────────
Write-Host "[4/4] Starting QongGpuWorker service..."
nssm start QongGpuWorker
Start-Sleep -Seconds 3
nssm status QongGpuWorker

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host "  Logs: C:\qong_logs\gpu_worker.log"
Write-Host "  Stop:    nssm stop QongGpuWorker"
Write-Host "  Restart: nssm restart QongGpuWorker"
Write-Host "  Remove:  nssm remove QongGpuWorker confirm"
