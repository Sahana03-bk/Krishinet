# news_aggregator.py
import os
import requests

NEWS_API_KEY = os.getenv("NEWS_API_KEY") or os.getenv("NEWSAPI_KEY") or ""

_LANGS = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "bn": "Bengali",
    "ta": "Tamil", "te": "Telugu", "kn": "Kannada", "gu": "Gujarati"
}

def list_languages():
    return [{"code": k, "name": v} for k, v in _LANGS.items()]

def get_news(lang="en", limit=12):
    if not NEWS_API_KEY:
        return []
    q = "agriculture OR farming OR crop OR farmer OR agro"
    params = {
        "q": q,
        "pageSize": min(100, int(limit or 12)),
        "language": lang if lang in _LANGS else "en",
        "sortBy": "publishedAt",
        "apiKey": NEWS_API_KEY,
    }
    try:
        r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
        items = []
        for a in j.get("articles", [])[:limit]:
            items.append({
                "title": a.get("title"),
                "link": a.get("url"),
                "source": (a.get("source") or {}).get("name"),
                "published": a.get("publishedAt"),
                "description": a.get("description"),
                "image": a.get("urlToImage"),
            })
        return items
    except Exception:
        return []
