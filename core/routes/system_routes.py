"""
=============================================================================
Open-POS Core System Routes Shim (core/routes/system_routes.py)
=============================================================================
Provides backward-compatible facade re-exporting system_bp
from the restructured presentation layer (ui.routes.system_routes).
=============================================================================
"""

import sys
import ui.routes.system_routes

sys.modules[__name__] = ui.routes.system_routes
