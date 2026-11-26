"""Builtin tools — gộp từ 7 file (common, math, time, weather, search, news, device)."""
from __future__ import annotations
import asyncio, html as html_mod, re, struct
from datetime import datetime, date as date_cls, timedelta
from typing import Any
import httpx
from loguru import logger
from app.config import config
from app.core.device_hub import get_device_hub
from app.core.providers.tools.parallel_search import search_web as parallel_search
from app.core.providers.tools.unified.register import Action

_http_client: httpx.AsyncClient | None = None
async def _http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept-Language": "vi-VN,vi;q=0.9"},
            follow_redirects=True,
        )
    return _http_client

async def close_http() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None

def _cfg(name: str, default: Any = None) -> Any:
    return getattr(config, name, default)

def _clean_text(s: str) -> str:
    if not s: return ""
    s = html_mod.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _compact_text(text: str, max_chars: int = 1500) -> str:
    if not text: return ""
    t = str(text)
    try:
        import json as _json
        data = _json.loads(t)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            lines = []
            for i, r in enumerate(data["results"][:3], 1):
                if not isinstance(r, dict): continue
                title = (r.get("title") or r.get("name") or "").strip()
                content = (r.get("content") or r.get("snippet") or r.get("description") or r.get("body") or r.get("text") or "").strip()
                if not title and not content: continue
                if len(content) > 300: content = content[:300].rsplit(" ", 1)[0] + "..."
                block = f"[{i}] {title}" if title else f"[{i}]"
                if content: block += f": {content}"
                lines.append(block)
            if lines: t = " | ".join(lines)
    except (ValueError, TypeError, KeyError): pass
    t = re.sub(r"[#*_`>]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars: t = t[:max_chars].rsplit(" ", 1)[0] + "..."
    return t

def _truncate_words(s: str, limit: int) -> str:
    if len(s) <= limit: return s
    return s[:limit].rsplit(" ", 1)[0] + "…"

async def _tool_calculate(expression: str) -> str:
    try:
        import ast, operator
        ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv}
        def eval_node(node):
            if isinstance(node, ast.Constant): return node.value
            if isinstance(node, ast.BinOp):
                l, r = eval_node(node.left), eval_node(node.right)
                if isinstance(node.op, ast.Pow) and (abs(r) > 100 or abs(l) > 1e6): raise ValueError("Luy thua qua lon")
                return ops[type(node.op)](l, r)
            if isinstance(node, ast.UnaryOp): return ops[type(node.op)](eval_node(node.operand))
            raise ValueError(f"Không hỗ trợ: {type(node).__name__}")
        expr = (expression or "").strip()
        if not expr: return "Biểu thức rỗng."
        expr = expr.replace("^", "**").replace(":", "/")
        expr = re.sub(r"[xX]", "*", expr)
        expr = re.sub(r"[^\d\+\-\*/%\(\)\.\s]", "", expr)
        if not expr.strip(): return "Biểu thức không hợp lệ."
        tree = ast.parse(expr, mode="eval")
        result = eval_node(tree.body)
        if isinstance(result, float): result = int(result) if result.is_integer() else round(result, 4)
        return f"{expr.strip()} = {result}"
    except Exception as e: return f"Không tính được '{expression}'. Lỗi: {e}"

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
DATE_ALIASES = {"hôm nay": 0, "ngày mai": 1, "mai": 1, "ngày kia": 2, "mốt": 2, "hôm qua": -1, "hôm kia": -2}

async def _tool_get_current_time() -> str:
    now = datetime.now()
    return now.strftime(f"Bây giờ là %H:%M, ngày %d/%m/%Y ({WEEKDAYS_VI[now.weekday()]}).")

def _parse_date(date_str: str) -> date_cls:
    today = date_cls.today()
    s = (date_str or "").strip().lower()
    if s in DATE_ALIASES: return today + timedelta(days=DATE_ALIASES[s])
    if s.startswith(("+", "-")) and s[1:].isdigit(): return today + timedelta(days=int(s))
    WEEKDAY_NAMES = {"thứ hai": 0, "thứ 2": 0, "thứ ba": 1, "thứ 3": 1, "thứ tư": 2, "thứ 4": 2, "thứ năm": 3, "thứ 5": 3, "thứ sáu": 4, "thứ 6": 4, "thứ bảy": 5, "thứ 7": 5, "chủ nhật": 6, "cn": 6}
    for name, wd in WEEKDAY_NAMES.items():
        if name in s:
            wo = 0
            if "tuần sau" in s or "tuần tới" in s: wo = 1
            elif "tuần trước" in s: wo = -1
            monday_this = today - timedelta(days=today.weekday())
            target = monday_this + timedelta(weeks=wo, days=wd)
            if wo == 0 and target < today: target += timedelta(days=7)
            return target
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if y:
            y = int(y)
            if y < 100: y += 2000
        else: y = today.year
        return date_cls(y, mo, d)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m: return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise ValueError(f"Không hiểu định dạng ngày: {date_str!r}")

