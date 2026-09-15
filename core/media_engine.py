import json
import os
from hashlib import sha256
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.templatetags.static import static


CATEGORY_TERMS = {
    "tecnologia": "technology students coding industry 4.0",
    "indústria 4.0": "industry 4.0 robotics automation",
    "gestão": "business management young professionals",
    "oratória": "public speaking presentation students",
    "liderança": "young leadership teamwork",
    "entrevista de emprego": "job interview young professional",
}


def _normalized_query(query):
    lowered = (query or "educação profissional").strip().lower()
    for key, value in CATEGORY_TERMS.items():
        if key in lowered:
            return value
    return query or "students professional education"


def _get_json(url, headers=None, timeout=4):
    request = Request(url, headers={"User-Agent": "PIEM-Tusker-Power/3.1", **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def get_contextual_image(query, orientation="landscape"):
    """Busca imagens contextuais e mantém uma ilustração local se os provedores falharem."""
    search = _normalized_query(query)
    digest = sha256(f"{orientation}:{search}".encode()).hexdigest()
    cache_key = f"piem:image:v2:{digest}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
    if unsplash_key:
        params = urlencode({"query": search, "orientation": orientation, "per_page": 1})
        try:
            payload = _get_json(
                f"https://api.unsplash.com/search/photos?{params}",
                {"Authorization": f"Client-ID {unsplash_key}"},
            )
            url = _image_url(payload["results"][0]["urls"]["regular"])
            cache.set(cache_key, url, 86400)
            return url
        except (KeyError, IndexError, OSError, ValueError, TypeError):
            pass

    pexels_key = os.getenv("PEXELS_API_KEY", "")
    if pexels_key:
        params = urlencode({"query": search, "orientation": orientation, "per_page": 1})
        try:
            payload = _get_json(
                f"https://api.pexels.com/v1/search?{params}",
                {"Authorization": pexels_key},
            )
            url = _image_url(payload["photos"][0]["src"]["large2x"])
            cache.set(cache_key, url, 86400)
            return url
        except (KeyError, IndexError, OSError, ValueError, TypeError):
            pass

    fallback = static("core/images/learning-path.svg")
    cache.set(cache_key, fallback, 3600)
    return fallback


def _image_url(value):
    """Ignore broken provider payloads before they become public image URLs."""
    if not isinstance(value, str):
        raise ValueError("Invalid image URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Expected an HTTPS image URL")
    return value
