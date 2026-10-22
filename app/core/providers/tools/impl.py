"""Tools — subject routing (SearXNG + Tavily + Wikipedia).

Router logic:
    realtime/product/news/howto  → Tavily → SearXNG → ddgs
    person/concept/place         → Wikipedia → Tavily → SearXNG
    general                      → SearXNG → Tavily → ddgs
"""
import asyncio
import html as html_mod
import re
from datetime import datetime, date as date_cls, timedelta
from typing import Any

import httpx
from loguru import logger

from app.config import config


# =====================================================
# CONSTANTS
# =====================================================

WMO_CODES = {
    0: "Trời quang", 1: "Ít mây", 2: "Có mây", 3: "Nhiều mây",
    45: "Sương mù", 48: "Sương mù đóng băng",
    51: "Mưa phùn nhẹ", 53: "Mưa phùn", 55: "Mưa phùn nặng",
    61: "Mưa nhẹ", 63: "Mưa", 65: "Mưa to",
    71: "Tuyết nhẹ", 73: "Tuyết", 75: "Tuyết to",
    80: "Mưa rào nhẹ", 81: "Mưa rào", 82: "Mưa rào to",
    95: "Giông", 96: "Giông có mưa đá", 99: "Giông mưa đá to",
}

WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
               "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

DATE_ALIASES = {
    "hôm nay": 0, "ngày mai": 1, "mai": 1,
    "ngày kia": 2, "mốt": 2,
    "hôm qua": -1, "hôm kia": -2,
}


# =====================================================
# SUBJECT CLASSIFIER
# =====================================================

PERSON_PATTERNS = re.compile(
    r"\b(là ai|tiểu sử|sinh năm|mất năm|nhà văn|nhà thơ|ca sĩ|"
    r"diễn viên|tổng thống|chủ tịch|vua|danh nhân|anh hùng|"
    r"nghệ sĩ|nhạc sĩ|họa sĩ|giáo sư|tiến sĩ)\b", re.IGNORECASE)

CONCEPT_PATTERNS = re.compile(
    r"\b(là gì|định nghĩa|khái niệm|nghĩa là|thuật ngữ|"
    r"nguyên lý|định lý|công thức)\b", re.IGNORECASE)

PLACE_PATTERNS = re.compile(
    r"\b(thủ đô|thành phố|tỉnh|quốc gia|đất nước|"
    r"châu lục|đại dương|con sông|ngọn núi|ở đâu|nằm ở)\b", re.IGNORECASE)

REALTIME_PATTERNS = re.compile(
    r"\b(tỷ số|tỉ số|livescore|kết quả bóng|kết quả trận|"
    r"giá vàng|giá đô|tỷ giá|usd|eur|bitcoin|btc|"
    r"chứng khoán|vn-index|cổ phiếu|lãi suất|"
    r"xổ số|xskt|lô tô|nhiệt độ|bao nhiêu độ|có mưa không|"
    r"dự báo thời tiết|giá xăng|giá điện|giá cả|hôm nay bao nhiêu|"
    r"bảng xếp hạng|lịch thi đấu)\b", re.IGNORECASE)

NEWS_PATTERNS = re.compile(
    r"\b(tin tức|thời sự|sự kiện|mới nhất|hôm nay có gì|"
    r"bản tin|thông tin mới|diễn biến|tình hình)\b", re.IGNORECASE)

HOWTO_PATTERNS = re.compile(
    r"\b(cách|làm sao|hướng dẫn|thủ thuật|mẹo|"
    r"cài đặt|setup|tutorial|chỉ cách)\b", re.IGNORECASE)

PRODUCT_PATTERNS = re.compile(
    r"\b(giá|review|đánh giá|mua ở đâu|so sánh|"
    r"iphone|samsung|xiaomi|vinfast|honda|toyota|"
    r"laptop|điện thoại|tai nghe)\b", re.IGNORECASE)