async def _tool_get_weekday(date: str) -> str:
    try:
        d = _parse_date(date)
        delta = (d - date_cls.today()).days
        rel_map = {0: "hôm nay", 1: "ngày mai", 2: "ngày kia", -1: "hôm qua"}
        rel = rel_map.get(delta, f"còn {delta} ngày nữa" if delta > 0 else f"{abs(delta)} ngày trước")
        return f"{d.strftime('%d/%m/%Y')} là {WEEKDAYS_VI[d.weekday()]} ({rel})."
    except Exception as e: return f"Không tra được: {e}"

async def _tool_days_between(date1: str, date2: str) -> str:
    try:
        d1, d2 = _parse_date(date1), _parse_date(date2)
        delta = (d2 - d1).days
        return f"Tu {d1.strftime('%d/%m/%Y')} đến {d2.strftime('%d/%m/%Y')}: {abs(delta)} ngay."
    except Exception as e: return f"Không tính được: {e}"

async def _tool_get_lunar(date: str = "hôm nay") -> str:
    try: from lunardate import LunarDate
    except ImportError: return "Lỗi: chua cai lunardate."
    try:
        base = _parse_date(date or "hôm nay")
        lunar = LunarDate.fromSolarDate(base.year, base.month, base.day)
        CAN = ["Giáp", "Ất", "Bính", "Đinh", "Mậu", "Kỷ", "Canh", "Tân", "Nhâm", "Quý"]
        CHI = ["Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ", "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi"]
        special = ""
        if lunar.day == 1: special = " (mùng 1)"
        elif lunar.day == 15: special = " (rằm)"
        leap = " nhuận" if getattr(lunar, "isLeapMonth", False) else ""
        return f"Âm lịch {lunar.day}/{lunar.month}{leap} năm {CAN[(lunar.year-4)%10]} {CHI[(lunar.year-4)%12]}{special}."
    except Exception as e: return f"Lỗi: {e}"

WMO_CODES = {0: "Trời quang", 1: "Ít mây", 2: "Có mây", 3: "Nhiều mây", 45: "Sương mù", 48: "Sương mù đóng băng", 51: "Mưa phùn nhẹ", 53: "Mưa phùn", 55: "Mưa phùn nặng", 61: "Mưa nhẹ", 63: "Mưa", 65: "Mưa to", 71: "Tuyết nhẹ", 73: "Tuyết", 75: "Tuyết to", 80: "Mưa rào nhẹ", 81: "Mưa rào", 82: "Mưa rào to", 95: "Giông", 96: "Giông có mưa đá", 99: "Giông mưa đá to"}
_geocode_cache: dict[str, dict] = {}

async def _geocode(city: str) -> dict:
    key = city.strip().lower()
    if key in _geocode_cache: return _geocode_cache[key]
    client = await _http()
    r = await client.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1, "language": "vi"})
    r.raise_for_status()
    data = r.json()
    if not data.get("results"): raise ValueError(f"Không tìm thấy thành phố '{city}'")
    loc = data["results"][0]
    out = {"name": loc.get("name", city), "lat": loc["latitude"], "lon": loc["longitude"]}
    _geocode_cache[key] = out
    return out

async def _tool_get_weather(city: str) -> str:
    try:
        loc = await _geocode(city)
        client = await _http()
        r = await client.get("https://api.open-meteo.com/v1/forecast", params={"latitude": loc["lat"], "longitude": loc["lon"], "current": "temperature_2m,relative_humidity_2m,weather_code", "timezone": "Asia/Ho_Chi_Minh"})
        r.raise_for_status()
        w = r.json()["current"]
        desc = WMO_CODES.get(w["weather_code"], "Không rõ")
        return f"{loc['name']} {round(float(w['temperature_2m']))} độ, {desc.lower()}, độ ẩm {round(float(w['relative_humidity_2m']))} phần trăm."
    except Exception as e:
        logger.error(f"get_weather loi: {e}")
        return f"Không lấy được thời tiết cho {city}."

