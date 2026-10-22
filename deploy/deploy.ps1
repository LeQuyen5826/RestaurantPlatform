# Triển khai bản publish lên IIS + dịch vụ API. Có -Rollback để quay về bản sao lưu gần nhất.
param(
  [string]$Source,
  [string]$Root = 'C:\wwwroot\booking',
  [string]$Service = 'BookingApi',
  [switch]$Rollback,
  [switch]$Seed   # chỉ lần đầu: nạp dữ liệu demo (thực đơn, bàn, tài khoản nhân sự)
)
$ErrorActionPreference = 'Stop'
$web = "$Root\web"; $api = "$Root\api"; $py = "$Root\venv\Scripts\python.exe"; $bakRoot = "$Root\backup"

function Copy-Dir($from, $to, $extra) {
  # /MIR đồng bộ (bản mới thay bản cũ); /XF /XD bảo vệ cấu hình và dữ liệu môi trường khỏi bị xóa
  robocopy $from $to /MIR @extra /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy $from -> $to that bai ($LASTEXITCODE)" }
  $global:LASTEXITCODE = 0
}
$keepApi = @('/XF', '.env', '*.db', '/XD', 'data', 'logs')

function Stop-Api {
  $s = Get-Service $Service -ErrorAction Stop
  if ($s.Status -ne 'Stopped') { Stop-Service $Service -Force; $s.WaitForStatus('Stopped', '00:00:30') }
}
function Start-Api { Start-Service $Service; (Get-Service $Service).WaitForStatus('Running', '00:00:30') }

if ($Rollback) {
  $last = Get-ChildItem $bakRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
  if (-not $last) { throw 'Khong co ban sao luu de rollback' }
  Write-Host "Rollback ve $($last.Name)"
  Stop-Api
  Copy-Dir "$($last.FullName)\api" $api $keepApi
  Copy-Dir "$($last.FullName)\web" $web @()
  Start-Api
  return
}

if (-not $Source -or -not (Test-Path "$Source\backend") -or -not (Test-Path "$Source\web")) { throw "Source khong hop le: $Source" }
if (-not (Test-Path "$api\.env")) { throw "Thieu $api\.env - chay deploy\setup-iis.ps1 truoc" }

# 1) Sao lưu bản đang chạy (giữ 3 bản gần nhất)
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = "$bakRoot\$stamp"
if ((Test-Path $api) -and (Test-Path $web)) {
  Copy-Dir $api "$bak\api" @('/XD', 'data', 'logs', '__pycache__', '/XF', '*.db')
  Copy-Dir $web "$bak\web" @()
}
Get-ChildItem $bakRoot -Directory | Sort-Object Name -Descending | Select-Object -Skip 3 | Remove-Item -Recurse -Force

# 2) Tạm ngừng API (file .py/.pyc đang được dùng) - vai trò tương tự app_offline.htm của ASP.NET Core
Stop-Api
try {
  # 3) Chép bản mới
  Copy-Dir "$Source\backend" $api $keepApi
  Copy-Dir "$Source\web" $web @()
  # 4) Cập nhật thư viện Python trong venv
  & $py -m pip install -r "$api\requirements.txt" --quiet --disable-pip-version-check
  if ($LASTEXITCODE -ne 0) { throw 'pip install that bai' }
  if ($Seed) { Push-Location $api; & $py -m app.seed; Pop-Location }
}
finally {
  # 5) Khởi động lại dù chép lỗi, để không bỏ dịch vụ ở trạng thái dừng
  Start-Api
}
Write-Host "Deploy xong ($stamp)"