def _classify_subject(query: str) -> str:
    q = query.strip()
    if REALTIME_PATTERNS.search(q):
        return "realtime"
    if PRODUCT_PATTERNS.search(q):
        return "product"
    if PERSON_PATTERNS.search(q):
        return "person"
    if PLACE_PATTERNS.search(q):
        return "place"
    if CONCEPT_PATTERNS.search(q):
        return "concept"
    if NEWS_PATTERNS.search(q):
        return "news"
    if HOWTO_PATTERNS.search(q):
        return "howto"
    return "general"


# =====================================================
# HTTP CLIENT — REUSE (tránh connection leak)
# =====================================================

_http_client: httpx.AsyncClient | None = None


async def _http() -> httpx.AsyncClient:
    """Singleton httpx client — reuse connection pool."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
        )
    return _http_client


async def close_http() -> None:
    """Gọi khi shutdown server."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


def _cfg(name: str, default: Any = None) -> Any:
    return getattr(config, name, default)


# =====================================================
# HELPERS
# =====================================================

def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = html_mod.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _truncate_words(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit].rsplit(" ", 1)[0] + "…"


def _format_results(results: list) -> str | None:
    """Format kết quả search thành text gọn cho TTS."""
    lines = []
    for i, res in enumerate(results, 1):
        title = _clean_text(res.get("title") or "")
        content = _clean_text(
            res.get("content") or res.get("desc") or res.get("body") or "")
        url = (res.get("url") or res.get("link") or "").strip()
        if not title and not content:
            continue
        content = _truncate_words(content, 400)
        block = f"[{i}] {title}"
        if content:
            block += f"\n    {content}"
        if url:
            block += f"\n    {url}"
        lines.append(block)
    return "\n".join(lines) if lines else None


# =====================================================
# WEATHER (không cần search)
# =====================================================

_geocode_cache: dict[str, dict] = {}


async def _geocode(city: str) -> dict:
    key = city.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]
    client = await _http()
    r = await client.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "vi"},
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("results"):
        raise ValueError(f"Không tìm thấy thành phố '{city}'")
    loc = data["results"][0]
    out = {
        "name": loc.get("name", city),
        "lat": loc["latitude"],
        "lon": loc["longitude"],
    }
    _geocode_cache[key] = out
    return out


async def _tool_get_weather(city: str) -> str:
    try:
        loc = await _geocode(city)
        client = await _http()
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "current": (
                    "temperature_2m,relative_humidity_2m,"
                    "apparent_temperature,wind_speed_10m,weather_code"
                ),
                "timezone": "Asia/Ho_Chi_Minh",
            },
        )
        r.raise_for_status()
        w = r.json()["current"]
        desc = WMO_CODES.get(w["weather_code"], "Không rõ")
        return (
            f"Thời tiết {loc['name']}: {desc}, "
            f"{w['temperature_2m']}°C (cảm giác {w['apparent_temperature']}°C), "
            f"độ ẩm {w['relative_humidity_2m']}%, "
            f"gió {w['wind_speed_10m']} km/h."
        )
    except Exception as e:
        logger.error(f"get_weather lỗi: {e}")
        return f"Không lấy được thời tiết cho {city}."


