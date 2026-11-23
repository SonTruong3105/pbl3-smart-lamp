<#
.SYNOPSIS  Test trực tiếp Ollama trên Terminal để đo độ trễ
#>
param([string]$Root = "D:\Xiaozhi_server")
$ErrorActionPreference = "Stop"
Set-Location $Root

Write-Host "`n════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  TEST TỐC ĐỘ OLLAMA TRỰC TIẾP TRÊN TERMINAL" -ForegroundColor Cyan
Write-Host "════════════════════════════════════════════════════" -ForegroundColor Cyan

# Đọc file config để lấy đúng thông số
$yamlPath = if (Test-Path "config.yaml") { "config.yaml" } else { "server.yaml" }
$yaml = [System.IO.File]::ReadAllText($yamlPath, [System.Text.UTF8Encoding]::new($false))

# Regex lấy thông tin (Cách thủ công để tránh phụ thuộc thư viện YAML trong PowerShell)
$modelMatch = [regex]::Match($yaml, '(?s)ollama_chat:.*?model:\s*([^\s\n]+)')
$model = if ($modelMatch.Success) { $modelMatch.Groups[1].Value } else { "qwen3.5:2b" }

$sysPromptMatch = [regex]::Match($yaml, '(?s)system_prompt:\s*\|(.*?)(?=\n[A-Z]|\n#|\Z)')
$sysPrompt = if ($sysPromptMatch.Success) { $sysPromptMatch.Groups[1].Value.Trim() } else { "Bạn là trợ lý AI." }

# Loại bỏ {{current_time}} nếu vẫn còn sót
$sysPrompt = $sysPrompt -replace 'Giờ hiện tại:.*', ''

Write-Host "`n[1] Thông số test:" -ForegroundColor Yellow
Write-Host "  → Model: $model" -ForegroundColor White
Write-Host "  → System Prompt: $($sysPrompt.Length) ký tự" -ForegroundColor White

Write-Host "`n[2] LẦN 1: Gửi câu chat ĐẦU TIÊN (Cold Start)..." -ForegroundColor Yellow
$body = @{
    model = $model
    messages = @(
        @{role="system"; content=$sysPrompt},
        @{role="user"; content="chào bạn"}
    )
    stream = $false
    keep_alive = -1
    think = $false
    options = @{num_predict=150; num_ctx=2048; num_gpu=99; num_batch=256}
} | ConvertTo-Json -Depth 5

$t1 = Measure-Command {
    $r1 = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method POST -Body $body -ContentType "application/json"
}

Write-Host "  ⏱ Thời gian tổng: $([math]::Round($t1.TotalSeconds, 2))s"
Write-Host "     - Nạp Model (Load): $([math]::Round($r1.load_duration / 1e9, 2))s"
Write-Host "     - Đọc Prompt (Prefill): $([math]::Round($r1.prompt_eval_duration / 1e9, 2))s ($($r1.prompt_eval_count) tokens)"
Write-Host "     - Sinh chữ (Generate): $([math]::Round($r1.eval_duration / 1e9, 2))s ($($r1.eval_count) tokens)"

Write-Host "`n[3] LẦN 2: Gửi lại câu chat (Hot Cache)..." -ForegroundColor Yellow
Start-Sleep -Milliseconds 500
$t2 = Measure-Command {
    $r2 = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method POST -Body $body -ContentType "application/json"
}

Write-Host "  ⏱ Thời gian tổng: $([math]::Round($t2.TotalSeconds, 2))s"
Write-Host "     - Nạp Model (Load): $([math]::Round($r2.load_duration / 1e9, 2))s"
Write-Host "     - Đọc Prompt (Prefill): $([math]::Round($r2.prompt_eval_duration / 1e9, 2))s ($($r2.prompt_eval_count) tokens)"
Write-Host "     - Sinh chữ (Generate): $([math]::Round($r2.eval_duration / 1e9, 2))s ($($r2.eval_count) tokens)"

Write-Host "`n═══════════════════ KẾT LUẬN ═══════════════════════" -ForegroundColor Cyan
if ($t2.TotalSeconds -lt ($t1.TotalSeconds - 2)) {
    Write-Host "✅ THÀNH CÔNG! Lần 2 nhanh hơn lần 1 rất nhiều." -ForegroundColor Green
    Write-Host "   → Bộ nhớ đệm KV Cache đang hoạt động hoàn hảo." -ForegroundColor Green
    Write-Host "   → Nếu trên Web vẫn chậm, lỗi nằm ở code gửi History của Xiaozhi." -ForegroundColor Yellow
} else {
    Write-Host "❌ THẤT BẠI! Lần 2 vẫn chậm như lần 1." -ForegroundColor Red
    Write-Host "   → Ollama không lưu được Cache (có thể do thiếu VRAM)." -ForegroundColor Red
    Write-Host "   → Hoặc System Prompt chứa biến động (như {{current_time}})." -ForegroundColor Red
}
Write-Host "════════════════════════════════════════════════════"