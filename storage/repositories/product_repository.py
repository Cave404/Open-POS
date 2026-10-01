"""
=============================================================================
Open-POS Product Repository (storage/repositories/product_repository.py)
=============================================================================
Abstracts merchandise catalog queries, preset quick-keys, barcode matching,
and inventory lookups. Isolates presentation layer from data schema.
=============================================================================
"""

import logging
from typing import Optional, Dict, Any, List
from storage.database import get_db_connection, execute_sql

logger = logging.getLogger("openpos.storage.product_repository")

DEFAULT_PRESET_PRODUCTS = [
    {"sku": "ACC-SLV-001", "name": "Matte Card Sleeves (100ct)", "price": 11.99, "category": "Accessories", "icon": "🛡️", "taxable": True},
    {"sku": "ACC-DKB-002", "name": "Deck Box (80+ Cards)", "price": 4.99, "category": "Accessories", "icon": "📦", "taxable": True},
    {"sku": "ACC-MAT-003", "name": "Custom Stitched Playmat", "price": 24.99, "category": "Accessories", "icon": "🎨", "taxable": True},
    {"sku": "ACC-DCE-004", "name": "Spindown / Dice Set", "price": 7.49, "category": "Accessories", "icon": "🎲", "taxable": True},
    {"sku": "TCG-BST-001", "name": "Booster Pack (Standard)", "price": 4.99, "category": "TCG Sealed", "icon": "🃏", "taxable": True},
    {"sku": "TCG-BDL-002", "name": "Collector Booster Pack", "price": 24.99, "category": "TCG Sealed", "icon": "✨", "taxable": True},
    {"sku": "TCG-EVT-001", "name": "Weekly Tournament Entry", "price": 10.00, "category": "Events", "icon": "🎟️", "taxable": False},
    {"sku": "FNB-SDA-001", "name": "Cold Beverage / Soda", "price": 2.25, "category": "Snacks", "icon": "🥤", "taxable": True},
    {"sku": "FNB-SNK-002", "name": "Gourmet Candy / Snack", "price": 2.50, "category": "Snacks", "icon": "🍫", "taxable": True},
]


class ProductRepository:
    @staticmethod
    def get_presets() -> List[Dict[str, Any]]:
        """Returns the quick-key merchandise presets."""
        return list(DEFAULT_PRESET_PRODUCTS)

    @staticmethod
    def find_by_barcode(barcode: str) -> Optional[Dict[str, Any]]:
        """
        Looks up product by SKU or barcode across preset catalog and database inventory.
        """
        target = barcode.strip().lower()

        # 1. Preset matching
        for item in DEFAULT_PRESET_PRODUCTS:
            if item["sku"].lower() == target:
                return dict(item)

        # 2. Database inventory table lookup if available
        try:
            with get_db_connection() as conn:
                cur = execute_sql(
                    conn,
                    "SELECT * FROM singles_inventory WHERE scryfall_id = ? OR card_name = ? LIMIT 1",
                    (barcode, barcode)
                )
                row = cur.fetchone()
                if row:
                    row_dict = dict(row)
                    return {
                        "sku": row_dict.get("scryfall_id", barcode),
                        "name": row_dict.get("card_name", barcode),
                        "price": float(row_dict.get("sell_price", 0.0) or 0.0),
                        "taxable": True,
                        "metadata": {
                            "condition": row_dict.get("condition", "NM"),
                            "is_foil": bool(row_dict.get("is_foil", 0))
                        }
                    }
        except Exception:
            pass

        return None

    @staticmethod
    def search(query_str: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Searches preset catalog and database inventory matching query string."""
        q = query_str.strip().lower()
        results = []

        for p in DEFAULT_PRESET_PRODUCTS:
            if q in p["name"].lower() or q in p["sku"].lower() or q in p.get("category", "").lower():
                results.append(dict(p))

        if len(results) < limit:
            try:
                with get_db_connection() as conn:
                    cur = execute_sql(
                        conn,
                        "SELECT * FROM singles_inventory WHERE card_name LIKE ? LIMIT ?",
                        (f"%{query_str}%", limit - len(results))
                    )
                    for row in cur.fetchall():
                        rd = dict(row)
                        results.append({
                            "sku": rd.get("scryfall_id", ""),
                            "name": rd.get("card_name", ""),
                            "price": float(rd.get("sell_price", 0.0) or 0.0),
                            "taxable": True,
                            "category": "Singles",
                            "metadata": {
                                "condition": rd.get("condition", "NM"),
                                "is_foil": bool(rd.get("is_foil", 0))
                            }
                        })
            except Exception:
                pass

        return results[:limit]