async def _tool_get_forecast(city: str, days: int = 3) -> str:
    days = max(1, min(7, int(days)))
    try:
        loc = await _geocode(city)
        client = await _http()
        r = await client.get("https://api.open-meteo.com/v1/forecast", params={"latitude": loc["lat"], "longitude": loc["lon"], "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code", "forecast_days": days, "timezone": "Asia/Ho_Chi_Minh"})
        r.raise_for_status()
        d = r.json()["daily"]
        rainy = sum(1 for p in d["precipitation_probability_max"] if p is not None and p >= 60)
        tmin_v = [x for x in d["temperature_2m_min"] if x is not None]
        tmax_v = [x for x in d["temperature_2m_max"] if x is not None]
        tmin = min(tmin_v) if tmin_v else 0
        tmax = max(tmax_v) if tmax_v else 0
        from collections import Counter
        codes = [c for c in d["weather_code"] if c is not None]
        desc = ""
        if codes: desc = WMO_CODES.get(Counter(codes).most_common(1)[0][0], "").lower()
        rain_note = "ít mưa" if rainy == 0 else f"{rainy} ngày mưa"
        parts = [f"{loc['name']} {days} ngày tới"]
        if desc: parts.append(desc)
        parts.append(f"{tmin:.0f} đến {tmax:.0f} độ")
        parts.append(rain_note)
        return ", ".join(parts) + "."
    except Exception as e: return f"Không lấy được dự báo {city}."

PERSON_PATTERNS = re.compile(r"\b(là ai|tiểu sử|sinh năm|nhà văn|ca sĩ|diễn viên|tổng thống)\b", re.IGNORECASE)
CONCEPT_PATTERNS = re.compile(r"\b(là gì|định nghĩa|khái niệm|thuật ngữ|nguyên lý)\b", re.IGNORECASE)
PLACE_PATTERNS = re.compile(r"\b(thủ đô|thành phố|tỉnh|quốc gia|ở đâu|nằm ở)\b", re.IGNORECASE)
REALTIME_PATTERNS = re.compile(r"\b(tỷ số|giá vàng|tỷ giá|usd|eur|bitcoin|chứng khoán|lãi suất|nhiệt độ|dự báo thời tiết)\b", re.IGNORECASE)
NEWS_PATTERNS = re.compile(r"\b(tin tức|thời sự|mới nhất|bản tin|tình hình)\b", re.IGNORECASE)
HOWTO_PATTERNS = re.compile(r"\b(cách|làm sao|hướng dẫn|mẹo|cài đặt)\b", re.IGNORECASE)
PRODUCT_PATTERNS = re.compile(r"\b(giá|review|đánh giá|iphone|samsung|laptop|điện thoại)\b", re.IGNORECASE)

def _classify_subject(query: str) -> str:
    q = query.strip()
    if REALTIME_PATTERNS.search(q): return "realtime"
    if PRODUCT_PATTERNS.search(q): return "product"
    if PERSON_PATTERNS.search(q): return "person"
    if PLACE_PATTERNS.search(q): return "place"
    if CONCEPT_PATTERNS.search(q): return "concept"
    if NEWS_PATTERNS.search(q): return "news"
    if HOWTO_PATTERNS.search(q): return "howto"
    return "general"

async def _wiki_summary(title: str, lang: str = "vi") -> dict | None:
    try:
        client = await _http()
        r = await client.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}", headers={"Accept": "application/json"}, timeout=8.0)
        if r.status_code == 404: return None
        r.raise_for_status()
        data = r.json()
        if data.get("type") == "disambiguation": return None
        return {"title": data.get("title"), "extract": data.get("extract"), "url": data.get("content_urls", {}).get("desktop", {}).get("page")}
    except Exception: return None

async def _wiki_search(query: str, lang: str = "vi", limit: int = 3) -> list:
    try:
        client = await _http()
        r = await client.get(f"https://{lang}.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json"}, timeout=8.0)
        r.raise_for_status()
        return r.json().get("query", {}).get("search", [])
    except Exception: return []

async def _search_wikipedia(query: str) -> str | None:
    lang = _cfg("wiki_lang", "vi") or "vi"
    direct = await _wiki_summary(query, lang)
    if direct and direct.get("extract"):
        return f"Wikipedia: {direct['title']}\n{direct['extract']}"
    return None