async def _tool_get_forecast(city: str, days: int = 3) -> str:
    days = max(1, min(7, int(days)))
    try:
        loc = await _geocode(city)
        client = await _http()
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,weather_code"
                ),
                "forecast_days": days,
                "timezone": "Asia/Ho_Chi_Minh",
            },
        )
        r.raise_for_status()
        d = r.json()["daily"]

        lines = [f"Dự báo {loc['name']} {days} ngày tới:"]
        rains = d["precipitation_probability_max"]

        for i in range(days):
            y, mo, dd = map(int, d["time"][i].split("-"))
            wd = WEEKDAYS_VI[date_cls(y, mo, dd).weekday()]
            # ✅ FIX: rains[i] có thể None → default 0
            prob = rains[i] if rains[i] is not None else 0
            t_min = d["temperature_2m_min"][i]
            t_max = d["temperature_2m_max"][i]
            lines.append(
                f"  {wd} {dd}/{mo}: "
                f"{t_min}°C - {t_max}°C, "
                f"{WMO_CODES.get(d['weather_code'][i], '')}, mưa {prob}%"
            )

        # ✅ FIX: filter None trước khi min/max
        valid_rains = [p for p in rains if p is not None]
        max_rain = max(valid_rains) if valid_rains else 0
        rain_note = (
            "có mưa rõ rệt" if max_rain >= 60
            else "có thể có mưa" if max_rain >= 30
            else "ít có mưa"
        )
        valid_tmin = [x for x in d["temperature_2m_min"] if x is not None]
        valid_tmax = [x for x in d["temperature_2m_max"] if x is not None]
        tmin = min(valid_tmin) if valid_tmin else 0
        tmax = max(valid_tmax) if valid_tmax else 0

        lines.append(
            f"\nTổng quan: {days} ngày tới {rain_note}, "
            f"nhiệt độ {tmin:.0f}°C - {tmax:.0f}°C."
        )
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_forecast lỗi: {e}")
        return f"Không lấy được dự báo cho {city}."


# =====================================================
# SEARXNG
# =====================================================

async def _search_searxng(
    query: str,
    extra_params: dict | None = None,
) -> str | None:
    url = _cfg("searxng_url")
    if not url:
        return None
    try:
        params = {
            "q": query,
            "format": "json",
            "language": "vi-VN",
            "safesearch": 0,
        }
        if extra_params:
            params.update(extra_params)

        client = await _http()
        r = await client.get(url, params=params)

        if r.status_code == 403:
            logger.warning("SearXNG 403 — JSON chưa bật trong settings.yml")
            return None
        r.raise_for_status()

        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            logger.warning(f"SearXNG trả {ctype!r}, không phải JSON")
            return None

        results = r.json().get("results", [])
        max_n = _cfg("search_max_results", 5)
        results = results[:max_n]
        if not results:
            return None
        return _format_results(results)
    except Exception as e:
        logger.warning(f"SearXNG lỗi: {e}")
        return None


def _subject_to_searxng_params(subject: str) -> dict:
    base = {"language": "vi-VN", "safesearch": 0}
    if subject in ("person", "concept", "place"):
        return {**base, "engines": "wikipedia", "categories": "general"}
    if subject == "news":
        return {**base, "categories": "news", "time_range": "day"}
    if subject == "howto":
        return {**base, "categories": "general", "engines": "google,bing"}
    return {**base, "categories": "general"}


# =====================================================
# WIKIPEDIA
# =====================================================

WIKI_SUMMARY = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH = "https://{lang}.wikipedia.org/w/api.php"


async def _wiki_summary(title: str, lang: str = "vi") -> dict | None:
    try:
        client = await _http()
        r = await client.get(
            WIKI_SUMMARY.format(lang=lang, title=title.replace(" ", "_")),
            headers={"Accept": "application/json"},
            timeout=8.0,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        if data.get("type") == "disambiguation":
            return None
        return {
            "title": data.get("title"),
            "extract": data.get("extract"),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        }
    except Exception as e:
        logger.debug(f"Wiki summary lỗi: {e}")
        return None


async def _wiki_search(query: str, lang: str = "vi", limit: int = 3) -> list:
    try:
        client = await _http()
        r = await client.get(
            WIKI_SEARCH.format(lang=lang),
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "format": "json",
                "utf8": 1,
            },
            timeout=8.0,
        )
        r.raise_for_status()
        return r.json().get("query", {}).get("search", [])
    except Exception as e:
        logger.debug(f"Wiki search lỗi: {e}")
        return []


