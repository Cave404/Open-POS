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
CACHE_TTL_SECONDS = 6 * 3600  # 6 hours


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
    Fetches the remote addon catalog.
    - Inspects data/cache/catalog_cache.json if younger than 6 hours (unless force_refresh is True).
    - Fetches via non-blocking requests.get() with a 5-second timeout.
    - If network is unreachable or offline, returns cached catalog or clean empty list [] without crashing.
    """
    cache_file = _get_cache_path()
    now = time.time()

    # 1. Inspect existing cache validity
    cached_data: Optional[List[Dict[str, Any]]] = None
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                if not isinstance(cached_data, list):
                    cached_data = None
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

    # 2. Remote fetch with 5-second timeout
    catalog_url = get_setting("addon_catalog_url", DEFAULT_CATALOG_URL)
    try:
        logger.info(f"Fetching remote addon catalog from {catalog_url}...")
        resp = requests.get(catalog_url, timeout=5)
        if resp.status_code == 200:
            catalog_list = resp.json()
            if isinstance(catalog_list, list):
                try:
                    with open(cache_file, 'w', encoding='utf-8') as f:
                        json.dump(catalog_list, f, indent=2)
                except Exception as we:
                    logger.warning(f"Failed to persist catalog cache: {we}")
                return catalog_list
            else:
                logger.error(f"Catalog response is not a list: {type(catalog_list)}")
        else:
            logger.warning(f"Catalog URL returned HTTP {resp.status_code}")
    except Exception as exc:
        logger.warning(f"Network error fetching addon catalog ({exc}). Entering offline resilience mode.")

    # 3. Fallback: return stale cached catalog if available, else empty list
    if cached_data is not None:
        logger.info("Using stale catalog cache due to network unavailability.")
        return cached_data

    return []


def get_catalog_item(addon_id: str) -> Optional[Dict[str, Any]]:
    """Returns a single catalog item by ID, or None if not listed."""
    catalog = fetch_catalog()
    for item in catalog:
        if isinstance(item, dict) and item.get("id") == addon_id:
            return item
    return None
