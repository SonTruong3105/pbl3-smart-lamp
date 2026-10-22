"""Test backend ddgs với timeout và debug chi tiết."""

import sys
import time

print("=" * 60, flush=True)
print("BẮT ĐẦU TEST", flush=True)
print("=" * 60, flush=True)

# Test import
try:
    from ddgs import DDGS
    print("✅ Import ddgs OK", flush=True)
except Exception as e:
    print(f"❌ Import lỗi: {e}", flush=True)
    sys.exit(1)

# Test version
try:
    import ddgs
    print(f"📦 Version: {getattr(ddgs, '__version__', 'unknown')}", flush=True)
except Exception:
    pass

print(flush=True)

BACKENDS = ["auto", "bing", "brave", "duckduckgo", "google", "yandex"]
QUERY = "iPhone 18 Pro"

for backend in BACKENDS:
    print(f"→ Testing '{backend}'...", end=" ", flush=True)

    try:
        start = time.perf_counter()
        with DDGS() as ddgs:
            results = list(ddgs.text(QUERY, max_results=3, backend=backend))
        elapsed = time.perf_counter() - start

        if results:
            print(f"✅ {len(results)} kết quả ({elapsed:.2f}s)", flush=True)
            print(f"     → {results[0].get('title', '')[:70]}", flush=True)
        else:
            print(f"⚠️  Rỗng ({elapsed:.2f}s)", flush=True)

    except Exception as e:
        print(f"❌ {type(e).__name__}: {str(e)[:60]}", flush=True)

print(flush=True)
print("=" * 60, flush=True)
print("KẾT THÚC", flush=True)