async def _search_wikipedia(query: str) -> str | None:
    lang = _cfg("wiki_lang", "vi") or "vi"

    # Thử direct lookup trước
    direct = await _wiki_summary(query, lang)
    if direct and direct.get("extract"):
        return (
            f"〖Wikipedia〗{direct['title']}\n"
            f"{direct['extract']}\n"
            f"{direct.get('url', '')}"
        )

    # Fallback: search rồi lấy summary
    results = await _wiki_search(query, lang, limit=3)
    if not results:
        return None

    top = results[0].get("title", "")
    if not top:
        return None

    summary = await _wiki_summary(top, lang)
    if not summary or not summary.get("extract"):
        snippet = re.sub(r"<[^>]+>", "", results[0].get("snippet", ""))
        return f"〖Wikipedia〗{top}\n{snippet}"

    return (
        f"〖Wikipedia〗{summary['title']}\n"
        f"{summary['extract']}\n"
        f"{summary.get('url', '')}"
    )


# =====================================================
# TAVILY
# =====================================================

async def _search_tavily(
    query: str,
    time_range: str | None = None,
    include_answer: bool = True,
) -> str | None:
    key = _cfg("tavily_api_key")
    if not key:
        return None

    try:
        body = {
            "api_key": key,
            "query": query,
            "search_depth": "advanced" if include_answer else "basic",
            "max_results": _cfg("search_max_results", 3),
            "include_answer": "advanced" if include_answer else False,
            "include_raw_content": False,
        }
        if time_range:
            body["time_range"] = time_range

        client = await _http()
        r = await client.post("https://api.tavily.com/search", json=body)

        if r.status_code == 429:
            logger.warning("⚠️ Tavily hết credit")
            return None
        if r.status_code == 401:
            logger.warning("⚠️ Tavily API key sai")
            return None
        r.raise_for_status()

        data = r.json()
        parts = []

        # Ưu tiên answer — ngắn gọn, đủ ý cho TTS
        answer = (data.get("answer") or "").strip()
        if answer:
            if len(answer) > 350:
                answer = answer[:350].rsplit(" ", 1)[0] + "..."
            parts.append(answer)

        # Fallback: top results nếu không có answer
        if not answer:
            results = data.get("results", [])[:2]
            for x in results:
                title = (x.get("title") or "").strip()
                content = (x.get("content") or "").strip()[:200]
                if content:
                    parts.append(f"{title}: {content}" if title else content)

        return "\n".join(parts) if parts else None

    except Exception as e:
        logger.warning(f"Tavily lỗi: {e}")
        return None


# =====================================================
# DDGS FALLBACK
# =====================================================

async def _search_ddgs(query: str) -> str | None:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        def _do(backend):
            with DDGS() as d:
                return list(d.text(query, max_results=5, backend=backend))

        for backend in ["brave", "bing", "yandex", "auto"]:
            try:
                results = await asyncio.to_thread(_do, backend)
                if results:
                    parts = [
                        f"{r.get('title', '')}: {r.get('body', '')[:300]}"
                        for r in results[:3] if r.get("title")
                    ]
                    if parts:
                        return " ".join(parts)
            except Exception:
                continue
        return None
    except Exception as e:
        logger.warning(f"ddgs lỗi: {e}")
        return None


# =====================================================
# MAIN ROUTER
# =====================================================

