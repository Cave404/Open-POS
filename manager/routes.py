"""
=============================================================================
Open-POS System Manager & System API Controller
=============================================================================
This module governs:
  1. Built-in Manager Applets & dynamic addon manifest discovery.
  2. Safe Navigation Guard: Guarantees that any built-in or addon applet
     renders an informative placeholder view instead of resulting in a dead end.
  3. Settings REST APIs (/api/settings) with validation and persistence.
  4. System Credits & Third-Party Dependency Licensing Audit (/api/system/credits).
  5. Dedicated View Endpoints (/manager/branding, /manager/about).
=============================================================================
"""

import os
import re
import json
import logging
import importlib.metadata
from flask import Blueprint, jsonify, render_template, request, send_file
from core.settings import get_all_settings, get_setting, set_setting

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Blueprint Registrations
# -----------------------------------------------------------------------------
# manager_bp handles HTML views and manager-specific internal routes
manager_bp = Blueprint(
    'manager',
    __name__,
    url_prefix='/manager',
    template_folder='templates'
)

# api_bp handles cross-system JSON REST endpoints mounted at /api/
api_bp = Blueprint(
    'api',
    __name__,
    url_prefix='/api'
)


# -----------------------------------------------------------------------------
# Built-In Applet Registry & Fallback Metadata
# -----------------------------------------------------------------------------
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
    {
        "id": "about",
        "title": "About_&_Credits",
        "category": "System_Admin",
        "icon": "info.png",
        "target": "/manager/about"
    },
]

# Informative metadata for applets currently undergoing active engineering
APPLETS_META = {
    "database": {
        "title": "Database Tools",
        "icon": "💾",
        "category": "Desktop Tools",
        "description": "Run SQLite/PostgreSQL vacuum compaction, schema integrity checks, automated backups, and catalog restore operations."
    },
    "network": {
        "title": "Network Settings",
        "icon": "🌐",
        "category": "System Admin",
        "description": "Configure host binding interfaces (0.0.0.0 vs localhost), port assignments, SSL/TLS certificates, and Customer Facing Display (CFD) pairing."
    },
    "cache": {
        "title": "Art Cache Purge",
        "icon": "🧹",
        "category": "Desktop Tools",
        "description": "Inspect and prune card artwork image cache files (MTG/Pokémon/TCG) to reclaim local disk space without deleting database records."
    },
    "logs": {
        "title": "Terminal Logs",
        "icon": "📜",
        "category": "System Admin",
        "description": "View live system runtime traces, background WSGI requests, database query performance, and diagnostic export bundles."
    },
    "about": {
        "title": "About & Credits",
        "icon": "ℹ️",
        "category": "System Admin",
        "description": "System credits, contributors ledger, and third-party dependency licensing audit."
    }
}

# Curated dependency metadata mapping package names to license, purpose, and upstream URL
KNOWN_DEPENDENCIES = {
    "flask": {
        "name": "Flask",
        "purpose": "Lightweight WSGI web application framework powering REST API services and manager dashboards.",
        "license": "BSD-3-Clause",
        "url": "https://github.com/pallets/flask"
    },
    "waitress": {
        "name": "Waitress",
        "purpose": "Production-quality pure-Python WSGI server designed for high-concurrency Windows deployments.",
        "license": "ZPL-2.1",
        "url": "https://github.com/Pylons/waitress"
    },
    "psycopg": {
        "name": "psycopg",
        "purpose": "PostgreSQL database adapter with native connection pooling and asynchronous query capabilities.",
        "license": "LGPL-3.0-or-later",
        "url": "https://github.com/psycopg/psycopg"
    },
    "cryptography": {
        "name": "cryptography",
        "purpose": "Cryptographic recipes and primitives for token verification and symmetric credential encryption.",
        "license": "Apache-2.0 / BSD-3-Clause",
        "url": "https://github.com/pyca/cryptography"
    },
    "python-dotenv": {
        "name": "python-dotenv",
        "purpose": "Reads key-value pairs from .env files and sets them as environment variables.",
        "license": "BSD-3-Clause",
        "url": "https://github.com/theskumar/python-dotenv"
    },
    "requests": {
        "name": "requests",
        "purpose": "Elegant HTTP client for external card database lookups (Scryfall, TCGdex) and webhooks.",
        "license": "Apache-2.0",
        "url": "https://github.com/psf/requests"
    },
    "pytest": {
        "name": "pytest",
        "purpose": "Mature testing framework for running unit, integration, and database regression test suites.",
        "license": "MIT",
        "url": "https://github.com/pytest-dev/pytest"
    },
    "pywebview": {
        "name": "pywebview",
        "purpose": "Lightweight cross-platform desktop wrapper embedding Microsoft Edge Chromium (WebView2).",
        "license": "BSD-3-Clause",
        "url": "https://github.com/r0x0r/pywebview"
    },
    "pystray": {
        "name": "pystray",
        "purpose": "System tray icon controller providing persistent background supervision and notification menus.",
        "license": "LGPL-3.0-or-later",
        "url": "https://github.com/moses-palmer/pystray"
    },
    "pillow": {
        "name": "Pillow",
        "purpose": "Python Imaging Library fork used for in-memory raster icon generation and card art processing.",
        "license": "HPND",
        "url": "https://github.com/python-pillow/Pillow"
    }
}


