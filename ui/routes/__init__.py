"""
UI Presentation Routes Package (ui/routes/)
"""

from ui.routes.pos_routes import pos_bp
from ui.routes.manager_routes import manager_bp, api_bp
from ui.routes.system_routes import system_bp

__all__ = [
    "pos_bp",
    "manager_bp",
    "api_bp",
    "system_bp",
]