async def _search_tavily(query: str, time_range: str | None = None, include_answer: bool = True) -> str | None:
    key = _cfg("tavily_api_key")
    if not key: return None
    try:
        body = {"api_key": key, "query": query, "max_results": _cfg("search_max_results", 3), "include_answer": "advanced" if include_answer else False}
        if time_range: body["time_range"] = time_range
        client = await _http()
        r = await client.post("https://api.tavily.com/search", json=body)
        if r.status_code in (429, 401): return None
        r.raise_for_status()
        data = r.json()
        parts = []
        answer = (data.get("answer") or "").strip()
        if answer: parts.append(answer[:350])
        return "\n".join(parts) if parts else None
    except Exception: return None

async def _search_ddgs(query: str) -> str | None:
    try:
        try: from ddgs import DDGS
        except ImportError: from duckduckgo_search import DDGS
        def _do(backend):
            with DDGS() as d: return list(d.text(query, max_results=5, backend=backend))
        for backend in ["brave", "bing", "auto"]:
            try:
                results = await asyncio.to_thread(_do, backend)
                if results:
                    return " ".join([f"{r.get('title','')}: {r.get('body','')[:300]}" for r in results[:3] if r.get("title")])
            except Exception: continue
        return None
    except Exception: return None

async def _tool_web_search(query: str) -> str:
    try: return await asyncio.wait_for(_tool_web_search_impl(query), timeout=8.0)
    except asyncio.TimeoutError: return "Tìm kiếm mất quá lâu."

async def _tool_web_search_impl(query: str) -> str:
    subject = _classify_subject(query)
    has_tavily = bool(_cfg("tavily_api_key"))
    if subject in ("realtime", "product", "news", "howto", "general"):
        if has_tavily:
            r = await _search_tavily(query, time_range="day" if subject in ("realtime", "news") else None)
            if r: return r
        r = await parallel_search(query)
        if r: return r
    if subject in ("person", "concept", "place"):
        r = await _search_wikipedia(query)
        if r: return r
    if has_tavily:
        r = await _search_tavily(query)
        if r: return r
    r = await _search_ddgs(query)
    if r: return r
    return f"Không tìm thấy thông tin về '{query}'."

NEWS_FEEDS = {
    "vnexpress": {"general": "https://vnexpress.net/rss/tin-moi-nhat.rss", "the-thao": "https://vnexpress.net/rss/the-thao.rss", "kinh-doanh": "https://vnexpress.net/rss/kinh-doanh.rss", "cong-nghe": "https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss", "giai-tri": "https://vnexpress.net/rss/giai-tri.rss"},
    "tuoitre": {"general": "https://tuoitre.vn/rss/tin-moi-nhat.rss", "the-thao": "https://tuoitre.vn/rss/the-thao.rss"},
    "thanhnien": {"general": "https://thanhnien.vn/rss/home.rss"},
    "dantri": {"general": "https://dantri.com.vn/rss/home.rss"},
}

async def _tool_get_news(query: str = "", category: str = "vnexpress", limit: int = 5, topic: str = "") -> str:
    try: import feedparser
    except ImportError: return "Lỗi: chua cai feedparser."
    category = (category or "vnexpress").lower().strip()
    if category not in NEWS_FEEDS: category = "vnexpress"
    feeds = NEWS_FEEDS[category]
    feed_url = feeds.get(topic, feeds["general"]) if topic else feeds["general"]
    try: limit = max(1, min(10, int(limit)))
    except (ValueError, TypeError): limit = 5
    try:
        client = await _http()
        response = await client.get(feed_url, timeout=httpx.Timeout(10.0, connect=3.0))
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        if not feed or not feed.entries: return f"Không lấy được tin từ {category}."
        lines = [f"Tin mới nhất ({category}):"]
        for i, entry in enumerate(feed.entries[:limit], 1):
            title = _clean_text(entry.get("title", ""))
            if title: lines.append(f"  {i}. {title}")
        return "\n".join(lines)
    except Exception as e: return f"Lỗi: {e}"

def _parse_exchange_number(raw_text: str, currency: str) -> str | None:
    if not raw_text: return None
    m = re.search(rf"(?:1\s*{currency}\s*(?:=|bằng|đổi)?\s*)?([\d\.]+)", raw_text, re.IGNORECASE)
    if m:
        val = m.group(1)
        if val and val != "0": return f"1 {currency} ≈ {val} VND."
    return None

