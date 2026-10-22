#Requires -RunAsAdministrator
# Chạy MỘT LẦN trên máy chủ (PowerShell quyền Administrator).
# Điều kiện: đã bật IIS (+ WebSocket Protocol), cài URL Rewrite và Application Request Routing (ARR), Python 3.12, NSSM.
param(
  [string]$Root = 'C:\wwwroot\booking',
  [string]$Nssm = 'C:\tools\nssm\nssm.exe',
  [string]$JenkinsAccount = 'NT AUTHORITY\SYSTEM',   # tài khoản chạy dịch vụ Jenkins
  [string]$PublicUrl = 'http://localhost/booking'
)
$ErrorActionPreference = 'Stop'
Import-Module WebAdministration

# 1) Thư mục triển khai
New-Item -ItemType Directory -Force "$Root\web", "$Root\api", "$Root\data", "$Root\logs", "$Root\backup" | Out-Null

# 2) Python venv (nằm ngoài thư mục api để /MIR không xóa)
if (-not (Test-Path "$Root\venv\Scripts\python.exe")) { & py -3.12 -m venv "$Root\venv" }

# 3) Application Pool "No Managed Code" + ứng dụng /booking dưới Default Web Site
if (-not (Test-Path IIS:\AppPools\BookingPool)) { New-WebAppPool -Name BookingPool | Out-Null }
Set-ItemProperty IIS:\AppPools\BookingPool -Name managedRuntimeVersion -Value ''
if (-not (Get-WebApplication -Site 'Default Web Site' -Name booking)) {
  New-WebApplication -Name booking -Site 'Default Web Site' -PhysicalPath "$Root\web" -ApplicationPool BookingPool | Out-Null
}

# 4) Bật proxy của ARR (cần cho rule rewrite sang http://127.0.0.1:8000)
Set-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Filter 'system.webServer/proxy' -Name enabled -Value $true

# 5) Phân quyền: Jenkins được ghi; app pool chỉ đọc web
icacls $Root /grant "${JenkinsAccount}:(OI)(CI)M" /T | Out-Null
icacls "$Root\web" /grant "IIS AppPool\BookingPool:(OI)(CI)RX" /T | Out-Null

# 6) .env môi trường (không bị deploy ghi đè). Khóa bí mật sinh ngẫu nhiên.
$envFile = "$Root\api\.env"
if (-not (Test-Path $envFile)) {
  function Rand($n) { $b = New-Object byte[] $n; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); return $b }
  $fernet = [Convert]::ToBase64String((Rand 32)).Replace('+', '-').Replace('/', '_')
  $dbPath = ("$Root\data\booking.db").Replace('\', '/')
  @"
DATABASE_URL=sqlite:///$dbPath
JWT_SECRET=$([Convert]::ToBase64String((Rand 32)))
QR_SECRET=$([Convert]::ToBase64String((Rand 32)))
DATA_KEY=$fernet
PUBLIC_URL=$PublicUrl
CORS_ORIGINS=$PublicUrl
SEPAY_API_KEY=$([Convert]::ToBase64String((Rand 24)))
BANK_CODE=MBBank
BANK_ACCOUNT=0000000000
"@ | Set-Content $envFile -Encoding ascii
  Write-Host "Da tao $envFile - sua BANK_ACCOUNT / SEPAY_API_KEY, dung PostgreSQL neu chay that."
}

# 7) Dịch vụ Windows cho FastAPI (NSSM)
if (-not (Get-Service BookingApi -ErrorAction SilentlyContinue)) {
  & $Nssm install BookingApi "$Root\venv\Scripts\python.exe" "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
  & $Nssm set BookingApi AppDirectory "$Root\api"
  & $Nssm set BookingApi Start SERVICE_AUTO_START
  & $Nssm set BookingApi AppStdout "$Root\logs\api.out.log"
  & $Nssm set BookingApi AppStderr "$Root\logs\api.err.log"
  & $Nssm set BookingApi AppRotateFiles 1
}
Write-Host 'Setup xong. Lan deploy dau tien chay them -Seed neu muon du lieu demo.'
