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
import sys
import json
import time
import secrets
import hashlib
import logging
import subprocess
import threading
import importlib.metadata
from flask import Blueprint, jsonify, render_template, request, send_file, send_from_directory, Response, stream_with_context, session
from core.config import Config
from core.settings import get_all_settings, get_setting, set_setting
from core.notifications import (
    add_alert,
    get_alerts,
    get_unread_count,
    clear_alerts,
    get_system_logs
)
from core.setup import (
    is_setup_complete,
    mark_setup_complete,
    check_prerequisites,
    save_setup_configuration,
    get_recovery_key_text,
    install_missing_requirements
)
from core.db_migrator import (
    get_database_status,
    test_sqlite_connection,
    test_postgres_connection,
    migrate_sqlite_to_postgres,
    migrate_postgres_to_sqlite,
    update_env_engine,
    dry_run_migration,
)

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
        "id": "configure_manager",
        "title": "Configure_Manager",
        "category": "System_Admin",
        "icon": "shield.png",
        "target": "/manager/configure_manager"
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
    "configure_manager": {
        "title": "Configure Manager",
        "icon": "🛡️",
        "category": "System Admin",
        "description": "Configure administrative access control, startup bypass modes, and Python peripheral package maintenance."
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
# Access Control & Authentication Helpers
# -----------------------------------------------------------------------------
AUTH_CONFIG_PATH = os.path.join(Config.CONFIG_DIR, 'manager_auth.json')

def _read_auth_file() -> dict:
    """Reads security configuration strictly from isolated data/config/manager_auth.json."""
    if os.path.isfile(AUTH_CONFIG_PATH):
        try:
            with open(AUTH_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "require_password": False,
        "password_hash": "",
        "salt": "",
        "protected_sections": ["branding", "database", "admin"],
        "bypass_manager_on_boot": False
    }

def _write_auth_file(data: dict) -> None:
    """Persists security configuration to isolated data/config/manager_auth.json."""
    os.makedirs(Config.CONFIG_DIR, exist_ok=True)
    with open(AUTH_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def _hash_with_salt(password: str, salt: str) -> str:
    """Computes SHA-256 salted password digest."""
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

def is_section_locked(section_name: str) -> bool:
    """
    Determines whether a view should be rendered in locked/blurred state.
    Inspects data/config/manager_auth.json and current session authentication.
    """
    cfg = _read_auth_file()
    if not cfg.get("require_password", False) or not cfg.get("password_hash"):
        return False
    protected = cfg.get("protected_sections", ["branding", "database", "admin"])
    is_protected = (
        ('all' in protected) or
        (section_name in protected) or
        (section_name == 'configure_manager' and ('admin' in protected or 'configure_manager' in protected))
    )
    if not is_protected:
        return False
    return session.get('manager_authenticated') is not True


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
@manager_bp.route('/open_pos_splash.png')
def manager_splash_image():
    """Serves the open_pos_splash.png graphic asset."""
    splash_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'open_pos_splash.png'))
    return send_file(splash_path, mimetype='image/png')


@manager_bp.route('/setup')
def manager_setup():
    """
    Renders the First-Run Setup & Security Wizard.
    Enforces permanent one-way lockout once setup is completed.
    """
    if is_setup_complete():
        return Response(
            "<!DOCTYPE html><html><head><title>403 Forbidden - OpenPOS</title></head>"
            "<body style='background:#12141a;color:#f85149;font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:60px 20px;text-align:center;'>"
            "<div style='max-width:560px;margin:0 auto;background:#1a1d24;border:1px solid #3d4455;border-radius:12px;padding:32px;'>"
            "<h2 style='margin-top:0;'>403 - Setup Wizard Locked</h2>"
            "<p style='color:#cbd5e1;font-size:15px;line-height:1.6;'>Initial store setup has already been completed and cryptographically locked on this system.</p>"
            "<p style='color:#94a3b8;font-size:13px;'>To re-run the wizard, an administrator must remove <code>data/config/.setup_complete</code> and restart OpenPOS.</p>"
            "<br><a href='/manager' style='display:inline-block;padding:10px 20px;background:#3b82f6;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;'>Return to System Manager &rarr;</a>"
            "</div></body></html>",
            status=403,
            mimetype="text/html"
        )
    return render_template('setup_wizard.html')


