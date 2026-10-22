"""Test SearXNG với query tiếng Việt."""
import httpx
import json


SEARXNG_URL = "http://localhost:8888/search"


def search(query: str, language: str = "vi-VN"):
    r = httpx.get(
        SEARXNG_URL,
        params={
            "q": query,
            "format": "json",
            "language": language,
            "safesearch": 1,
        },
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    print(f"Query: {data.get('query')}")
    print(f"Number of results: {len(data.get('results', []))}")
    print(f"Unresponsive engines: {data.get('unresponsive_engines')}")
    print()

    for i, res in enumerate(data.get("results", [])[:5], 1):
        print(f"[{i}] {res.get('title')}")
        print(f"    {res.get('url')}")
        print(f"    Engine: {res.get('engine')}")
        print(f"    {res.get('content', '')[:150]}")
        print()


if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: 'đội tuyển việt nam'")
    print("=" * 60)
    search("đội tuyển việt nam")

    print("\n" + "=" * 60)
    print("Test 2: 'thời tiết Hà Nội'")
    print("=" * 60)
    search("thời tiết Hà Nội")

    print("\n" + "=" * 60)
    print("Test 3: 'tin tức công nghệ'")
    print("=" * 60)
    search("tin tức công nghệ")