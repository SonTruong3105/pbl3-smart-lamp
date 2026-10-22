<#
.SYNOPSIS
    Dọn dẹp thư mục my-xiaozhi — phiên bản tối ưu tốc độ.
.DESCRIPTION
    Quét cây thư mục 1 lần duy nhất, cache kết quả, tính size bằng walk-up parent.
    Chạy nhanh gấp 20-50 lần so với bản dùng Get-ChildItem -Recurse.
.PARAMETER Path
    Đường dẫn thư mục my-xiaozhi. Mặc định: D:\my-xiaozhi
.PARAMETER Mode
    Safe | Standard | Aggressive. Mặc định: Standard
.PARAMETER DryRun
    Chỉ báo cáo, không xóa thật.
.PARAMETER Backup
    Sao lưu files sắp xóa vào thư mục _backup.
.PARAMETER SkipHeavy
    Bỏ qua venv/node_modules khi scan (nhanh hơn nhưng không xóa được chúng).
.EXAMPLE
    .\Clean-Xiaozhi.ps1 -Mode Safe -DryRun
    .\Clean-Xiaozhi.ps1 -Mode Standard -Backup
    .\Clean-Xiaozhi.ps1 -Mode Aggressive -SkipHeavy:$false
#>

param(
    [string]$Path = "D:\my-xiaozhi",
    [ValidateSet("Safe", "Standard", "Aggressive")]
    [string]$Mode = "Standard",
    [switch]$DryRun,
    [switch]$Backup,
    [switch]$SkipHeavy = $true
)

$ErrorActionPreference = "SilentlyContinue"
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# =====================================================
# CẤU HÌNH TARGETS
# =====================================================

$Targets = @{
    Safe = @{
        Files = @(
            "*.pyc", "*.pyo", "*.pyd",
            "*.log", "*.tmp", "*.bak", "*.backup", "*.old",
            "*.swp", "*.swo", "*~"
        )
        Dirs = @(
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".cache",
            "tmp",
            ".ipynb_checkpoints"
        )
    }
    Standard = @{
        Files = @(
            "*.pyc", "*.pyo", "*.pyd",
            "*.log", "*.tmp", "*.bak", "*.backup", "*.old",
            "*.swp", "*.swo", "*~",
            "*.db-journal", "*.db-wal", "*.db-shm"
        )
        Dirs = @(
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".cache",
            "tmp",
            ".ipynb_checkpoints",
            "build",
            "dist",
            ".idea",
            ".vs",
            ".pio",
            "node_modules"
        )
    }
    Aggressive = @{
        Files = @(
            "*.pyc", "*.pyo", "*.pyd",
            "*.log", "*.tmp", "*.bak", "*.backup", "*.old",
            "*.swp", "*.swo", "*~",
            "*.db-journal", "*.db-wal", "*.db-shm",
            "*.wav", "*.mp3", "*.opus",
            "*.exe"
        )
        Dirs = @(
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".cache",
            "tmp",
            ".ipynb_checkpoints",
            "logs",
            "build",
            "dist",
            ".idea",
            ".vs",
            ".pio",
            "node_modules",
            "venv",
            "venv-vieneu",
            ".venv",
            "asr\venv",
            "SearXNGforWindows-main",
            "data\audio"
        )
    }
}

$Config = $Targets[$Mode]

# Danh sách dir nặng — bỏ qua khi scan nếu -SkipHeavy
$HeavyDirNames = @(
    "venv", "venv-vieneu", ".venv",
    "node_modules",
    "SearXNGforWindows-main",
    "__pycache__"
)

# =====================================================
# HELPERS
# =====================================================

function Format-Size {
    param([long]$Bytes)
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

function Test-ShouldSkipScan {
    param([string]$DirName)
    if (-not $SkipHeavy) { return $false }
    foreach ($h in $HeavyDirNames) {
        if ($DirName -ieq $h) { return $true }
    }
    return $false
}

# =====================================================
# BẮT ĐẦU
# =====================================================

Write-Host ""
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  XIAOZHI CLEANUP (Optimized v2)" -ForegroundColor Cyan
Write-Host "  Path:    $Path" -ForegroundColor Cyan
Write-Host "  Mode:    $Mode" -ForegroundColor Cyan
Write-Host "  DryRun:  $DryRun  |  Backup: $Backup  |  SkipHeavy: $SkipHeavy" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $Path)) {
    Write-Host "❌ Không tìm thấy thư mục: $Path" -ForegroundColor Red
    exit 1
}

# =====================================================
# QUÉT CÂY THƯ MỤC (1 LẦN DUY NHẤT)
# =====================================================

Write-Host "🔍 Đang quét cây thư mục..." -ForegroundColor Yellow
$scanSw = [System.Diagnostics.Stopwatch]::StartNew()

$allFiles = [System.Collections.Generic.List[object]]::new()
$allDirs = [System.Collections.Generic.List[object]]::new()
$skippedDirs = [System.Collections.Generic.List[string]]::new()

