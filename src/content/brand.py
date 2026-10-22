"""Identidade visual: config/brands/base.json + config/brands/<nicho>.json (merge profundo)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config.loader import deep_merge
from src.config.models import Niche

ROOT = Path(__file__).resolve().parents[2]
BASE_BRAND = "config/brands/base.json"


@lru_cache(maxsize=32)
def _read(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def load_brand(niche: Niche) -> dict[str, Any]:
    base = _read(BASE_BRAND)
    if niche.store and niche.store.brand and niche.store.brand != BASE_BRAND:
        brand = deep_merge(base, _read(niche.store.brand))
    else:
        brand = dict(base)
    brand.setdefault("name", niche.name)
    return brand
