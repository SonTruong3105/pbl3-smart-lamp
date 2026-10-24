from pathlib import Path

# ============ CẤU HÌNH ============
# Chỉ quét thư mục "app" bên trong dự án
folder = Path(r"D:\my-xiaozhi\app")

# File đầu ra
output_file = r"D:\my-xiaozhi_app_code.md"

# ============ CẤU HÌNH BỘ LỌC ============
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".java", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".php", ".rb", ".swift", ".kt",
    ".html", ".css", ".vue", ".sql", ".sh", ".bat", ".ps1",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".cmake", ".mk", ".txt", ".md",
}
IGNORE_DIRS = {
    "build", "Build", "BUILD", "Debug", "Release",
    ".pio", ".vscode", ".git", ".github",
    "node_modules", "__pycache__", "managed_components",
}
IGNORE_FILES = {"sdkconfig", "sdkconfig.old", "package-lock.json"}

# ============ KIỂM TRA THƯ MỤC ============
if not folder.is_dir():
    print(f"❌ Lỗi: '{folder}' không phải là thư mục hợp lệ.")
    print("   Kiểm tra lại đường dẫn (nhớ dùng r\"...\" cho Windows).")
    raise SystemExit(1)

# ============ QUÉT FILE ============
print(f"🔍 Đang quét: {folder} ...")
result = {}

for fp in sorted(folder.rglob("*")):
    if any(part in IGNORE_DIRS for part in fp.parts):
        continue
    if fp.name in IGNORE_FILES:
        continue
    if fp.is_file() and fp.suffix.lower() in CODE_EXTENSIONS:
        try:
            result[str(fp)] = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            print(f"⚠️  Lỗi đọc {fp}: {e}")

# ============ GHI FILE MARKDOWN ============
if not result:
    print("⚠️  Không tìm thấy file code nào phù hợp trong thư mục app.")
    raise SystemExit(0)

with open(output_file, "w", encoding="utf-8") as f:
    f.write(f"# CODE TỪ: {folder}\n\n")
    f.write(f"**Tổng số file:** {len(result)}\n\n---\n")
    for path, content in result.items():
        f.write(f"\n## 📄 `{path}`\n\n")
        f.write("```\n")
        f.write(content)
        f.write("\n```\n\n---\n")

print(f"✅ Đã xuất {len(result)} file vào: {output_file}")