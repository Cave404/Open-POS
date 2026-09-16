"""
Open-POS Remote Addon Catalog Engine
Provides a resilient catalog registry service for discovering, querying,
and caching available remote OpenPOS plugins from GitHub or custom registries.
"""

import os
import json
import time
import logging
import re
from typing import List, Dict, Any, Optional
import requests

from core.config import Config
from core.settings import get_setting

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/Cave404/Open-POS/main/addons_catalog.json"
DEFAULT_CATALOG_FALLBACK_PATH = os.path.join(os.path.dirname(__file__), 'default_catalog.json')
CACHE_TTL_SECONDS = 6 * 3600  # 6 hours


def _get_bundled_catalog() -> List[Dict[str, Any]]:
    """Loads bundled fallback catalog from core/addons/default_catalog.json."""
    if os.path.isfile(DEFAULT_CATALOG_FALLBACK_PATH):
        try:
            with open(DEFAULT_CATALOG_FALLBACK_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            logger.warning(f"Could not load bundled default_catalog.json: {e}")
    return []


def _get_cache_path() -> str:
    """Returns absolute path to data/cache/catalog_cache.json."""
    cache_dir = getattr(Config, 'CACHE_DIR', os.path.join(Config.DATA_DIR, 'cache'))
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, 'catalog_cache.json')


def parse_version(v_str: str) -> tuple:
    """Parses a version string like 'v1.0.8' or '2.1' into an integer tuple for comparison."""
    if not v_str:
        return (0, 0, 0)
    clean = re.sub(r'^[vV]', '', str(v_str).strip())
    parts = []
    for chunk in clean.split('.'):
        num_match = re.match(r'^\d+', chunk)
        if num_match:
            parts.append(int(num_match.group(0)))
        else:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_compatible(min_core_version: str, current_version: Optional[str] = None) -> bool:
    """
    Checks whether current_version satisfies min_core_version.
    Defaults current_version to Config.VERSION.
    """
    if not min_core_version:
        return True
    cur = current_version or getattr(Config, 'VERSION', 'v1.0.8')
    return parse_version(cur) >= parse_version(min_core_version)


def fetch_catalog(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Fetches the remote addon catalog implementing a three-tier fallback:
    - Tier 1 (Remote): Attempt requests.get() to configured catalog URL with 4-second timeout.
      On HTTP 200, caches to data/cache/catalog_cache.json and returns.
    - Tier 2 (Cache): If remote fails or times out, read from data/cache/catalog_cache.json.
    - Tier 3 (Bundled Fallback): If no cache exists or cache is empty, load core/addons/default_catalog.json.
    """
    cache_file = _get_cache_path()
    now = time.time()

    # 1. Inspect existing cache validity
    cached_data: Optional[List[Dict[str, Any]]] = None
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, list) and len(loaded) > 0:
                    cached_data = loaded
        except Exception as e:
            logger.warning(f"Could not parse catalog cache file: {e}")
            cached_data = None

    if not force_refresh and cached_data is not None:
        try:
            mtime = os.path.getmtime(cache_file)
            if (now - mtime) < CACHE_TTL_SECONDS:
                return cached_data
        except Exception:
            pass

    # Tier 1 (Remote): Attempt requests.get with 4-second timeout
    catalog_url = get_setting("addon_catalog_url", DEFAULT_CATALOG_URL)
    try:
        logger.info(f"Fetching remote addon catalog from {catalog_url}...")
        resp = requests.get(catalog_url, timeout=4)
        if resp.status_code == 200:
            catalog_list = resp.json()
            if isinstance(catalog_list, list) and len(catalog_list) > 0:
                try:
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(catalog_list, f, indent=2)
                except Exception as we:
                    logger.warning(f"Failed to persist catalog cache: {we}")
                return catalog_list
            else:
                logger.warning(f"Catalog response is not a valid list: {catalog_list}")
        else:
            logger.warning(f"Catalog URL returned HTTP {resp.status_code}")
    except Exception as exc:
        logger.warning(f"Network error fetching addon catalog ({exc}). Entering offline resilience mode.")

    # Tier 2 (Cache): Return cached data if present
    if cached_data is not None and len(cached_data) > 0:
        logger.info("Using cached catalog due to network unavailability.")
        return cached_data

    # Tier 3 (Bundled Fallback): Return bundled default catalog
    bundled = _get_bundled_catalog()
    if bundled:
        logger.info("Using bundled default_catalog.json fallback.")
        return bundled

    return []



def get_catalog_item(addon_id: str) -> Optional[Dict[str, Any]]:
    """Returns a single catalog item by ID, or None if not listed."""
    catalog = fetch_catalog()
    for item in catalog:
        if isinstance(item, dict) and item.get("id") == addon_id:
            return item
    return None
