"""
=============================================================================
Open-POS Core Addon UI Extension Hooks System
=============================================================================
Manages UI hook registration and dynamic rendering for addon components:
  1. Dynamic Action Canvas swapping (e.g. TCG Intake / Singles replacement).
  2. Workspace Mode Switcher toggle buttons.
  3. Pluggable slots (pos:header_actions, pos:cart_actions, etc.).
  4. Safe, fault-contained template rendering preventing addon crashes.
=============================================================================
"""

import os
import logging
from typing import List, Dict, Any, Optional
from flask import current_app, render_template, render_template_string
from markupsafe import Markup

logger = logging.getLogger(__name__)


def _get_addon_manager():
    """Lazily resolves addon_manager from core.addons."""
    try:
        from core.addons import addon_manager
        return addon_manager
    except ImportError:
        return None


def get_active_ui_extensions() -> List[Dict[str, Any]]:
    """
    Scans all currently active addons and extracts their ui_extensions manifest declarations.
    Returns a list of dicts with addon_id, dir_path, manifest, and ui_extensions.
    """
    manager = _get_addon_manager()
    if not manager:
        return []

    active_exts = []
    items = manager.addons.values() if hasattr(manager, 'addons') and manager.addons else manager.get_all_addons()
    for item in items:
        if isinstance(item, dict):
            status = item.get('status')
            addon_id = item.get('id')
            manifest = item.get('manifest') or {}
            name = item.get('name', addon_id)
            dir_path = item.get('dir_path', '')
        else:
            status = getattr(item, 'status', None)
            addon_id = getattr(item, 'id', None)
            manifest = getattr(item, 'manifest', {}) or {}
            name = getattr(item, 'name', addon_id)
            dir_path = getattr(item, 'dir_path', '')

        # Check active status (AddonRecord uses 'ACTIVE')
        if str(status).upper() != "ACTIVE":
            continue

        ui_ext = manifest.get("ui_extensions")
        if ui_ext and isinstance(ui_ext, dict):
            active_exts.append({
                "addon_id": addon_id,
                "name": name,
                "dir_path": dir_path,
                "manifest": manifest,
                "ui_extensions": ui_ext
            })

    return active_exts


def get_registered_workspaces() -> List[Dict[str, Any]]:
    """
    Inspects active addon manifests to discover registered canvas workspaces.
    Returns list of workspace objects:
      - 'id': addon ID (e.g. 'tcg_pos')
      - 'label': workspace tab label (e.g. '🃏 TCG Singles & Intake')
      - 'icon_html': icon html or emoji string (e.g. '🃏')
      - 'template_path': template relative path to include (e.g. 'tcg_pos/canvas.html')
    """
    workspaces = []
    for ext in get_active_ui_extensions():
        addon_id = ext["addon_id"]
        manifest = ext.get("manifest", {})
        ui_ext = ext.get("ui_extensions", {})

        provides_canvas = (
            ui_ext.get("provides_canvas") is True or
            ui_ext.get("mode") == "canvas_replace" or
            bool(ui_ext.get("canvas_template")) or
            bool(ui_ext.get("canvas_label"))
        )
        if not provides_canvas:
            continue

        raw_label = ui_ext.get("canvas_label") or manifest.get("name") or ext.get("name", addon_id)
        icon_html = ui_ext.get("icon_html")
        if not icon_html:
            first_char = raw_label.strip()[:1] if raw_label else ""
            if first_char and ord(first_char) > 127:
                icon_html = ""
            else:
                icon_html = "🧩"

        tmpl = ui_ext.get("canvas_template", "canvas.html")
        if tmpl.startswith(f"{addon_id}/") or tmpl.startswith(f"{addon_id}\\"):
            template_path = tmpl.replace('\\', '/')
        else:
            template_path = f"{addon_id}/{tmpl}".replace('\\', '/')

        workspaces.append({
            "id": addon_id,
            "label": raw_label,
            "icon_html": icon_html,
            "template_path": template_path
        })
    return workspaces


def has_addon_canvas() -> bool:
    """
    Returns True if at least one active addon declares a custom register canvas extension.
    Used by register.html to conditionally render the Workspace Mode Switcher.
    """
    for ext in get_active_ui_extensions():
        ui_ext = ext["ui_extensions"]
        if ui_ext.get("provides_canvas") or ui_ext.get("mode") == "canvas_replace" or ui_ext.get("canvas_template") or ui_ext.get("canvas_label"):
            return True
    return False