async def _tool_get_exchange_rate(currency: str = "USD", target: str = "VND") -> str:
    currency, target = (currency or "USD").upper().strip(), (target or "VND").upper().strip()
    if target != "VND":
        try:
            client = await _http()
            r = await client.get("https://api.frankfurter.app/latest", params={"from": currency, "to": target}, timeout=5.0)
            r.raise_for_status()
            rate = r.json().get("rates", {}).get(target)
            if rate: return f"1 {currency} = {rate:.4f} {target}."
        except Exception: pass
    try:
        raw_text = await _tool_web_search(f"tỷ giá {currency} {target} hôm nay")
        parsed = _parse_exchange_number(raw_text, currency)
        if parsed: return parsed
        return f"Ty gia {currency}/{target}: {_compact_text(raw_text, max_chars=150)}"
    except Exception as e: return f"Không lấy được tỷ giá {currency}."

async def _tool_get_air_quality() -> str:
    from app.core.providers.tools.context import get_connection
    conn = get_connection()
    device_id = getattr(conn, "device_id", None)
    hub = get_device_hub()
    if not hub.is_sensor_fresh(max_age_sec=300, device_id=device_id):
        return "Chưa có dữ liệu cảm biến bụi mịn."
    pm25 = hub.get_sensor("pm25", device_id=device_id)
    if pm25 is None:
        return "Chưa có dữ liệu PM2.5."
    try:
        pm25 = float(pm25)
    except (ValueError, TypeError):
        return "Dữ liệu PM2.5 không hợp lệ."
    if pm25 <= 12:
        level, advice = "rất tốt", "Không khí trong lành."
    elif pm25 <= 35:
        level, advice = "tốt", "Chất lượng không khí ổn."
    elif pm25 <= 55:
        level, advice = "trung bình", "Nên mở cửa sổ hoặc bật lọc khí."
    elif pm25 <= 150:
        level, advice = "kém", "Nên thông gió hoặc lọc không khí ngay."
    else:
        level, advice = "nguy hiểm", "Bụi mịn cao, cần đóng cửa và lọc khí ngay!"
    return f"Chất lượng không khí {level} (PM2.5: {pm25:.1f} µg/m³). {advice}"