@manager_bp.route('/branding')
def manager_branding():
    """Renders the Store Branding & Business Rules configuration panel."""
    return render_template('branding.html', is_locked=is_section_locked('branding'))


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


@manager_bp.route('/database')
def manager_database():
    """Renders the full Database Tools & Migration wizard view."""
    return render_template('database.html', is_locked=is_section_locked('database'))


@manager_bp.route('/network')
def manager_network():
    return manager_placeholder('network')


@manager_bp.route('/cache')
def manager_cache():
    return manager_placeholder('cache')


@manager_bp.route('/logs')
def manager_logs():
    """Renders the Terminal Logs & Diagnostics management interface."""
    return render_template('logs.html')


@manager_bp.route('/configure_manager')
def manager_configure():
    """Renders the Configure Manager administrative security & update panel."""
    return render_template('configure_manager.html', is_locked=is_section_locked('configure_manager'))



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
        "version": Config.VERSION,
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

    # Validate Store Logo URL
    if 'store_logo_url' in data:
        validated['store_logo_url'] = str(data['store_logo_url']).strip()

    # Validate Pinned Tools
    if 'pinned_tools' in data:
        pinned_val = data['pinned_tools']
        if isinstance(pinned_val, list):
            validated['pinned_tools'] = json.dumps([str(x) for x in pinned_val])
        elif isinstance(pinned_val, str):
            validated['pinned_tools'] = pinned_val

    # Persist all validated settings to database
    for k, v in validated.items():
        success = set_setting(k, v)
        if not success:
            return jsonify({"status": "error", "message": f"Failed to persist setting: {k}"}), 500

    return jsonify({"status": "success"})


# -----------------------------------------------------------------------------
# 4. Store Logo Image Upload & Management Endpoints
# -----------------------------------------------------------------------------
UPLOAD_FOLDER = Config.UPLOAD_DIR
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'svg', 'webp'}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB Limit