$stack = [System.Collections.Generic.Stack[string]]::new()
$stack.Push($Path)

while ($stack.Count -gt 0) {
    $current = $stack.Pop()

    # Bỏ qua dir nặng nếu SkipHeavy
    $currentName = [System.IO.Path]::GetFileName($current)
    if ($currentName -and (Test-ShouldSkipScan $currentName)) {
        $skippedDirs.Add($current)
        continue
    }

    try {
        # Liệt kê files trong dir hiện tại
        foreach ($f in [System.IO.Directory]::EnumerateFiles($current)) {
            $fi = [System.IO.FileInfo]::new($f)
            $allFiles.Add([PSCustomObject]@{
                FullName = $fi.FullName
                Name     = $fi.Name
                Length   = $fi.Length
            })
        }
        # Liệt kê subdirs
        foreach ($d in [System.IO.Directory]::EnumerateDirectories($current)) {
            $allDirs.Add([PSCustomObject]@{
                FullName = $d
                Name     = [System.IO.Path]::GetFileName($d)
            })
            $stack.Push($d)
        }
    } catch {
        # Bỏ qua lỗi permission
    }
}

$scanElapsed = $scanSw.Elapsed.TotalSeconds
Write-Host ("✅ Quét xong: {0:N0} files, {1:N0} dirs trong {2:N1}s" -f `
    $allFiles.Count, $allDirs.Count, $scanElapsed) -ForegroundColor Green

if ($skippedDirs.Count -gt 0) {
    Write-Host ("   ⏭  Đã bỏ qua {0} dir nặng (venv, node_modules, ...)" -f $skippedDirs.Count) -ForegroundColor Gray
}
Write-Host ""

# Tính size ban đầu (từ cache)
$sizeBefore = ($allFiles | Measure-Object -Property Length -Sum).Sum
Write-Host "📊 Kích thước hiện tại: $(Format-Size $sizeBefore)" -ForegroundColor Yellow
if ($SkipHeavy -and $skippedDirs.Count -gt 0) {
    Write-Host "   (chưa tính các dir đã bỏ qua — chạy với -SkipHeavy:`$false để scan hết)" -ForegroundColor Gray
}
Write-Host ""

# =====================================================
# LỌC FILE VÀ DIR CẦN XÓA
# =====================================================

Write-Host "🎯 Đang lọc file/dir cần xóa..." -ForegroundColor Yellow

# Pre-compile regex cho file patterns
$fileRegexes = $Config.Files | ForEach-Object {
    $p = $_.Replace(".", "\.").Replace("*", ".*")
    [regex]::new("^$p$", "IgnoreCase")
}

# Set tên dir cần xóa
$dirNameSet = [System.Collections.Generic.HashSet[string]]::new(
    [string[]]$Config.Dirs,
    [System.StringComparer]::OrdinalIgnoreCase
)

# Lọc files
$filesToDelete = [System.Collections.Generic.List[object]]::new()
foreach ($f in $allFiles) {
    foreach ($re in $fileRegexes) {
        if ($re.IsMatch($f.Name)) {
            $filesToDelete.Add($f)
            break
        }
    }
}

# Lọc dirs — chỉ lấy dir khớp tên
$matchedDirs = [System.Collections.Generic.List[object]]::new()
foreach ($d in $allDirs) {
    if ($dirNameSet.Contains($d.Name)) {
        $matchedDirs.Add($d)
    }
}

