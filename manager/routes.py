import os
import json
from flask import Blueprint, jsonify, render_template

manager_bp = Blueprint(
    'manager',
    __name__,
    url_prefix='/manager',
    template_folder='templates'
)

BUILTIN_APPLETS = [
    {
        "id": "branding",
        "title": "Store_Branding",
        "category": "Desktop_Controls",
        "icon": "color.png",
        "target": "/manager/branding"
    },
    {
        "id": "database",
        "title": "Database_Tools",
        "category": "Desktop_Tools",
        "icon": "tools.png",
        "target": "/manager/database"
    },
    {
        "id": "network",
        "title": "Network_Settings",
        "category": "System_Admin",
        "icon": "network.png",
        "target": "/manager/network"
    },
    {
        "id": "cache",
        "title": "Art_Cache_Purge",
        "category": "Desktop_Tools",
        "icon": "brush.png",
        "target": "/manager/cache"
    },
    {
        "id": "logs",
        "title": "Terminal_Logs",
        "category": "System_Admin",
        "icon": "terminal.png",
        "target": "/manager/logs"
    },
]

@manager_bp.route('/')
def manager_index():
    return render_template('manager.html')

@manager_bp.route('/api/applets')
def list_applets():
    applets = list(BUILTIN_APPLETS)
    addons_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'addons'))

    if os.path.exists(addons_dir):
        for entry in os.listdir(addons_dir):
            manifest_path = os.path.join(addons_dir, entry, 'manifest.json')
            if os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                        applets.append({
                            "id": meta.get("id", entry),
                            "title": meta.get("name", entry),
                            "category": meta.get("category", "Desktop_Apps"),
                            "icon": meta.get("icon", "generic_app.png"),
                            "target": f"/addons/{entry}/admin",
                            "is_addon": True,
                            "enabled": meta.get("enabled", True)
                        })
                except Exception:
                    continue

    return jsonify(applets)