# -----------------------------------------------------------------------------
# 1. Dashboard & Applet Navigation Handlers
# -----------------------------------------------------------------------------
@manager_bp.route('/')
def manager_index():
    """Renders the primary full-window HTML5 System Manager dashboard."""
    return render_template('manager.html')


@manager_bp.route('/splash')
def manager_splash():
    """Renders the startup splash window view."""
    return render_template('splash.html')


@manager_bp.route('/splash_image')
def manager_splash_image():
    """Serves the open_pos_splash.png graphic asset."""
    splash_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'open_pos_splash.png'))
    return send_file(splash_path, mimetype='image/png')


@manager_bp.route('/branding')
def manager_branding():
    """Renders the Store Branding & Business Rules configuration panel."""
    return render_template('branding.html')


@manager_bp.route('/about')
def manager_about():
    """Renders the About & Credits dependency audit view."""
    return render_template('about.html')


@manager_bp.route('/placeholder/<applet_id>')
def manager_placeholder(applet_id):
    """
    Universal Safe Navigation Fallback:
    Renders an informative placeholder page with prominent return navigation,
    guaranteeing that no applet or newly registered addon ever leads to a dead end.
    """
    meta = APPLETS_META.get(applet_id, {
        "title": applet_id.replace('_', ' ').title(),
        "icon": "⚙️",
        "category": "System Module",
        "description": "This management applet is slated for an upcoming development sprint."
    })
    return render_template('placeholder.html', applet=meta)


# Explicit route bindings for built-in applets under construction
@manager_bp.route('/database')
def manager_database():
    return manager_placeholder('database')


@manager_bp.route('/network')
def manager_network():
    return manager_placeholder('network')


@manager_bp.route('/cache')
def manager_cache():
    return manager_placeholder('cache')


@manager_bp.route('/logs')
def manager_logs():
    return manager_placeholder('logs')


@manager_bp.route('/api/applets')
def list_applets():
    """
    Returns a dynamic list of built-in applets and discovered addon manifests.
    Addons are read from the /addons directory if present.
    """
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
                except Exception as e:
                    logger.warning(f"Could not load addon manifest for {entry}: {e}")
                    continue

    return jsonify(applets)