async def _tool_web_search(query: str) -> str:
    subject = _classify_subject(query)
    has_tavily = bool(_cfg("tavily_api_key"))
    logger.info(f"🔍 web_search [{subject}] '{query[:60]}'")

    # ─── 1. Tavily cho realtime/product/news/howto ───
    if has_tavily and subject in ("realtime", "product", "news", "howto"):
        time_range = "day" if subject in ("realtime", "news") else None
        result = await _search_tavily(
            query,
            time_range=time_range,
            include_answer=True,
        )
        if result:
            logger.info(f"   ✓ Tavily ({subject})")
            return result
        logger.info("   ↻ Tavily fail → next")

    # ─── 2. Wikipedia cho person/concept/place ───
    if subject in ("person", "concept", "place"):
        result = await _search_wikipedia(query)
        if result:
            logger.info(f"   ✓ Wikipedia ({subject})")
            return result
        logger.info("   ↻ Wiki fail → SearXNG")

    # ─── 3. SearXNG (subject-specific params) ───
    searxng_params = _subject_to_searxng_params(subject)
    result = await _search_searxng(query, extra_params=searxng_params)
    if result:
        logger.info(f"   ✓ SearXNG ({subject})")
        return result

    # ─── 4. SearXNG general fallback (nếu params quá hẹp) ───
    if searxng_params.get("engines") or searxng_params.get("categories") != "general":
        result = await _search_searxng(query, extra_params={"language": "vi-VN"})
        if result:
            logger.info("   ✓ SearXNG (general fallback)")
            return result

    # ─── 5. Tavily rescue (general case) ───
    if has_tavily:
        result = await _search_tavily(query, time_range=None)
        if result:
            logger.info("   ✓ Tavily (rescue)")
            return result

    # ─── 6. ddgs fallback ───
    logger.info("   ↻ Fallback ddgs")
    result = await _search_ddgs(query)
    if result:
        logger.info("   ✓ ddgs")
        return result

    return f"Không tìm thấy thông tin về '{query}'."


# =====================================================
# TIME / DATE
# =====================================================

async def _tool_get_current_time() -> str:
    now = datetime.now()
    return now.strftime(
        f"Bây giờ là %H:%M, ngày %d/%m/%Y ({WEEKDAYS_VI[now.weekday()]})."
    )


