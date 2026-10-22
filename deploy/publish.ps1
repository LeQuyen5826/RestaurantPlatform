# Gom bản publish: publish\backend (mã FastAPI) + publish\web (frontend đã build, kèm web.config)
$ErrorActionPreference = 'Stop'
$ws = $env:WORKSPACE
$pub = Join-Path $ws 'publish'
if (Test-Path $pub) { Remove-Item $pub -Recurse -Force }
New-Item -ItemType Directory -Force "$pub\backend", "$pub\web" | Out-Null

robocopy "$ws\backend" "$pub\backend" /E /XD tests __pycache__ .pytest_cache .venv /XF *.db .env test-results.xml /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy backend that bai ($LASTEXITCODE)" }
robocopy "$ws\frontend\dist" "$pub\web" /E /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy web that bai ($LASTEXITCODE)" }
if (-not (Test-Path "$pub\web\web.config")) { throw 'Thieu web.config trong ban build' }
if (-not (Test-Path "$pub\web\index.html")) { throw 'Thieu index.html trong ban build' }
$global:LASTEXITCODE = 0
Write-Host "Publish xong: $pub"