# Loại bỏ dir con nằm trong dir cha (chỉ giữ dir cha cao nhất)
# Sắp xếp theo độ dài path tăng dần
$matchedDirs = $matchedDirs | Sort-Object { $_.FullName.Length }
$finalDirs = [System.Collections.Generic.List[object]]::new()
foreach ($d in $matchedDirs) {
    $isChild = $false
    foreach ($parent in $finalDirs) {
        if ($d.FullName.StartsWith($parent.FullName + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            $isChild = $true
            break
        }
    }
    if (-not $isChild) {
        $finalDirs.Add($d)
    }
}

# =====================================================
# TÍNH SIZE CẦN XÓA (TỐI ƯU - WALK-UP PARENT)
# =====================================================

Write-Host "📐 Đang tính dung lượng..." -ForegroundColor Yellow
$calcSw = [System.Diagnostics.Stopwatch]::StartNew()

# Set các path sẽ xóa để check nhanh O(1)
$deletePaths = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($d in $finalDirs) { [void]$deletePaths.Add($d.FullName) }
foreach ($f in $filesToDelete) { [void]$deletePaths.Add($f.FullName) }

# Khởi tạo size = 0 cho từng dir
$dirSizes = @{}
foreach ($d in $finalDirs) { $dirSizes[$d.FullName] = [long]0 }

# Mỗi file: walk-up parent, dừng khi match dir trong deletePaths
$dirSizeTotal = [long]0
$pathLen = $Path.Length

foreach ($f in $allFiles) {
    $current = [System.IO.Path]::GetDirectoryName($f.FullName)
    $steps = 0
    while ($current -and $current.Length -gt $pathLen -and $steps -lt 20) {
        if ($deletePaths.Contains($current)) {
            $dirSizes[$current] += $f.Length
            $dirSizeTotal += $f.Length
            break
        }
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
        $steps++
    }
}

$calcElapsed = $calcSw.Elapsed.TotalSeconds
$fileSizeTotal = ($filesToDelete | Measure-Object -Property Length -Sum).Sum
$fileSizeTotal = if ($fileSizeTotal) { [long]$fileSizeTotal } else { [long]0 }

Write-Host ("✅ Tính xong trong {0:N1}s" -f $calcElapsed) -ForegroundColor Green
Write-Host ""

# =====================================================
# BÁO CÁO
# =====================================================

Write-Host "📁 THƯ MỤC SẼ XÓA ($($finalDirs.Count)):" -ForegroundColor Yellow
if ($finalDirs.Count -eq 0) {
    Write-Host "  (không có)" -ForegroundColor Gray
} else {
    foreach ($d in $finalDirs) {
        $s = $dirSizes[$d.FullName]
        Write-Host ("  🗂  {0,-65} {1,12}" -f `
            $d.FullName.Replace($Path, "."), (Format-Size $s))
    }
    Write-Host "  → Tổng thư mục: $(Format-Size $dirSizeTotal)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "📄 FILE SẼ XÓA ($($filesToDelete.Count) files):" -ForegroundColor Yellow
if ($filesToDelete.Count -eq 0) {
    Write-Host "  (không có)" -ForegroundColor Gray
} else {
    $filesToDelete | Sort-Object Length -Descending | Select-Object -First 20 | ForEach-Object {
        Write-Host ("  📄 {0,-70} {1,10}" -f `
            $_.FullName.Replace($Path, "."), (Format-Size $_.Length))
    }
    if ($filesToDelete.Count -gt 20) {
        Write-Host "  ... và $($filesToDelete.Count - 20) file khác" -ForegroundColor Gray
    }
    Write-Host "  → Tổng files: $(Format-Size $fileSizeTotal)" -ForegroundColor Yellow
}
Write-Host ""

$totalWillFree = $dirSizeTotal + $fileSizeTotal
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "💾 SẼ GIẢI PHÓNG: $(Format-Size $totalWillFree)" -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""

if ($DryRun) {
    Write-Host "🔍 DRY RUN — không xóa gì cả." -ForegroundColor Gray
    $sw.Stop()
    Write-Host ("⏱  Tổng thời gian: {0:N1}s" -f $sw.Elapsed.TotalSeconds) -ForegroundColor Gray
    exit 0
}

# =====================================================
# BACKUP
# =====================================================

if ($Backup -and $filesToDelete.Count -gt 0) {
    $backupDir = Join-Path $Path "_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Write-Host "📦 Đang backup vào: $backupDir" -ForegroundColor Cyan

    foreach ($f in $filesToDelete) {
        $rel = $f.FullName.Substring($Path.Length).TrimStart('\')
        $dest = Join-Path $backupDir $rel
        $destDir = Split-Path $dest -Parent
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
    }
    Write-Host "✅ Backup xong." -ForegroundColor Green
    Write-Host ""
}

# =====================================================
# XÓA
# =====================================================

Write-Host "⚠️  Bắt đầu xóa..." -ForegroundColor Red

$deletedCount = 0
$errorCount = 0

# Xóa dirs trước (sâu → nông để tránh lỗi path not found)
$sortedDirs = $finalDirs | Sort-Object { $_.FullName.Length } -Descending
foreach ($d in $sortedDirs) {
    try {
        Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction Stop
        $deletedCount++
    } catch {
        $errorCount++
    }
}

# Xóa files còn sót (không nằm trong dir đã xóa)
foreach ($f in $filesToDelete) {
    if (Test-Path -LiteralPath $f.FullName) {
        try {
            Remove-Item -LiteralPath $f.FullName -Force -ErrorAction Stop
            $deletedCount++
        } catch {
            $errorCount++
        }
    }
}

# =====================================================
# BÁO CÁO CUỐI
# =====================================================

$sizeAfter = $sizeBefore - $totalWillFree
$sw.Stop()

Write-Host ""
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  ✅ HOÀN THÀNH" -ForegroundColor Green
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  Trước:        $(Format-Size $sizeBefore)" -ForegroundColor White
Write-Host "  Sau (ước):    $(Format-Size $sizeAfter)" -ForegroundColor White
Write-Host "  Giải phóng:   $(Format-Size $totalWillFree)" -ForegroundColor Green
Write-Host "  Đã xóa:       $deletedCount mục" -ForegroundColor White
Write-Host "  Lỗi:          $errorCount mục" -ForegroundColor $(if ($errorCount -gt 0) { "Red" } else { "Gray" })
Write-Host "  Thời gian:    $($sw.Elapsed.TotalSeconds.ToString('N1'))s" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host ""