def _parse_date(date_str: str) -> date_cls:
    today = date_cls.today()
    s = (date_str or "").strip().lower()

    if s in DATE_ALIASES:
        return today + timedelta(days=DATE_ALIASES[s])

    if s.startswith(("+", "-")) and s[1:].isdigit():
        return today + timedelta(days=int(s))

    WEEKDAY_NAMES = {
        "thứ hai": 0, "thứ 2": 0,
        "thứ ba": 1, "thứ 3": 1,
        "thứ tư": 2, "thứ 4": 2,
        "thứ năm": 3, "thứ 5": 3,
        "thứ sáu": 4, "thứ 6": 4,
        "thứ bảy": 5, "thứ 7": 5,
        "chủ nhật": 6, "cn": 6,
    }
    for name, wd in WEEKDAY_NAMES.items():
        if name in s:
            week_offset = 0
            if "tuần sau" in s or "tuần tới" in s:
                week_offset = 1
            elif "tuần trước" in s:
                week_offset = -1

            monday_this = today - timedelta(days=today.weekday())
            monday_target = monday_this + timedelta(weeks=week_offset)
            target = monday_target + timedelta(days=wd)
            if week_offset == 0 and target < today:
                target += timedelta(days=7)
            return target

    m = re.match(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if y:
            y = int(y)
            if y < 100:
                y += 2000
        else:
            y = today.year
        return date_cls(y, mo, d)

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return date_cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    raise ValueError(f"Không hiểu định dạng ngày: {date_str!r}")


async def _tool_get_weekday(date: str) -> str:
    try:
        d = _parse_date(date)
        wd = WEEKDAYS_VI[d.weekday()]
        delta = (d - date_cls.today()).days

        rel_map = {0: "hôm nay", 1: "ngày mai", 2: "ngày kia", -1: "hôm qua"}
        if delta in rel_map:
            rel = rel_map[delta]
        elif delta > 0:
            rel = f"còn {delta} ngày nữa"
        else:
            rel = f"{abs(delta)} ngày trước"

        return f"{d.strftime('%d/%m/%Y')} là {wd} ({rel})."
    except Exception as e:
        logger.error(f"get_weekday lỗi: {e}")
        return f"Không tra được thứ cho '{date}'. Lỗi: {e}"


async def _tool_days_between(date1: str, date2: str) -> str:
    try:
        d1 = _parse_date(date1)
        d2 = _parse_date(date2)
        delta = (d2 - d1).days
        if delta == 0:
            rel = "cùng một ngày"
        elif delta > 0:
            rel = f"{d2.strftime('%d/%m/%Y')} sau {d1.strftime('%d/%m/%Y')} {delta} ngày"
        else:
            rel = f"{d2.strftime('%d/%m/%Y')} trước {d1.strftime('%d/%m/%Y')} {abs(delta)} ngày"
        return (
            f"Từ {d1.strftime('%d/%m/%Y')} ({WEEKDAYS_VI[d1.weekday()]}) "
            f"đến {d2.strftime('%d/%m/%Y')} ({WEEKDAYS_VI[d2.weekday()]}): "
            f"{abs(delta)} ngày ({rel})."
        )
    except Exception as e:
        logger.error(f"days_between lỗi: {e}")
        return f"Không tính được. Lỗi: {e}"


# =====================================================
# SENSOR STATE IMPORT (nếu chưa có)
# =====================================================

try:
    from app.core.providers.tools import sensor_state
except ImportError:
    sensor_state = None


# =====================================================
# LUNAR CALENDAR (Âm lịch VN)
# =====================================================

async def _tool_get_lunar(date: str = "hôm nay") -> str:
    try:
        from lunardate import LunarDate
    except ImportError:
        return "Lỗi: chưa cài lunardate. Chạy: pip install lunardate"

    try:
        base = _parse_date(date or "hôm nay")
        lunar = LunarDate.fromSolarDate(base.year, base.month, base.day)

        CAN = ["Giáp", "Ất", "Bính", "Đinh", "Mậu",
               "Kỷ", "Canh", "Tân", "Nhâm", "Quý"]
        CHI = ["Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ",
               "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi"]
        can_year = CAN[(lunar.year - 4) % 10]
        chi_year = CHI[(lunar.year - 4) % 12]

        special = ""
        if lunar.day == 1:
            special = " (mùng 1 đầu tháng âm)"
        elif lunar.day == 15:
            special = " (rằm, ngày 15 âm)"
        elif lunar.day in (29, 30):
            special = " (cuối tháng âm)"

        delta = (base - date_cls.today()).days
        rel_map = {0: "hôm nay", 1: "ngày mai", 2: "ngày kia", -1: "hôm qua"}
        rel = rel_map.get(delta,
                          f"{abs(delta)} ngày nữa" if delta > 0
                          else f"{abs(delta)} ngày trước")

        leap = " nhuận" if getattr(lunar, "isLeapMonth", False) else ""

        return (
            f"Ngày {base.strftime('%d/%m/%Y')} dương lịch {rel} "
            f"tương ứng âm lịch {lunar.day}/{lunar.month}{leap} "
            f"năm {can_year} {chi_year}{special}."
        )
    except Exception as e:
        logger.error(f"get_lunar lỗi: {e}")
        return f"Không tra được âm lịch cho '{date}'. Lỗi: {e}"


# =====================================================
# NEWS (RSS VN)
# =====================================================

NEWS_FEEDS = {
    "vnexpress":  "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "tuoitre":    "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "thanhnien":  "https://thanhnien.vn/rss/home.rss",
    "dantri":     "https://dantri.com.vn/rss/home.rss",
}


async def _tool_get_news(category: str = "vnexpress", limit: int = 5) -> str:
    try:
        import feedparser
    except ImportError:
        return "Lỗi: chưa cài feedparser. Chạy: pip install feedparser"

    category = (category or "vnexpress").lower().strip()
    feed_url = NEWS_FEEDS.get(category, NEWS_FEEDS["vnexpress"])
    category = category if category in NEWS_FEEDS else "vnexpress"

    try:
        limit = max(1, min(10, int(limit)))
    except (ValueError, TypeError):
        limit = 5

    def _fetch():
        try:
            return feedparser.parse(feed_url)
        except Exception as e:
            logger.warning(f"feedparser lỗi: {e}")
            return None

    try:
        feed = await asyncio.to_thread(_fetch)
        if not feed or not feed.entries:
            return f"Không lấy được tin tức từ {category}."

        lines = [f"Tin tức mới nhất ({category}):"]
        for i, entry in enumerate(feed.entries[:limit], 1):
            title = _clean_text(entry.get("title", ""))
            if title:
                lines.append(f"  {i}. {title}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_news lỗi: {e}")
        return f"Không lấy được tin tức. Lỗi: {e}"


# =====================================================
# EXCHANGE RATE
# =====================================================

async def _tool_get_exchange_rate(
    currency: str = "USD",
    target: str = "VND",
) -> str:
    currency = (currency or "USD").upper().strip()
    target = (target or "VND").upper().strip()

    try:
        client = await _http()
        r = await client.get(
            "https://api.frankfurter.app/latest",
            params={"from": currency, "to": target},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        rates = data.get("rates", {})
        rate = rates.get(target)
        if rate:
            if rate >= 1000:
                rate_str = f"{rate:,.0f}".replace(",", ".")
            else:
                rate_str = f"{rate:.4f}"
            return (
                f"Tỷ giá {currency}/{target}: 1 {currency} = {rate_str} {target}. "
                f"(Cập nhật: {data.get('date', 'không rõ')})"
            )
    except Exception as e:
        logger.warning(f"Frankfurter lỗi: {e}")

    logger.info("   ↻ Exchange rate fallback → web_search")
    return await _tool_web_search(f"tỷ giá {currency} {target} hôm nay")


# =====================================================
# CALCULATE
# =====================================================

async def _tool_calculate(expression: str) -> str:
    try:
        import ast
        import operator

        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.Mod: operator.mod,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
            ast.FloorDiv: operator.floordiv,
        }

        def eval_node(node):
            if isinstance(node, ast.Num):
                return node.n
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.BinOp):
                return ops[type(node.op)](eval_node(node.left), eval_node(node.right))
            if isinstance(node, ast.UnaryOp):
                return ops[type(node.op)](eval_node(node.operand))
            raise ValueError(f"Không hỗ trợ: {type(node).__name__}")

        expr = (expression or "").strip()
        if not expr:
            return "Biểu thức rỗng."

        expr = expr.replace("^", "**")
        expr = re.sub(r"[xX]", "*", expr)
        expr = expr.replace(":", "/")
        expr = re.sub(r"[^\d\+\-\*/%\(\)\.\s]", "", expr)

        if not expr.strip():
            return "Biểu thức không hợp lệ."

        tree = ast.parse(expr, mode="eval")
        result = eval_node(tree.body)

        if isinstance(result, float):
            if result.is_integer():
                result = int(result)
            else:
                result = round(result, 4)

        return f"{expr.strip()} = {result}"
    except Exception as e:
        logger.warning(f"calculate lỗi: {e}")
        return f"Không tính được '{expression}'. Lỗi: {e}"


