"""
=============================================================================
Open-POS Presentation Manager Routes (ui/routes/manager_routes.py)
=============================================================================
Presentation layer controller for System Manager, settings, applets, and diagnostics.
Maintains identity and monkeypatch compatibility with manager.routes.
=============================================================================
"""

import sys
import manager.routes

# Replace module entry in sys.modules so manager.routes and ui.routes.manager_routes are identical
sys.modules[__name__] = manager.routes