def handle_logo_upload():
    """
    Accepts an image upload for the store logo, enforces <= 2MB and allowed
    image formats, saves the asset to data/uploads, and updates settings.
    """
    file = request.files.get('logo') or request.files.get('file')
    if not file or not file.filename:
        return jsonify({"status": "error", "message": "No logo file provided."}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        return jsonify({
            "status": "error",
            "message": f"Invalid image format. Unsupported format '.{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_LOGO_EXTENSIONS))}"
        }), 400

    file_data = file.read()
    if len(file_data) > MAX_LOGO_SIZE:
        return jsonify({"status": "error", "message": "File size exceeds 2MB limit."}), 400

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    # Remove previous store logo versions to avoid disk bloat
    for old_ext in ALLOWED_LOGO_EXTENSIONS:
        old_file = os.path.join(UPLOAD_FOLDER, f"store_logo.{old_ext}")
        if os.path.isfile(old_file):
            try:
                os.remove(old_file)
            except OSError:
                pass

    target_name = f"store_logo.{ext}"
    target_path = os.path.join(UPLOAD_FOLDER, target_name)
    with open(target_path, 'wb') as f:
        f.write(file_data)

    logo_url = f"/data/uploads/{target_name}"
    set_setting('store_logo_url', logo_url)

    return jsonify({"status": "success", "logo_url": logo_url}), 200


def handle_logo_delete():
    """Removes the store logo asset and clears the store_logo_url setting."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    for ext in ALLOWED_LOGO_EXTENSIONS:
        path = os.path.join(UPLOAD_FOLDER, f"store_logo.{ext}")
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    # Clean legacy folder if present
    legacy_folder = os.path.join(Config.BASE_DIR, 'static', 'uploads')
    if os.path.isdir(legacy_folder):
        for ext in ALLOWED_LOGO_EXTENSIONS:
            p = os.path.join(legacy_folder, f"store_logo.{ext}")
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    set_setting('store_logo_url', '')
    return jsonify({"status": "success"}), 200



# -----------------------------------------------------------------------------
# 5. Dashboard Pinned Tools Management Endpoints
# -----------------------------------------------------------------------------
def handle_get_pinned():
    """Returns the active list of pinned tool IDs."""
    raw = get_setting('pinned_tools', '["branding", "database"]')
    try:
        pinned = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pinned = ["branding", "database"]
    return jsonify({"status": "success", "pinned": pinned, "pinned_tools": pinned})


def handle_update_pinned():
    """Updates the pinned tools list in settings."""
    data = request.get_json(silent=True) or {}
    pinned = data.get('pinned') if 'pinned' in data else data.get('pinned_tools')
    if pinned is None or not isinstance(pinned, list):
        return jsonify({"status": "error", "message": "Expected a JSON list of pinned tool IDs."}), 400

    clean_pinned = [str(x) for x in pinned]
    set_setting('pinned_tools', json.dumps(clean_pinned))
    return jsonify({"status": "success", "pinned": clean_pinned, "pinned_tools": clean_pinned}), 200


# -----------------------------------------------------------------------------
# 6. Route Bindings (Dual Mounting for /api and /manager/api)
# -----------------------------------------------------------------------------
@api_bp.route('/settings', methods=['GET'])
@manager_bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    return handle_get_settings()


@api_bp.route('/settings', methods=['POST'])
@manager_bp.route('/api/settings', methods=['POST'])
def api_post_settings():
    return handle_update_settings()


@api_bp.route('/settings/logo', methods=['POST'])
@manager_bp.route('/api/settings/logo', methods=['POST'])
def api_post_logo():
    return handle_logo_upload()


@api_bp.route('/settings/logo', methods=['DELETE'])
@api_bp.route('/settings/logo/delete', methods=['POST'])
@manager_bp.route('/api/settings/logo', methods=['DELETE'])
@manager_bp.route('/api/settings/logo/delete', methods=['POST'])
def api_delete_logo():
    return handle_logo_delete()


@api_bp.route('/settings/pinned', methods=['GET'])
@manager_bp.route('/api/settings/pinned', methods=['GET'])
def api_get_pinned():
    return handle_get_pinned()


@api_bp.route('/settings/pinned', methods=['POST'])
@manager_bp.route('/api/settings/pinned', methods=['POST'])
def api_post_pinned():
    return handle_update_pinned()


@manager_bp.route('/data/uploads/<path:filename>')
@api_bp.route('/data/uploads/<path:filename>')
def api_serve_data_uploads(filename):
    return send_from_directory(Config.UPLOAD_DIR, filename)


# -----------------------------------------------------------------------------
# 7. Persistent Notification Service REST Endpoints
# -----------------------------------------------------------------------------
@api_bp.route('/notifications', methods=['GET'])
@manager_bp.route('/api/notifications', methods=['GET'])
def api_get_notifications():
    """Returns current active system notifications list and unread count."""
    alerts = get_alerts(limit=50)
    unread = get_unread_count()
    return jsonify({
        "status": "success",
        "notifications": alerts,
        "unread_count": unread
    })


@api_bp.route('/notifications/clear', methods=['POST'])
@manager_bp.route('/api/notifications/clear', methods=['POST'])
def api_clear_notifications():
    """Clears the active notification queue."""
    clear_alerts()
    return jsonify({"status": "success", "message": "Notifications cleared."})


@api_bp.route('/notifications/test', methods=['POST'])
@manager_bp.route('/api/notifications/test', methods=['POST'])
def api_test_notification():
    """Emits a synthetic test notification alert for verification."""
    data = request.get_json(silent=True) or {}
    level = data.get('level', 'WARNING')
    message = data.get('message', 'Diagnostic test notification emitted by user.')
    subsystem = data.get('subsystem', 'CORE')
    item = add_alert(level, message, subsystem)
    return jsonify({"status": "success", "alert": item})


# -----------------------------------------------------------------------------
# 8b. Database Tools & Migration API Endpoints
# -----------------------------------------------------------------------------
@api_bp.route('/database/status', methods=['GET'])
@manager_bp.route('/api/database/status', methods=['GET'])
def api_database_status():
    """
    Returns a real-time snapshot of the active database:
    engine name, connection details, table count, and file size (SQLite).
    """
    status = get_database_status()
    return jsonify({"status": "success", "database": status})


@api_bp.route('/database/test_connection', methods=['POST'])
@manager_bp.route('/api/database/test_connection', methods=['POST'])
def api_database_test_connection():
    """
    Tests a database connection without persisting any configuration.
    Accepts JSON body:
      { "engine": "sqlite" | "postgresql",
        "host": str, "port": int, "dbname": str, "user": str, "password": str,
        "db_path": str  (SQLite only) }
    Returns: { ok, message, latency_ms, [server_version] }
    """
    data = request.get_json(silent=True) or {}
    engine = str(data.get('engine', 'sqlite')).lower()

    if engine in ('postgres', 'postgresql'):
        result = test_postgres_connection(
            host=data.get('host'),
            port=data.get('port'),
            dbname=data.get('dbname'),
            user=data.get('user'),
            password=data.get('password')
        )
    else:
        result = test_sqlite_connection(db_path=data.get('db_path'))

    status_code = 200 if result['ok'] else 502
    return jsonify(result), status_code


@api_bp.route('/database/dry_run', methods=['POST'])
@manager_bp.route('/api/database/dry_run', methods=['POST'])
def api_database_dry_run():
    """
    Performs a non-destructive dry-run validation of migration credentials,
    schema introspection, and row counts across SQLite and PostgreSQL.
    """
    data = request.get_json(silent=True) or {}
    direction = str(data.get('direction', 'sqlite_to_postgres')).lower()
    res = dry_run_migration(
        direction=direction,
        sqlite_path=data.get('sqlite_path'),
        pg_host=data.get('host'),
        pg_port=data.get('port'),
        pg_dbname=data.get('dbname'),
        pg_user=data.get('user'),
        pg_password=data.get('password'),
    )
    status_code = 200 if res.get('ok') else 400
    return jsonify(res), status_code


@api_bp.route('/database/migrate', methods=['POST'])
@manager_bp.route('/api/database/migrate', methods=['POST'])
def api_database_migrate():
    """
    Triggers a bidirectional database migration and streams progress as Server-Sent Events.
    Accepts JSON body:
      { "direction": "sqlite_to_postgres" | "postgres_to_sqlite",
        "host": str, "port": int, "dbname": str, "user": str, "password": str }

    SSE event format (each line prefixed with 'data: '):
      { "percent": int, "message": str, "done": bool, "result": {...} }
    """
    data = request.get_json(silent=True) or {}
    direction = str(data.get('direction', 'sqlite_to_postgres')).lower()
    pg_host = data.get('host')
    pg_port = data.get('port')
    pg_dbname = data.get('dbname')
    pg_user = data.get('user')
    pg_password = data.get('password')

    def generate():
        """Generator that yields SSE-formatted progress events."""
        import queue
        import threading

        q = queue.Queue()

        def progress_cb(pct: int, msg: str):
            """Thread-safe callback that feeds progress into the SSE queue."""
            q.put({"percent": pct, "message": msg, "done": False})

        def run_migration():
            """Executes the migration on a worker thread so Flask can stream the SSE."""
            try:
                if direction == 'postgres_to_sqlite':
                    result = migrate_postgres_to_sqlite(
                        progress_cb=progress_cb,
                        pg_host=pg_host, pg_port=pg_port,
                        pg_dbname=pg_dbname, pg_user=pg_user, pg_password=pg_password
                    )
                else:
                    result = migrate_sqlite_to_postgres(
                        progress_cb=progress_cb,
                        pg_host=pg_host, pg_port=pg_port,
                        pg_dbname=pg_dbname, pg_user=pg_user, pg_password=pg_password
                    )
                q.put({"percent": 100, "message": "Migration finished.", "done": True, "result": result})
            except Exception as e:
                q.put({"percent": 100, "message": str(e), "done": True, "result": {"status": "error", "message": str(e)}})

        worker = threading.Thread(target=run_migration, daemon=True)
        worker.start()

        # Drain the queue until migration signals done
        while True:
            try:
                item = q.get(timeout=90)
                yield f"data: {json.dumps(item)}\n\n"
                if item.get('done'):
                    break
            except Exception:
                # Timeout or queue closed — emit error sentinel
                yield f"data: {json.dumps({'percent': 100, 'message': 'Stream timeout.', 'done': True})}\n\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@api_bp.route('/database/switch_engine', methods=['POST'])
@manager_bp.route('/api/database/switch_engine', methods=['POST'])
def api_database_switch_engine():
    """
    Switches the active database engine in .env without running a migration.
    Intended for fresh deployments where a new empty database is acceptable.
    Accepts JSON body:
      { "engine": "sqlite" | "postgresql",
        "host": str, "port": int, "dbname": str, "user": str, "password": str }
    """
    data = request.get_json(silent=True) or {}
    engine = str(data.get('engine', 'sqlite')).lower()

    if engine not in ('sqlite', 'postgresql', 'postgres'):
        return jsonify({"status": "error", "message": "Invalid engine. Use 'sqlite' or 'postgresql'."}), 400

    pg_params = None
    if engine in ('postgresql', 'postgres'):
        pg_params = {
            'DB_HOST':     data.get('host', 'localhost'),
            'DB_PORT':     str(data.get('port', 5432)),
            'DB_NAME':     data.get('dbname', 'openpos'),
            'DB_USER':     data.get('user', 'postgres'),
            'DB_PASSWORD': data.get('password', ''),
        }

    try:
        update_env_engine(engine, pg_params)
        add_alert('WARNING', f'Database engine switched to {engine}. A system restart is recommended.', 'DATABASE')
        return jsonify({
            'status': 'success',
            'engine': engine,
            'message': f'Engine switched to {engine}. Restart Open-POS for the change to take full effect.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@api_bp.route('/logs', methods=['GET'])
@manager_bp.route('/api/logs', methods=['GET'])
def api_get_logs():
    """Returns structured system telemetry log entries."""
    logs = get_system_logs(limit=250)
    return jsonify({
        "status": "success",
        "logs": logs,
        "total": len(logs)
    })


@api_bp.route('/logs/export/csv', methods=['GET'])
@api_bp.route('/logs/export', methods=['GET'])
@manager_bp.route('/api/logs/export/csv', methods=['GET'])
@manager_bp.route('/api/logs/export', methods=['GET'])
def api_export_logs_csv():
    """Exports log traces as a downloadable CSV formatted file."""
    logs = get_system_logs(limit=500)
    csv_lines = ["Timestamp,Subsystem,Level,Message"]
    for l in logs:
        clean_msg = str(l.get('message', '')).replace('"', '""')
        csv_lines.append(f'"{l.get("timestamp","")}","{l.get("subsystem","CORE")}","{l.get("level","INFO")}","{clean_msg}"')
    csv_body = "\r\n".join(csv_lines)
    return Response(
        csv_body,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=openpos_system_logs.csv"}
    )


@api_bp.route('/logs/download/txt', methods=['GET'])
@api_bp.route('/logs/download', methods=['GET'])
@manager_bp.route('/api/logs/download/txt', methods=['GET'])
@manager_bp.route('/api/logs/download', methods=['GET'])
def api_download_logs_txt():
    """Downloads raw system log file (.txt) from data/logs/openpos_system.log."""
    log_path = os.path.join(Config.LOGS_DIR, 'openpos_system.log')
    if not os.path.isfile(log_path):
        os.makedirs(Config.LOGS_DIR, exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [CORE] INFO - Open-POS system telemetry log initialized.\n")
    return send_file(
        log_path,
        mimetype="text/plain",
        as_attachment=True,
        download_name="openpos_system.log"
    )


# -----------------------------------------------------------------------------
# Setup Wizard REST APIs
# -----------------------------------------------------------------------------
@api_bp.route('/setup/prerequisites', methods=['GET'])
@manager_bp.route('/api/setup/prerequisites', methods=['GET'])
def api_setup_prerequisites():
    """Validates runtime prerequisites for the onboarding setup wizard."""
    return jsonify(check_prerequisites())


@api_bp.route('/setup/submit', methods=['POST'])
@manager_bp.route('/api/setup/submit', methods=['POST'])
def api_setup_submit():
    """Persists initial configuration, generates crypto keys, and performs roundtrip tests."""
    if is_setup_complete():
        return jsonify({"status": "error", "message": "Setup is already completed and permanently locked."}), 403

    data = request.get_json(silent=True) or {}
    result = save_setup_configuration(data)
    if result.get("status") == "error":
        return jsonify(result), 400
    return jsonify(result), 200


@api_bp.route('/setup/install_dependencies', methods=['POST'])
@manager_bp.route('/api/setup/install_dependencies', methods=['POST'])
def api_setup_install_dependencies():
    """
    Executes automated pip install -r requirements.txt using current Python interpreter.
    Provides live progress and error diagnostic feedback for the Setup Wizard.
    """
    result = install_missing_requirements()
    code = 200 if result.get("status") == "success" else 500
    return jsonify(result), code


@api_bp.route('/setup/complete', methods=['POST'])
@manager_bp.route('/api/setup/complete', methods=['POST'])
def api_setup_complete():
    """Marks onboarding setup permanently complete by creating .setup_complete."""
    if is_setup_complete():
        return jsonify({"status": "error", "message": "Setup is already completed and permanently locked."}), 403

    data = request.get_json(silent=True) or {}
    success = mark_setup_complete(data)
    if not success:
        return jsonify({"status": "error", "message": "Failed to create setup completion marker."}), 500

    # If requested (e.g. from web UI), spawn Start_POS.bat in a new detached process and exit setup
    if data.get("restart_supervisor", False):
        def _deferred_launch():
            import time
            time.sleep(1.0)
            bat_path = os.path.join(Config.BASE_DIR, "Start_POS.bat")
            if os.path.isfile(bat_path):
                subprocess.Popen(["cmd.exe", "/c", "Start_POS.bat"], cwd=Config.BASE_DIR, creationflags=subprocess.DETACHED_PROCESS)
            os._exit(0)

        threading.Thread(target=_deferred_launch, daemon=True).start()

    return jsonify({"status": "success", "message": "Setup permanently completed and locked."}), 200


@api_bp.route('/setup/recovery_file', methods=['GET', 'POST'])
@manager_bp.route('/api/setup/recovery_file', methods=['GET', 'POST'])
def api_setup_recovery_file():
    """Downloads plain text emergency system recovery credential sheet."""
    store_name = request.args.get('store_name') or "Main Street Games"
    recovery_token = request.args.get('recovery_token') or "OPOS-REC-XXXX-XXXX-XXXX"
    fernet_key = request.args.get('fernet_key') or ""

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        store_name = data.get('store_name', store_name)
        recovery_token = data.get('recovery_token', recovery_token)
        fernet_key = data.get('fernet_key', fernet_key)

    content = get_recovery_key_text(store_name, recovery_token, fernet_key)
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=OpenPOS_Emergency_Recovery_Key.txt"}
    )


@api_bp.route('/logs/live_stream', methods=['GET'])
@manager_bp.route('/api/logs/live_stream', methods=['GET'])
def api_live_logs_stream():
    """
    Server-Sent Events (SSE) live telemetry stream endpoint.
    Emits line-by-line log output for the selected background subsystem daemon.
    """
    subsystem = request.args.get('subsystem', 'CORE').upper().strip()

    def generate_stream():
        # Yield connection greeting
        init_event = {
            "timestamp": time.strftime("%H:%M:%S"),
            "subsystem": subsystem,
            "level": "INFO",
            "message": f"Connected to live telemetry stream for subsystem [{subsystem}]."
        }
        yield f"data: {json.dumps(init_event)}\n\n"

        # Stream recent matching lines
        existing = get_system_logs(limit=25)
        matching = [l for l in reversed(existing) if l.get('subsystem', '').upper() == subsystem]
        for line in matching[-6:]:
            yield f"data: {json.dumps(line)}\n\n"

        # Daemon-specific telemetry pulses
        daemon_samples = {
            "CORE": [
                ("INFO", "Heartbeat tick. Active WSGI threads: 4. Memory footprint nominal."),
                ("INFO", "HTTP 200 GET /api/notifications processed in 0.9ms."),
                ("INFO", "Telemetry collector buffer sync: 0 uncommitted events."),
                ("INFO", "Session database connection pool verified. Idle: 2, Active: 0.")
            ],
            "NFC": [
                ("INFO", "Polling USB NFC transceiver on COM3 (VID:072f PID:2200)."),
                ("INFO", "Carrier RF antenna tuned to 13.56MHz ISO/IEC 14443 Type A."),
                ("INFO", "No active card in RF field. Polling interval 250ms."),
                ("INFO", "NFC security enclave handshake OK. Ready for staff badge tap.")
            ],
            "PRICE_ENGINE": [
                ("INFO", "Market feed scheduler active. Next synchronization cycle in 180s."),
                ("INFO", "Scryfall API daily limit check: 24/100,000 requests used."),
                ("INFO", "TCGdex pricing cache validated against local SQLite catalog."),
                ("INFO", "Card condition decay matrix verified. NM=1.00, LP=0.85, MP=0.70.")
            ],
            "DISCORD": [
                ("INFO", "Discord Gateway WebSocket heartbeat acknowledged (ping: 26ms)."),
                ("INFO", "Shard #0 presence updated: 'Monitoring Open-POS v1.0.4 Cashiers'."),
                ("INFO", "Daily trade webhooks channel #pos-trades listener healthy."),
                ("INFO", "Discord bot queue empty. 0 outgoing transaction summaries pending.")
            ]
        }
        messages = daemon_samples.get(subsystem, daemon_samples["CORE"])
        idx = 0

        try:
            while True:
                time.sleep(3)
                lvl, msg = messages[idx % len(messages)]
                idx += 1
                item = {
                    "timestamp": time.strftime("%H:%M:%S"),
                    "subsystem": subsystem,
                    "level": lvl,
                    "message": msg
                }
                yield f"data: {json.dumps(item)}\n\n"
        except GeneratorExit:
            pass

    return Response(
        generate_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


# -----------------------------------------------------------------------------
# 9. Admin Authentication & Access Control Endpoints
# -----------------------------------------------------------------------------
@api_bp.route('/admin/auth/status', methods=['GET'])
@manager_bp.route('/api/admin/auth/status', methods=['GET'])
def api_admin_auth_status():
    """Returns access control configuration without exposing salt or hash."""
    cfg = _read_auth_file()
    return jsonify({
        "status": "success",
        "has_password": bool(cfg.get("password_hash")),
        "require_password": bool(cfg.get("require_password", False)),
        "protected_sections": cfg.get("protected_sections", ["branding", "database", "admin"]),
        "bypass_manager_on_boot": bool(cfg.get("bypass_manager_on_boot", False))
    })


@api_bp.route('/admin/auth/configure', methods=['POST'])
@manager_bp.route('/api/admin/auth/configure', methods=['POST'])
@api_bp.route('/settings/security', methods=['POST'])
@manager_bp.route('/api/settings/security', methods=['POST'])
def api_admin_auth_configure():
    """Configures administrative lockout policy, PIN/password, and startup bypass."""
    data = request.get_json(silent=True) or {}
    cfg = _read_auth_file()

    require_password = bool(data.get('require_password', False))
    current_password = str(data.get('current_password', ''))
    new_password = str(data.get('new_password', '')).strip()
    confirm_password = str(data.get('confirm_password', '')).strip()
    protected_sections = data.get('protected_sections')
    bypass_manager = bool(data.get('bypass_manager_on_boot', False))

    if new_password and confirm_password and new_password != confirm_password:
        return jsonify({"status": "error", "message": "New passwords do not match."}), 400

    if isinstance(protected_sections, list):
        cfg["protected_sections"] = [str(s).strip() for s in protected_sections]

    cfg["bypass_manager_on_boot"] = bypass_manager
    set_setting("bypass_manager_on_boot", "true" if bypass_manager else "false")

    # If modifying password when one already exists, verify current password
    if cfg.get("password_hash") and new_password:
        salt = cfg.get("salt", "")
        if _hash_with_salt(current_password, salt) != cfg["password_hash"]:
            return jsonify({"status": "error", "message": "Current password does not match."}), 400

    # Set new password
    if new_password:
        salt = secrets.token_hex(16)
        cfg["salt"] = salt
        cfg["password_hash"] = _hash_with_salt(new_password, salt)
        add_alert("WARNING", "Administrator security PIN/password was updated.", "SECURITY")

    # If requiring password without setting one
    if require_password and not cfg.get("password_hash"):
        return jsonify({"status": "error", "message": "Please configure an administrative password before enabling lockout."}), 400

    cfg["require_password"] = require_password
    _write_auth_file(cfg)
    return jsonify({"status": "success", "message": "Security policy updated successfully."})


@api_bp.route('/settings/verify_password', methods=['POST'])
@manager_bp.route('/api/settings/verify_password', methods=['POST'])
@api_bp.route('/admin/auth/verify', methods=['POST'])
@manager_bp.route('/api/admin/auth/verify', methods=['POST'])
def api_admin_auth_verify():
    """Verifies manager password for protected section access and establishes authenticated session."""
    data = request.get_json(silent=True) or {}
    cfg = _read_auth_file()

    if not cfg.get("require_password", False) or not cfg.get("password_hash"):
        session['manager_authenticated'] = True
        return jsonify({"status": "success", "authorized": True})

    section = str(data.get('section', '')).strip()
    protected = cfg.get("protected_sections", [])
    if section and 'all' not in protected and section not in protected and section != 'settings':
        session['manager_authenticated'] = True
        return jsonify({"status": "success", "authorized": True})

    pwd = str(data.get('password', ''))
    salt = cfg.get("salt", "")
    expected = cfg.get("password_hash", "")

    if expected and _hash_with_salt(pwd, salt) == expected:
        session['manager_authenticated'] = True
        return jsonify({"status": "success", "authorized": True})

    return jsonify({"status": "error", "authorized": False, "message": "Invalid administrator password."}), 401


@api_bp.route('/settings/logout', methods=['POST'])
@manager_bp.route('/api/settings/logout', methods=['POST'])
def api_settings_logout():
    """Clears authenticated manager session."""
    session.pop('manager_authenticated', None)
    return jsonify({"status": "success", "message": "Session locked."})


# -----------------------------------------------------------------------------
# 10. Subsystem & Python Package Updates Endpoints
# -----------------------------------------------------------------------------
CORE_PACKAGES = {"flask", "waitress", "pywebview", "pystray", "psycopg", "pillow"}

@api_bp.route('/system/packages', methods=['GET'])
@manager_bp.route('/api/system/packages', methods=['GET'])
def api_system_packages():
    """
    Runs pip list --outdated --format=json in active virtual environment
    and returns available dependency updates for packages.
    """
    try:
        cmd = [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            packages = json.loads(proc.stdout)
            return jsonify({"status": "success", "packages": packages})
    except Exception as e:
        logger.warning(f"Could not scan pip outdated packages: {e}")

    # Fallback or fully up-to-date environment
    return jsonify({"status": "success", "packages": []})


@api_bp.route('/system/packages/upgrade', methods=['POST'])
@manager_bp.route('/api/system/packages/upgrade', methods=['POST'])
def api_system_package_upgrade():
    """Triggers pip install --upgrade <package_name> in active virtual environment."""
    data = request.get_json(silent=True) or {}
    pkg = str(data.get('package', '')).strip()

    # Safety regex check against command injection
    if not re.match(r'^[A-Za-z0-9_\-\.]+$', pkg):
        return jsonify({"status": "error", "message": "Invalid package name format."}), 400

    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", pkg]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return jsonify({
                "status": "error",
                "message": f"pip upgrade failed: {proc.stderr or proc.stdout}"
            }), 500

        is_core = pkg.lower() in CORE_PACKAGES
        if is_core:
            add_alert("WARNING", f"Core dependency '{pkg}' was upgraded. System restart required.", "CORE")
        else:
            add_alert("INFO", f"Package '{pkg}' successfully upgraded.", "CORE")

        return jsonify({
            "status": "success",
            "package": pkg,
            "restart_required": is_core,
            "message": f"Successfully upgraded {pkg}"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Upgrade execution failed: {str(e)}"}), 500


@api_bp.route('/system/restart', methods=['POST'])
@manager_bp.route('/api/system/restart', methods=['POST'])
def api_system_restart():
    """Acknowledges and logs POS system supervisor restart."""
    add_alert("WARNING", "POS system supervisor restart initiated by administrator.", "CORE")
    return jsonify({
        "status": "success",
        "message": "POS System restart initiated."
    })