# =====================================================
# AIR QUALITY (MQ135)
# =====================================================

async def _tool_get_air_quality() -> str:
    if sensor_state is None:
        return "Lỗi: chưa có module sensor_state."

    if not sensor_state.is_fresh(max_age_sec=300):
        return (
            "Chưa có dữ liệu cảm biến không khí. "
            "Kiểm tra ESP32 đã kết nối chưa."
        )

    ppm = sensor_state.get("air_quality_ppm")
    if ppm is None:
        return "Chưa có dữ liệu từ cảm biến MQ135."

    try:
        ppm = float(ppm)
    except (ValueError, TypeError):
        return "Dữ liệu cảm biến không hợp lệ."

    if ppm < 400:
        level = "rất tốt"
        advice = "Không khí trong lành."
    elif ppm < 800:
        level = "tốt"
        advice = "Không khí ổn."
    elif ppm < 1500:
        level = "trung bình"
        advice = "Nên mở cửa sổ cho thoáng."
    elif ppm < 2500:
        level = "kém"
        advice = "Không khí kém, nên thông gió ngay."
    else:
        level = "nguy hiểm"
        advice = "Cảnh báo: không khí rất kém, mở cửa ngay!"

    return (
        f"Chất lượng không khí hiện tại ở mức {level}, "
        f"khoảng {ppm:.0f} ppm. {advice}"
    )

