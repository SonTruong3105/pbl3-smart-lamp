
$ErrorActionPreference = "Stop"
$Root = "D:\Xiaozhi_server"
Set-Location $Root

$OutputFile = Join-Path $Root "xiaozhi_full_code.txt"

# Các thư mục không cần đọc
$ExcludeDirs = @(
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "logs",
    ".idea",
    ".vscode"
)

# Các loại file muốn đọc toàn bộ
$Extensions = @(
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".ini",
    ".ps1",
    ".md"
)

Write-Host "`nDang quet ma nguon Xiaozhi..." -ForegroundColor Cyan

$Files = Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $relative = $_.FullName.Substring($Root.Length).TrimStart('\')
        $parts = $relative -split '[\\/]'

        ($parts | Where-Object { $ExcludeDirs -contains $_ }).Count -eq 0 -and
        $Extensions -contains $_.Extension.ToLowerInvariant() -and
        $_.FullName -ne $OutputFile
    } |
    Sort-Object FullName

Write-Host "Tim thay $($Files.Count) file." -ForegroundColor Yellow

# Dùng StreamWriter để ghi lần lượt, tránh giữ toàn bộ code trong RAM
$Writer = [System.IO.StreamWriter]::new(
    $OutputFile,
    $false,
    [System.Text.UTF8Encoding]::new($true)
)

try {
    $Writer.WriteLine("XIAOZHI SERVER - FULL SOURCE CODE REPORT")
    $Writer.WriteLine("Root: $Root")
    $Writer.WriteLine("Thoi gian: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    $Writer.WriteLine("Tong so file: $($Files.Count)")
    $Writer.WriteLine(("=" * 100))

    foreach ($File in $Files) {
        $RelativePath = $File.FullName.Substring($Root.Length).TrimStart('\')

        Write-Host "Dang doc: $RelativePath" -ForegroundColor Gray

        $Writer.WriteLine("")
        $Writer.WriteLine(("=" * 100))
        $Writer.WriteLine("FILE: $RelativePath")
        $Writer.WriteLine(("=" * 100))

        try {
            $Reader = [System.IO.StreamReader]::new(
                $File.FullName,
                [System.Text.Encoding]::UTF8,
                $true
            )

            try {
                while (($Line = $Reader.ReadLine()) -ne $null) {
                    $Writer.WriteLine($Line)
                }
            }
            finally {
                $Reader.Dispose()
            }
        }
        catch {
            $Writer.WriteLine("[LOI DOC FILE: $($_.Exception.Message)]")
        }

        $Writer.WriteLine("")
    }
}
finally {
    $Writer.Dispose()
}

$SizeMB = [math]::Round(
    (Get-Item -LiteralPath $OutputFile).Length / 1MB,
    2
)

Write-Host "`nHOAN TAT!" -ForegroundColor Green
Write-Host "So file: $($Files.Count)" -ForegroundColor Green
Write-Host "Dung luong: $SizeMB MB" -ForegroundColor Green
Write-Host "Bao cao: $OutputFile" -ForegroundColor Cyan

# Mở thư mục chứa báo cáo
explorer.exe $Root