def get_addon_canvases() -> List[Dict[str, Any]]:
    """
    Returns list of active custom canvases registered by addons.
    """
    canvases = []
    for ext in get_active_ui_extensions():
        ui_ext = ext["ui_extensions"]
        if ui_ext.get("provides_canvas") or ui_ext.get("mode") == "canvas_replace" or ui_ext.get("canvas_template") or ui_ext.get("canvas_label"):
            canvases.append({
                "addon_id": ext["addon_id"],
                "name": ext["name"],
                "canvas_label": ui_ext.get("canvas_label", ext["name"]),
                "canvas_template": ui_ext.get("canvas_template", ""),
                "standalone_route": ui_ext.get("standalone_route", ""),
                "dir_path": ext["dir_path"],
                "ui_extensions": ui_ext
            })
    return canvases


def _render_template_fragment(template_path: str, addon_dir: str, context: dict) -> str:
    """
    Attempts to render template_path using Flask's render_template.
    Falls back to loading directly from addon_dir/templates/template_path if needed.
    """
    # 1. Try standard Flask template loader
    try:
        return render_template(template_path, **context)
    except Exception as e1:
        logger.debug(f"Standard template render for '{template_path}' not found: {e1}")

    # 2. Try loading from addon's templates directory directly
    if addon_dir:
        candidate_paths = [
            os.path.join(addon_dir, 'templates', template_path),
            os.path.join(addon_dir, template_path)
        ]
        for path in candidate_paths:
            if os.path.isfile(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        template_source = f.read()
                    return render_template_string(template_source, **context)
                except Exception as e2:
                    logger.error(f"Error rendering addon template file '{path}': {e2}", exc_info=True)
                    return f"<!-- Template Error ({os.path.basename(path)}): {e2} -->"

    return f"<!-- Template Not Found: {template_path} -->"


def render_addon_hook(slot_name: str, **context) -> Markup:
    """
    Universal Jinja2 helper for rendering addon UI extensions into designated slots.

    Supported Special Slots:
      - 'pos:workspace_toggles': Renders button toggles for each custom canvas.
      - 'pos:canvas_mount': Renders each custom canvas pane container.
      - 'pos:header_actions': Renders header action widgets from ui_extensions.slots.
      - 'pos:cart_actions': Renders cart action widgets from ui_extensions.slots.
      - Any custom slot: Scans ui_extensions.slots for matching slot names.
    """
    rendered_fragments: List[str] = []

    try:
        # Special Case 1: Workspace Mode Switcher Toggles
        if slot_name == "pos:workspace_toggles":
            canvases = get_addon_canvases()
            for c in canvases:
                addon_id = c["addon_id"]
                label = c["canvas_label"]
                html = (
                    f'<button type="button" class="btn btn-sm btn-outline-primary" '
                    f'data-canvas="addon-{addon_id}" title="Switch to {label}">'
                    f'{label}'
                    f'</button>'
                )
                rendered_fragments.append(html)
            return Markup("\n".join(rendered_fragments))

        # Special Case 2: Addon Canvas Mount
        if slot_name == "pos:canvas_mount":
            canvases = get_addon_canvases()
            for c in canvases:
                addon_id = c["addon_id"]
                template_path = c["canvas_template"]
                inner_content = ""
                if template_path:
                    inner_content = _render_template_fragment(template_path, c["dir_path"], context)
                else:
                    inner_content = (
                        f'<div class="alert alert-info">'
                        f'Custom canvas for <strong>{c["name"]}</strong> is active.'
                        f'</div>'
                    )

                pane_html = (
                    f'<div class="addon-canvas-pane" id="canvas-addon-{addon_id}" style="display: none;">\n'
                    f'{inner_content}\n'
                    f'</div>'
                )
                rendered_fragments.append(pane_html)
            return Markup("\n".join(rendered_fragments))

        # General Slot Rendering (pos:header_actions, pos:cart_actions, etc.)
        for ext in get_active_ui_extensions():
            ui_ext = ext["ui_extensions"]
            slots = ui_ext.get("slots", [])
            if not isinstance(slots, list):
                continue

            for s in slots:
                if not isinstance(s, dict):
                    continue
                if s.get("slot") == slot_name:
                    tmpl = s.get("template")
                    html_content = s.get("html")
                    if tmpl:
                        frag = _render_template_fragment(tmpl, ext["dir_path"], context)
                        rendered_fragments.append(frag)
                    elif html_content:
                        rendered_fragments.append(str(html_content))

    except Exception as err:
        logger.error(f"Error executing UI hook '{slot_name}': {err}", exc_info=True)
        return Markup(f"<!-- Error executing UI hook '{slot_name}': {err} -->")

    return Markup("\n".join(rendered_fragments))
