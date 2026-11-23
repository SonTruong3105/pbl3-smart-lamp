import os

ROOT = os.getcwd()
print("=== DỌN DẸP FILE THỪA ===")

# 1. Xóa các file JS không còn dùng
js_dir = os.path.join(ROOT, "static", "js")
js_to_delete = ["lamp.js", "observe.js"]

for f in js_to_delete:
    path = os.path.join(js_dir, f)
    if os.path.exists(path):
        os.remove(path)
        print(f"[XÓA] static/js/{f}")

# 2. Xóa các file CSS cũ (chỉ giữ style.css)
css_dir = os.path.join(ROOT, "static", "css")
css_to_delete = [
    "dashboard.css", "chat.css", "calendar.css", 
    "apple-calendar.css", "tokens.css", "base.css", 
    "components.css", "layout.css", "calendar-base.css",
    "calendar-integration.css", "calendar-layout.css", 
    "calendar-overrides.css"
]

for f in css_to_delete:
    path = os.path.join(css_dir, f)
    if os.path.exists(path):
        os.remove(path)
        print(f"[XÓA] static/css/{f}")

# 3. Kiểm tra các file còn lại
print("\n=== CÁC FILE CÒN LẠI ===")
print("CSS:")
if os.path.exists(css_dir):
    for f in os.listdir(css_dir):
        if f.endswith(".css"):
            print(f"  ✅ {f}")

print("JS:")
if os.path.exists(js_dir):
    for f in os.listdir(js_dir):
        if f.endswith(".js"):
            print(f"  ✅ {f}")

print("\n=== HOÀN TẤT ===")