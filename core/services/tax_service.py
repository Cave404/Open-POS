"""
=============================================================================
Open-POS Core Tax Service (core/services/tax_service.py)
=============================================================================
Pure business logic for sales tax computations, tax rate resolutions,
and line-level tax apportioning.
=============================================================================
"""

import logging
from typing import Dict, Any, List
from core.settings import get_setting

logger = logging.getLogger("openpos.core.tax")


class TaxService:
    @staticmethod
    def get_default_tax_rate() -> float:
        """
        Retrieves the default configured tax rate percentage (e.g. 8.25)
        and converts it to decimal format (0.0825).
        """
        rate_pct = get_setting("tax_rate", 8.25)
        try:
            return round(float(rate_pct) / 100.0, 4)
        except (ValueError, TypeError):
            return 0.0825

    @staticmethod
    def calculate_tax(taxable_amount: float, tax_rate: float) -> float:
        """
        Calculates sales tax on a given taxable amount at the specified decimal tax rate.
        """
        if taxable_amount <= 0.0 or tax_rate <= 0.0:
            return 0.0
        return round(float(taxable_amount) * float(tax_rate), 2)

    @staticmethod
    def calculate_order_tax(taxable_net: float, tax_rate: float = None) -> Dict[str, float]:
        """
        Computes tax total for taxable net amount.
        """
        rate = tax_rate if tax_rate is not None else TaxService.get_default_tax_rate()
        tax_total = TaxService.calculate_tax(taxable_net, rate)
        return {
            "tax_rate": rate,
            "taxable_net": round(max(0.0, float(taxable_net)), 2),
            "tax_total": tax_total
        }


tax_service = TaxService()
