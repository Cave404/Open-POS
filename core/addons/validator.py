import os
import re
import json
from typing import Tuple

REQUIRED_FIELDS = ["id", "name", "version", "entrypoint"]
ID_REGEX = re.compile(r"^[a-z0-9_]+$")

def validate_addon_manifest(addon_dir: str) -> Tuple[bool, str]:
    manifest_path = os.path.join(addon_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        return False, "Missing manifest.json file"

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as err:
        return False, f"Invalid JSON syntax: {err}"
    except Exception as err:
        return False, f"Failed to read manifest: {err}"

    for field in REQUIRED_FIELDS:
        if field not in data or not str(data[field]).strip():
            return False, f"Missing required manifest field: '{field}'"

    addon_id = data["id"].strip()
    if not ID_REGEX.match(addon_id):
        return False, f"Invalid addon ID '{addon_id}'. Must be lowercase alphanumeric with underscores."

    dir_name = os.path.basename(os.path.normpath(addon_dir))
    if addon_id != dir_name:
        return False, f"Addon ID '{addon_id}' does not match directory name '{dir_name}'."

    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list):
        return False, "'dependencies' field must be a list."

    for dep in dependencies:
        dep_clean = re.split(r"[<>=!~ ]", dep.strip())[0].strip().lower()
        if dep_clean == "python":
            return False, "Declare Python version requirements in 'min_core_version', not 'dependencies'."

    ui_ext = data.get("ui_extensions")
    if ui_ext:
        if not isinstance(ui_ext, dict):
            return False, "'ui_extensions' must be an object."
        if ui_ext.get("provides_canvas") and not ui_ext.get("canvas_template"):
            return False, "Addons providing a canvas must specify 'canvas_template'."

    return True, "Manifest validated successfully"