# =====================================================
# MCP — GỬI LỆNH XUỐNG ESP32
# =====================================================

async def _send_mcp_command(
    method: str,
    params: dict = None,
    timeout: float = 3.0,
) -> dict:
    """Gửi lệnh MCP xuống device theo chuẩn JSON-RPC 2.0."""
    import asyncio
    from app.core.mqtt_server import get_mqtt_manager

    manager = get_mqtt_manager()
    if not manager.sessions:
        return {"ok": False, "error": "Không có thiết bị nào kết nối."}

    device_id = list(manager.sessions.keys())[0]
    s = manager.sessions[device_id]
    transport = s["transport"]

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    s["_mcp_future"] = fut

    try:
        await transport.send_json({
            "type": "mcp",
            "payload": {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": method,
                    "arguments": params or {},
                },
            },
        })
        logger.info(f"📤 MCP → {device_id}: {method}({params})")

        try:
            reply = await asyncio.wait_for(fut, timeout=timeout)
            logger.info(f"📥 MCP reply: {str(reply)[:200]}")
            return {"ok": True, "device_id": device_id, "reply": reply}
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"Timeout {timeout}s chờ reply"}
    except Exception as e:
        logger.error(f"MCP send lỗi: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        s.pop("_mcp_future", None)


async def _tool_lamp_turn_on() -> str:
    result = await _send_mcp_command("Lamp.TurnOn")
    if result["ok"]:
        return "Đã bật đèn."
    return f"Không bật được đèn: {result.get('error')}"


async def _tool_lamp_turn_off() -> str:
    result = await _send_mcp_command("Lamp.TurnOff")
    if result["ok"]:
        return "Đã tắt đèn."
    return f"Không tắt được đèn: {result.get('error')}"


async def _tool_lamp_set_brightness(brightness: int) -> str:
    brightness = max(0, min(100, int(brightness)))
    result = await _send_mcp_command(
        "Lamp.SetBrightness", {"value": brightness}
    )
    if result["ok"]:
        return f"Đã đặt độ sáng {brightness}%."
    return f"Không đổi được độ sáng: {result.get('error')}"


async def _tool_lamp_set_color_temp(color_temp: int) -> str:
    color_temp = max(0, min(100, int(color_temp)))
    result = await _send_mcp_command(
        "Lamp.SetColorTemp", {"value": color_temp}
    )
    if result["ok"]:
        return f"Đã đặt nhiệt độ màu {color_temp}."
    return f"Không đổi được màu: {result.get('error')}"


async def _tool_get_sensor(sensor: str = "all") -> str:
    if sensor_state is not None:
        if sensor == "all":
            data = sensor_state.get_all()
            if not sensor_state.is_fresh(max_age_sec=300):
                return "Chưa có dữ liệu cảm biến. Kiểm tra ESP32 đã kết nối chưa."

            parts = []
            if data.get("temperature") is not None:
                parts.append(f"nhiệt độ {data['temperature']}°C")
            if data.get("humidity") is not None:
                parts.append(f"độ ẩm {data['humidity']}%")
            if data.get("air_quality_ppm") is not None:
                parts.append(f"không khí {data['air_quality_ppm']} ppm")
            if data.get("light_lux") is not None:
                parts.append(f"ánh sáng {data['light_lux']} lux")
            if data.get("presence") is not None:
                parts.append("có người" if data["presence"] else "không có người")

            return "Phòng hiện tại: " + ", ".join(parts) + "."
        else:
            value = sensor_state.get(sensor)
            if value is None:
                return f"Chưa có dữ liệu {sensor}."
            return f"{sensor} hiện tại: {value}"

    result = await _send_mcp_command("Sensor.Read", {"sensor": sensor})
    if result["ok"]:
        return f"Đã yêu cầu đọc {sensor}."
    return "Không đọc được cảm biến."
