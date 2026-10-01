"""
Unit and Integration Tests for Official Addon Specification, Contract Validation,
and Standardized Route Mounting.
"""

import os
import json
import tempfile
import pytest
from flask import Flask, Blueprint, jsonify

from core.addons.validator import validate_addon_manifest
from core.addons.loader import (
    load_single_addon,
    get_core_context,
    discover_addons,
    ACTIVE_ADDONS
)
from core.addons.ui_hooks import get_registered_workspaces, get_registered_slot_actions
from app import create_app


def test_validator_missing_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        valid, msg = validate_addon_manifest(tmp)
        assert not valid
        assert "Missing manifest.json" in msg


def test_validator_invalid_json():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            f.write("{invalid_json: true")
        valid, msg = validate_addon_manifest(tmp)
        assert not valid
        assert "Invalid JSON" in msg


def test_validator_missing_required_fields():
    with tempfile.TemporaryDirectory() as tmp:
        folder_name = os.path.basename(tmp)
        # Missing entrypoint
        manifest = {"id": folder_name, "name": "Test", "version": "1.0.0"}
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        valid, msg = validate_addon_manifest(tmp)
        assert not valid
        assert "Missing required manifest field: 'entrypoint'" in msg


def test_validator_id_format_and_folder_match():
    with tempfile.TemporaryDirectory() as tmp:
        folder_name = os.path.basename(tmp)
        # Mismatched ID
        manifest = {
            "id": "different_id",
            "name": "Test",
            "version": "1.0.0",
            "entrypoint": "plugin:setup_addon"
        }
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        valid, msg = validate_addon_manifest(tmp)
        assert not valid
        assert "does not match directory name" in msg

    with tempfile.TemporaryDirectory() as tmp:
        # Invalid characters in ID (e.g. hyphens or capital letters)
        bad_dir = os.path.join(tmp, "Bad-Addon-ID")
        os.makedirs(bad_dir, exist_ok=True)
        manifest = {
            "id": "Bad-Addon-ID",
            "name": "Test",
            "version": "1.0.0",
            "entrypoint": "plugin:setup_addon"
        }
        with open(os.path.join(bad_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        valid, msg = validate_addon_manifest(bad_dir)
        assert not valid
        assert "Invalid addon ID" in msg


def test_validator_dependency_rules():
    with tempfile.TemporaryDirectory() as tmp:
        folder_name = os.path.basename(tmp)
        # Non-list dependencies
        manifest = {
            "id": folder_name,
            "name": "Test",
            "version": "1.0.0",
            "entrypoint": "plugin:setup_addon",
            "dependencies": "requests>=2.0.0"
        }
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        valid, msg = validate_addon_manifest(tmp)
        assert not valid
        assert "'dependencies' field must be a list" in msg

        # Declaring python in dependencies
        manifest["dependencies"] = ["requests>=2.0.0", "python>=3.11"]
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        valid, msg = validate_addon_manifest(tmp)
        assert not valid
        assert "min_core_version" in msg


def test_validator_ui_extensions_rules():
    with tempfile.TemporaryDirectory() as tmp:
        folder_name = os.path.basename(tmp)
        # provides_canvas without canvas_template
        manifest = {
            "id": folder_name,
            "name": "Test",
            "version": "1.0.0",
            "entrypoint": "plugin:setup_addon",
            "ui_extensions": {
                "provides_canvas": True
            }
        }
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        valid, msg = validate_addon_manifest(tmp)
        assert not valid
        assert "must specify 'canvas_template'" in msg


def test_core_context_keys():
    context = get_core_context()
    assert "cart" in context
    assert "customers" in context
    assert "events" in context
    assert "config" in context
    assert "version" in context


def test_namespaced_loader_and_route_mounting():
    with tempfile.TemporaryDirectory() as tmp:
        addon_id = os.path.basename(tmp)
        manifest = {
            "id": addon_id,
            "name": "Sample Retail Addon",
            "version": "1.0.0",
            "author": "OpenPOS Contributor",
            "entrypoint": "plugin:setup_addon",
            "dependencies": ["requests>=2.31.0"],
            "ui_extensions": {
                "provides_canvas": True,
                "canvas_label": "Custom Desk",
                "canvas_icon": "bi-terminal",
                "canvas_template": f"{addon_id}/canvas.html",
                "standalone_routes": [
                    {
                        "path": "/desk",
                        "label": "Full Screen Desk",
                        "template": f"{addon_id}/desk.html"
                    }
                ],
                "slots": [
                    {
                        "slot": "pos:header_actions",
                        "label": "Custom Action",
                        "action": "navigate",
                        "target": f"/addon/{addon_id}/desk"
                    }
                ]
            }
        }
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        plugin_code = f"""
from flask import Blueprint, jsonify

def setup_addon(app, core_context):
    assert core_context['cart'] is not None
    assert core_context['customers'] is not None
    addon_bp = Blueprint('{addon_id}', __name__, url_prefix='/addon/{addon_id}')

    @addon_bp.route('/desk')
    def desk():
        return jsonify({{'status': 'ok', 'addon': '{addon_id}'}})

    app.register_blueprint(addon_bp)
"""
        with open(os.path.join(tmp, "plugin.py"), "w", encoding="utf-8") as f:
            f.write(plugin_code)

        app = Flask(f"test_app_{addon_id}")
        loaded = load_single_addon(tmp, app)
        assert loaded
        assert ACTIVE_ADDONS[addon_id]["status"] == "active"


        # Check workspace discovery
        workspaces = get_registered_workspaces()
        ws = next((w for w in workspaces if w["id"] == addon_id), None)
        assert ws is not None
        assert ws["label"] == "Custom Desk"
        assert ws["icon"] == "bi-terminal"
        assert ws["standalone_url"] == f"/addon/{addon_id}/desk"
        assert ws["template_path"] == f"{addon_id}/canvas.html"

        # Check slot action discovery
        slot_actions = get_registered_slot_actions("pos:header_actions")
        action = next((a for a in slot_actions if a["addon_id"] == addon_id), None)
        assert action is not None
        assert action["target"] == f"/addon/{addon_id}/desk"

        # Test route access
        client = app.test_client()
        res = client.get(f"/addon/{addon_id}/desk")
        assert res.status_code == 200
        assert res.get_json()["status"] == "ok"


def test_pos_register_ui_workspace_integration():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        res = client.get("/pos")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "pos-workspace-tabs" in html
        assert "workspace-toggle" in html
        assert 'data-pane="retail-pane"' in html
        assert 'id="retail-pane"' in html
        assert "pos-workspace-canvas" in html
