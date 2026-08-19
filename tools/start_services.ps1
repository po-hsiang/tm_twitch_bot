# 啟動 Bot 相依的四個本機微服務，並確認它們真的活著。
#
# 平常不需要用：四個服務的 restart 政策會讓它們隨 Docker Desktop 自動復原。
# 這支是給「重建機器」或「懷疑某個沒起來」時用的。
#
#   .\tools\start_services.ps1          啟動 + 檢查
#   .\tools\start_services.ps1 -Check   只檢查，不啟動
#
# 服務清單與各自的職責見 docs/SERVICES.md。
# n8n 刻意不在這裡：它是多客戶端共用的服務，生命週期跟這個 Bot 無關。

param(
    [switch]$Check,
    # 四個服務的專案根目錄。搬家的話只改這一行。
    [string]$Root = 'C:\Dev\GoProjects'
)

$Services = @(
    @{ Name = 'google-sheets-svc'; Port = 9091; Role = '指令集／轉職表／文案' }
    @{ Name = 'openai-svc';        Port = 9092; Role = '!pk 對戰旁白（僅此一項）' }
    @{ Name = 'mongo-atlas-svc';   Port = 9093; Role = '所有持久化資料' }
    @{ Name = 'youtube-svc';       Port = 9094; Role = '虎喵歌單' }
)

function Test-Service {
    param([int]$Port)
    # 所有服務的根路徑都回 404（Go mux 預設），所以改打一定存在的 Swagger 頁。
    # 拿到任何 HTTP 回應就代表它在聽了。
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$Port/docs/index.html" `
            -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not $Check) {
    foreach ($svc in $Services) {
        $dir = Join-Path $Root $svc.Name
        if (-not (Test-Path $dir)) {
            Write-Host "✗ 找不到 $dir —— 專案搬家了嗎？（見 docs/SERVICES.md）" -ForegroundColor Red
            continue
        }
        Write-Host "→ 啟動 $($svc.Name) ..." -ForegroundColor Cyan
        Push-Location $dir
        # compose 檔名不一致（有的 compose.yaml、有的 docker-compose.yaml），
        # 但 docker compose 兩種都認得，所以不必指定 -f
        docker compose up -d
        Pop-Location
    }
    Write-Host ''
}

Write-Host '檢查服務狀態：' -ForegroundColor Cyan
$failed = @()
foreach ($svc in $Services) {
    if (Test-Service -Port $svc.Port) {
        Write-Host ("  OK   {0,-20} :{1}  {2}" -f $svc.Name, $svc.Port, $svc.Role) -ForegroundColor Green
    } else {
        Write-Host ("  DOWN {0,-20} :{1}  {2}" -f $svc.Name, $svc.Port, $svc.Role) -ForegroundColor Red
        $failed += $svc.Name
    }
}

if ($failed.Count -eq 0) {
    Write-Host "`n四個服務都正常，可以開 Bot 了。" -ForegroundColor Green
    exit 0
}

Write-Host "`n有 $($failed.Count) 個沒起來：$($failed -join '、')" -ForegroundColor Yellow
Write-Host '  docker ps -a   看容器狀態' -ForegroundColor Yellow
Write-Host '  docker logs <container>   看失敗原因' -ForegroundColor Yellow
if ($failed -contains 'openai-svc') {
    # 這個服務的 restart 政策是 on-failure:5，和其他三個的 unless-stopped 不同
    Write-Host "`n注意：openai-svc 的 restart 政策是 on-failure:5 —— 連續失敗 5 次" -ForegroundColor Yellow
    Write-Host '      就會放棄並保持停止，而且不會有任何通知。' -ForegroundColor Yellow
}
Write-Host "`n（Bot 少了 9091 會降級啟動；少了其他三個只會讓對應指令失效）" -ForegroundColor DarkGray
exit 1
