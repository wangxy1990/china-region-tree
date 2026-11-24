# 首次发布：GitHub 设备授权 -> REST API 提交 -> 开启 Pages
# pwsh -NoProfile -File tools\publish_via_api.ps1
$ErrorActionPreference = 'Continue'
$root = 'D:\agent-workspace\china-region-tree'
$log  = Join-Path $root 'out\_push.log'
'' | Set-Content $log -Encoding utf8
function Log($m) { $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; Add-Content $log $line -Encoding utf8; Write-Output $m }

$owner = 'wangxy1990'
$repo  = 'china-region-tree'
$api   = "https://api.github.com/repos/$owner/$repo"
$clientId = 'Ov23liVJ6tn0IzlKYyFE'
$UA = @{ 'User-Agent' = 'region-tree' }

# 1) 申请设备码
$code = $null
for ($i = 0; $i -lt 8; $i++) {
    try {
        $code = Invoke-RestMethod -Uri 'https://github.com/login/device/code' -Method Post -Headers @{ Accept = 'application/json'; 'User-Agent' = 'region-tree' } `
            -Body @{ client_id = $clientId; scope = 'repo' } -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 25
        break
    } catch { Start-Sleep 3 }
}
if (-not $code) { Log '拿不到设备码'; exit 1 }
Log ("USER_CODE=" + $code.user_code)
Log ("URL=" + $code.verification_uri)

# 2) 轮询换取 token
$token = $null
for ($i = 0; $i -lt 120; $i++) {
    try {
        $r = Invoke-RestMethod -Uri 'https://github.com/login/oauth/access_token' -Method Post -Headers @{ Accept = 'application/json'; 'User-Agent' = 'region-tree' } `
            -Body @{ client_id = $clientId; device_code = $code.device_code; grant_type = 'urn:ietf:params:oauth:grant-type:device_code' } `
            -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 25
    } catch { Start-Sleep 5; continue }
    if ($r.access_token) { $token = $r.access_token; Log ("授权成功，scope=" + $r.scope); break }
    if ($r.error -in @('authorization_pending', 'slow_down')) { Start-Sleep 5; continue }
    Log ("授权失败: " + $r.error + " " + $r.error_description); exit 1
}
if (-not $token) { Log '等待授权超时'; exit 1 }

$H = @{ 'User-Agent' = 'region-tree'; Authorization = "token $token"; Accept = 'application/vnd.github+json' }

# 2.5) 校验权限
try {
    $me = Invoke-RestMethod -Uri 'https://api.github.com/user' -Headers $H -TimeoutSec 30
    Log ("登录账号: " + $me.login)
} catch { Log ("取用户信息失败: " + $_.Exception.Message) }

# 3) 上传 blob
$files = & git -C $root ls-files | Where-Object { $_ -and $_ -notlike '.git*' }
Log ("文件数: " + @($files).Count)
$entries = New-Object System.Collections.ArrayList
foreach ($f in $files) {
    $full = Join-Path $root ($f -replace '/', '\')
    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($full))
    $payload = @{ content = $b64; encoding = 'base64' } | ConvertTo-Json -Depth 3
    try {
        $b = Invoke-RestMethod -Uri "$api/git/blobs" -Method Post -Headers $H -Body $payload -ContentType 'application/json; charset=utf-8' -TimeoutSec 60
        [void]$entries.Add(@{ path = ($f -replace '\', '/'); mode = '100644'; type = 'blob'; sha = $b.sha })
    } catch {
        Log ("blob 失败: $f -> " + $_.Exception.Message + " | " + $_.ErrorDetails.Message)
        exit 1
    }
}
Log ("blob 完成: " + $entries.Count)

# 4) tree / commit / ref
try {
    $tree = Invoke-RestMethod -Uri "$api/git/trees" -Method Post -Headers $H -Body (@{ tree = @($entries) } | ConvertTo-Json -Depth 6) -ContentType 'application/json; charset=utf-8' -TimeoutSec 60
    $commitBody = @{
        message = 'init: 全国省市区结构树 Java + 车牌代号 + 每周自动更新与 Pages 工作流'
        tree = $tree.sha
        author = @{ name = 'region-tree'; email = 'region-tree@users.noreply.github.com' }
        committer = @{ name = 'region-tree'; email = 'region-tree@users.noreply.github.com' }
    } | ConvertTo-Json -Depth 6
    $commit = Invoke-RestMethod -Uri "$api/git/commits" -Method Post -Headers $H -Body $commitBody -ContentType 'application/json; charset=utf-8' -TimeoutSec 60
    Log ("commit=" + $commit.sha)
    try {
        Invoke-RestMethod -Uri "$api/git/refs" -Method Post -Headers $H -Body (@{ ref = 'refs/heads/main'; sha = $commit.sha } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 60 | Out-Null
        Log 'main 分支已创建'
    } catch {
        Invoke-RestMethod -Uri "$api/git/refs/heads/main" -Method Patch -Headers $H -Body (@{ sha = $commit.sha; force = $true } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 60 | Out-Null
        Log 'main 分支已更新'
    }
} catch { Log ("提交失败: " + $_.Exception.Message + " | " + $_.ErrorDetails.Message); exit 1 }

# 5) Pages
try {
    Invoke-RestMethod -Uri "$api/pages" -Method Post -Headers $H -Body (@{ build_type = 'workflow' } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 60 | Out-Null
    Log 'Pages 开启（workflow 构建）'
} catch { Log ("Pages: " + $_.Exception.Message + " | " + $_.ErrorDetails.Message) }

# 6) 首次触发工作流
try {
    Invoke-RestMethod -Uri "$api/actions/workflows/update.yml/dispatches" -Method Post -Headers $H -Body (@{ ref = 'main' } | ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 60 | Out-Null
    Log '已触发首次部署'
} catch { Log ("触发失败: " + $_.Exception.Message + " | " + $_.ErrorDetails.Message) }

Log 'DONE'

