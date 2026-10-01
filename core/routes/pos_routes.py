"""
=============================================================================
Open-POS Core POS Routes Shim (core/routes/pos_routes.py)
=============================================================================
Provides backward-compatible facade re-exporting pos_bp and helper functions
from the restructured presentation layer (ui.routes.pos_routes).
=============================================================================
"""

import sys
import ui.routes.pos_routes

sys.modules[__name__] = ui.routes.pos_routes
