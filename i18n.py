import json, os
from pathlib import Path

_cache = {}

def load_translations(lang: str) -> dict:
    if lang in _cache:
        return _cache[lang]
    path = Path(__file__).parent / "translations" / f"{lang}.json"
    fallback = Path(__file__).parent / "translations" / "he.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        with open(fallback, encoding="utf-8") as f:
            data = json.load(f)
    _cache[lang] = data
    return data

def t(key: str, lang: str = "he", **kwargs) -> str:
    """Translate key to lang. Falls back to key itself if not found."""
    strings = load_translations(lang)
    val = strings.get(key, key)
    if kwargs:
        try:
            val = val.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return val