async def _send_mcp_command(
    method: str, params: dict = None, timeout: float = 3.0,
    device_id: str | None = None,
) -> dict:
    """Gửi tools/call xuống ESP32.

    device_id=None giữ hành vi cũ (chọn thiết bị đầu tiên) để tương thích các
    call site cũ. Khi truyền rõ device_id: ưu tiên Control WS always-on
    (DeviceMCPManager), sau MQTT control, WS audio và MQTT session.
    """
    from app.core.mqtt_server import get_mqtt_manager
    from app.core.providers.tools.device_mcp_manager import get_device_mcp_manager

    manager = get_mqtt_manager()
    device_manager = get_device_mcp_manager()

    mqtt_control_devices = getattr(manager, "control_devices", {})
    control_transports = getattr(device_manager, "_control_transports", {})
    has_control_channel = getattr(device_manager, "has_control_channel", lambda _device: False)

    def _from_action(action, device):
        return {
            "ok": action.action != Action.ERROR,
            "device_id": device,
            "reply": action.result,
            "error": action.result if action.action == Action.ERROR else None,
        }

    async def _via_mqtt(session: dict, device: str) -> dict:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        session["_mcp_future"] = fut
        try:
            await session["transport"].send_json({
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": method, "arguments": params or {}},
                },
            })
            try:
                reply = await asyncio.wait_for(fut, timeout=timeout)
                return {"ok": True, "device_id": device, "reply": reply}
            except asyncio.TimeoutError:
                return {"ok": False, "error": f"Timeout {timeout}s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            session.pop("_mcp_future", None)

    if device_id:
        if device_id in mqtt_control_devices:
            return await manager.call_control_tool(
                device_id, method, params or {}, timeout=timeout,
            )
        if (device_id in device_manager._transports or
                has_control_channel(device_id)):
            action = await device_manager.call_tool(device_id, method, params or {}, timeout=timeout)
            return _from_action(action, device_id)
        session = manager.sessions.get(device_id)
        if not session:
            return {"ok": False, "error": f"Thiết bị {device_id} chưa kết nối."}
        return await _via_mqtt(session, device_id)

    online_ids = (set(mqtt_control_devices) | set(manager.sessions)
                  | set(device_manager._transports) | set(control_transports))
    if len(online_ids) != 1:
        return {
            "ok": False,
            "error": "Cần chỉ định device_id; không thể chọn thiết bị an toàn khi có 0 hoặc nhiều thiết bị.",
        }
    device_id = next(iter(online_ids))
    if device_id in mqtt_control_devices:
        return await manager.call_control_tool(device_id, method, params or {}, timeout=timeout)
    if (device_id in device_manager._transports or
            has_control_channel(device_id)):
        action = await device_manager.call_tool(device_id, method, params or {}, timeout=timeout)
        return _from_action(action, device_id)
    session = manager.sessions.get(device_id)
    return await _via_mqtt(session, device_id) if session else {
        "ok": False, "error": f"Thiết bị {device_id} chưa kết nối."
    }

async def _tool_lamp_turn_on() -> str:
    r = await _send_mcp_command("Lamp.TurnOn")
    return "Đã bật đèn." if r["ok"] else f"Không bật được: {r.get('error')}"

async def _tool_lamp_turn_off() -> str:
    r = await _send_mcp_command("Lamp.TurnOff")
    return "Đã tắt đèn." if r["ok"] else f"Không tắt được: {r.get('error')}"

async def _tool_lamp_set_brightness(brightness: int) -> str:
    b = max(0, min(100, int(brightness)))
    r = await _send_mcp_command("Lamp.SetBrightness", {"value": b})
    return f"Da dat độ sang {b}%." if r["ok"] else f"Lỗi: {r.get('error')}"

async def _tool_lamp_set_color_temp(color_temp: int) -> str:
    c = max(0, min(100, int(color_temp)))
    r = await _send_mcp_command("Lamp.SetColorTemp", {"value": c})
    return f"Da dat nhiet độ mau {c}." if r["ok"] else f"Lỗi: {r.get('error')}"

async def _tool_get_sensor(sensor: str = "all") -> str:
    from app.core.providers.tools.context import get_connection
    conn = get_connection()
    device_id = getattr(conn, "device_id", None)
    hub = get_device_hub()
    if sensor == "all":
        data = hub.get_all_sensors(device_id=device_id)
        if not hub.is_sensor_fresh(max_age_sec=300, device_id=device_id):
            return "Chưa có dữ liệu cảm biến."
        parts = []
        if data.get("temperature") is not None: parts.append(f"nhiệt độ {data['temperature']}°C")
        if data.get("humidity") is not None: parts.append(f"độ ẩm {data['humidity']}%")
        if data.get("pm25") is not None: parts.append(f"bụi mịn PM2.5 {data['pm25']} µg/m³")
        if data.get("light_lux") is not None: parts.append(f"ánh sáng {data['light_lux']} lux")
        if data.get("presence") is not None: parts.append("có người" if data["presence"] else "không có người")
        return "Phòng hiện tại: " + ", ".join(parts) + "."
    value = hub.get_sensor(sensor, device_id=device_id)
    labels = {
        "temperature": ("Nhiệt độ phòng", "°C"),
        "humidity": ("Độ ẩm phòng", "%"),
        "pm25": ("Bụi mịn PM2.5", " µg/m³"),
        "light_lux": ("Ánh sáng", " lux"),
        "presence": ("Hiện diện", ""),
    }
    label, unit = labels.get(sensor, (sensor, ""))
    if value is None:
        return f"Chưa có dữ liệu {label.lower()}."
    if sensor == "presence":
        return "Có người trong phòng." if value else "Không có người trong phòng."
    return f"{label}: {value}{unit}."

__all__ = [
    "_http", "close_http", "_cfg", "_clean_text", "_compact_text", "_truncate_words",
    "_tool_calculate", "_tool_get_current_time", "_parse_date", "_tool_get_weekday",
    "_tool_days_between", "_tool_get_lunar", "_geocode", "_tool_get_weather",
    "_tool_get_forecast", "_classify_subject", "_wiki_summary", "_wiki_search",
    "_search_wikipedia", "_search_tavily", "_search_ddgs", "_tool_web_search",
    "_tool_web_search_impl", "_tool_get_news", "_tool_get_exchange_rate",
    "_tool_get_air_quality", "_send_mcp_command", "_tool_lamp_turn_on",
    "_tool_lamp_turn_off", "_tool_lamp_set_brightness", "_tool_lamp_set_color_temp",
    "_tool_get_sensor",
]