# Kiểm tra sau triển khai: API sống, trang chủ trả HTML của app, đường dẫn con (SPA) không 404.
param([string]$BaseUrl = 'http://localhost/booking', [int]$Retries = 20)
$ErrorActionPreference = 'Stop'
foreach ($i in 1..$Retries) {
  try {
    $h = Invoke-RestMethod "$BaseUrl/api/health" -TimeoutSec 5
    $page = Invoke-WebRequest "$BaseUrl/" -UseBasicParsing -TimeoutSec 5
    $spa = Invoke-WebRequest "$BaseUrl/login" -UseBasicParsing -TimeoutSec 5
    if ($h.ok -and $page.StatusCode -eq 200 -and $page.Content -match 'id="root"' -and $spa.StatusCode -eq 200) {
      Write-Host "Verify OK (lan $i)"; exit 0
    }
  } catch { Write-Host "Lan $i chua san sang: $($_.Exception.Message)" }
  Start-Sleep -Seconds 3
}
Write-Error 'Verify that bai'
exit 1
