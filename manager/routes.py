import os
import json
from flask import Blueprint, jsonify, render_template, request
from core.settings import get_all_settings, get_setting, set_setting

manager_bp = Blueprint(
    'manager',
    __name__,
    url_prefix='/manager',
    template_folder='templates'
)

api_bp = Blueprint(
    'api',
    __name__,
    url_prefix='/api'
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

@manager_bp.route('/branding')
def manager_branding():
    return render_template('branding.html')

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


def handle_get_settings():
    return jsonify(get_all_settings())


def handle_update_settings():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Expected a JSON object payload."}), 400

    validated = {}

    # Validate Store Name
    if 'store_name' in data:
        name = str(data['store_name']).strip()
        if not name:
            return jsonify({"status": "error", "message": "Store name cannot be empty."}), 400
        validated['store_name'] = name

    # Validate Legal Entity Name
    if 'store_legal_entity' in data:
        validated['store_legal_entity'] = str(data['store_legal_entity']).strip()

    # Validate Location
    if 'store_location' in data:
        validated['store_location'] = str(data['store_location']).strip()

    # Validate Cash Payout Rate (Percentage: 0.0 - 100.0)
    if 'cash_payout_rate' in data:
        try:
            val = float(data['cash_payout_rate'])
            if not (0.0 <= val <= 100.0):
                raise ValueError("Out of range")
            validated['cash_payout_rate'] = val
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Cash payout rate must be a percentage between 0 and 100."}), 400

    # Validate Credit Payout Rate (Percentage: 0.0 - 100.0)
    if 'credit_payout_rate' in data:
        try:
            val = float(data['credit_payout_rate'])
            if not (0.0 <= val <= 100.0):
                raise ValueError("Out of range")
            validated['credit_payout_rate'] = val
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Credit payout rate must be a percentage between 0 and 100."}), 400

    # Validate Daily Trade Limit (Integer >= 1)
    if 'daily_trade_limit' in data:
        try:
            val = int(data['daily_trade_limit'])
            if val < 1:
                raise ValueError("Must be positive integer")
            validated['daily_trade_limit'] = val
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Daily customer trade limit must be an integer greater than or equal to 1."}), 400

    # Validate Condition Multipliers
    if 'condition_multipliers' in data:
        mults = data['condition_multipliers']
        if isinstance(mults, str):
            try:
                mults = json.loads(mults)
            except Exception:
                return jsonify({"status": "error", "message": "Condition multipliers must be valid JSON."}), 400

        if not isinstance(mults, dict):
            return jsonify({"status": "error", "message": "Condition multipliers must be a dictionary."}), 400

        valid_conditions = {'NM', 'LP', 'MP', 'HP', 'DMG'}
        parsed_mults = {}
        for cond, rate in mults.items():
            if cond not in valid_conditions:
                return jsonify({"status": "error", "message": f"Invalid condition code: {cond}. Valid codes are: {', '.join(sorted(valid_conditions))}"}), 400
            try:
                rate_val = float(rate)
                if rate_val < 0.0 or rate_val > 5.0:
                    raise ValueError("Rate out of bounds")
                parsed_mults[cond] = round(rate_val, 4)
            except (ValueError, TypeError):
                return jsonify({"status": "error", "message": f"Condition multiplier for {cond} must be a non-negative number."}), 400

        # Ensure all standard conditions are present, filling from current if needed
        current_raw = get_setting('condition_multipliers', '{}')
        try:
            current_mults = json.loads(current_raw) if isinstance(current_raw, str) else current_raw
        except Exception:
            current_mults = {}

        for cond in valid_conditions:
            if cond not in parsed_mults and cond in current_mults:
                parsed_mults[cond] = current_mults[cond]

        validated['condition_multipliers'] = json.dumps(parsed_mults)

    # Persist all validated settings
    for k, v in validated.items():
        success = set_setting(k, v)
        if not success:
            return jsonify({"status": "error", "message": f"Failed to persist setting: {k}"}), 500

    return jsonify({"status": "success"})


# Register API endpoints on both /api/settings and /manager/api/settings
@api_bp.route('/settings', methods=['GET'])
def api_get_settings():
    return handle_get_settings()

@api_bp.route('/settings', methods=['POST'])
def api_post_settings():
    return handle_update_settings()

@manager_bp.route('/api/settings', methods=['GET'])
def manager_get_settings():
    return handle_get_settings()

@manager_bp.route('/api/settings', methods=['POST'])
def manager_post_settings():
    return handle_update_settings()