# -----------------------------------------------------------------------------
# 2. System Credits & Dependency Audit API
# -----------------------------------------------------------------------------
@api_bp.route('/system/credits', methods=['GET'])
@manager_bp.route('/api/system/credits', methods=['GET'])
def get_system_credits():
    """
    Returns an audited inventory of active third-party dependencies dynamically
    parsed from requirements.txt, enriched with installed versions, functional roles,
    license classifications, and upstream source repositories.
    """
    req_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'requirements.txt'))
    dependencies = []

    if os.path.exists(req_file):
        try:
            with open(req_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # Extract raw package name stripped of version pins (e.g. 'Flask>=3.0.0')
                    raw_pkg = re.split(r'[<>=!~;]', line)[0].strip()
                    # Strip bracket extras like [binary,pool]
                    base_pkg = re.sub(r'\[.*\]', '', raw_pkg).strip()

                    # Query dynamic version via importlib.metadata
                    try:
                        installed_version = importlib.metadata.version(base_pkg)
                    except Exception:
                        installed_version = "Installed"

                    lookup_key = base_pkg.lower()
                    meta = KNOWN_DEPENDENCIES.get(lookup_key, {
                        "name": base_pkg,
                        "purpose": "Core runtime peripheral or utility dependency.",
                        "license": "Open Source",
                        "url": f"https://pypi.org/project/{base_pkg}/"
                    })

                    dependencies.append({
                        "name": meta["name"],
                        "version": installed_version,
                        "license": meta["license"],
                        "purpose": meta["purpose"],
                        "url": meta["url"]
                    })
        except Exception as e:
            logger.error(f"Error reading requirements.txt: {e}")

    credits_payload = {
        "version": "v1.0.0-alpha",
        "repository": "https://github.com/Cave404/Open-POS",
        "authors": [
            {"name": "Cave404", "role": "Lead Architect & Maintainer"},
            {"name": "Open-POS Community", "role": "Core Contributors"}
        ],
        "dependencies": dependencies
    }

    return jsonify(credits_payload)


# -----------------------------------------------------------------------------
# 3. Settings Configuration REST Endpoints
# -----------------------------------------------------------------------------
def handle_get_settings():
    """Helper delivering current active configuration settings as JSON."""
    return jsonify(get_all_settings())


def handle_update_settings():
    """
    Validates incoming JSON updates for store branding and business rules,
    persists compliant parameters to the settings table, and returns status.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "Expected a JSON object payload."}), 400

    validated = {}

    # Validate Store Name (non-empty string required)
    if 'store_name' in data:
        name = str(data['store_name']).strip()
        if not name:
            return jsonify({"status": "error", "message": "Store name cannot be empty."}), 400
        validated['store_name'] = name

    # Validate Legal Entity Name
    if 'store_legal_entity' in data:
        validated['store_legal_entity'] = str(data['store_legal_entity']).strip()

    # Validate City/State Location
    if 'store_location' in data:
        validated['store_location'] = str(data['store_location']).strip()

    # Validate Cash Payout Rate (Percentage between 0.0 and 100.0)
    if 'cash_payout_rate' in data:
        try:
            val = float(data['cash_payout_rate'])
            if not (0.0 <= val <= 100.0):
                raise ValueError("Out of range")
            validated['cash_payout_rate'] = val
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Cash payout rate must be a percentage between 0 and 100."}), 400

    # Validate Store Credit Payout Rate (Percentage between 0.0 and 100.0)
    if 'credit_payout_rate' in data:
        try:
            val = float(data['credit_payout_rate'])
            if not (0.0 <= val <= 100.0):
                raise ValueError("Out of range")
            validated['credit_payout_rate'] = val
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Credit payout rate must be a percentage between 0 and 100."}), 400

    # Validate Daily Customer Trade Limit (Integer >= 1)
    if 'daily_trade_limit' in data:
        try:
            val = int(data['daily_trade_limit'])
            if val < 1:
                raise ValueError("Must be positive integer")
            validated['daily_trade_limit'] = val
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Daily customer trade limit must be an integer greater than or equal to 1."}), 400

    # Validate Condition Multipliers (Map of NM, LP, MP, HP, DMG weights)
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
                return jsonify({
                    "status": "error",
                    "message": f"Invalid condition code: {cond}. Valid codes are: {', '.join(sorted(valid_conditions))}"
                }), 400
            try:
                rate_val = float(rate)
                if rate_val < 0.0 or rate_val > 5.0:
                    raise ValueError("Rate out of bounds")
                parsed_mults[cond] = round(rate_val, 4)
            except (ValueError, TypeError):
                return jsonify({
                    "status": "error",
                    "message": f"Condition multiplier for {cond} must be a non-negative number."
                }), 400

        # Preserve any unmentioned conditions from existing configuration
        current_raw = get_setting('condition_multipliers', '{}')
        try:
            current_mults = json.loads(current_raw) if isinstance(current_raw, str) else current_raw
        except Exception:
            current_mults = {}

        for cond in valid_conditions:
            if cond not in parsed_mults and cond in current_mults:
                parsed_mults[cond] = current_mults[cond]

        validated['condition_multipliers'] = json.dumps(parsed_mults)

    # Persist all validated settings to database
    for k, v in validated.items():
        success = set_setting(k, v)
        if not success:
            return jsonify({"status": "error", "message": f"Failed to persist setting: {k}"}), 500

    return jsonify({"status": "success"})


# Register API routes on both /api/settings and /manager/api/settings
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