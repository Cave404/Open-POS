# OpenPOS Addon & Extension Specification
**Target Core API Version:** `1.0.0`  
**Minimum OpenPOS Platform Version:** `v1.0.8`

---

## 1. Directory Structure Contract
Every OpenPOS addon must be packaged as a standalone folder containing a root `manifest.json`:

```text
<addon_id>/
├── manifest.json              # Contract metadata, routes, and dependencies
├── plugin.py                  # Entrypoint exposing `addon_bp` Blueprint
├── settings.py                # (Optional) Addon configuration persistence
├── migrations/
│   ├── schema_sqlite.sql      # Executed automatically on install if running SQLite
│   └── schema_postgres.sql    # Executed automatically on install if running PostgreSQL
├── static/
│   ├── css/                   # Addon styling (must use core CSS variables)
│   └── js/                    # Client-side scripts
└── templates/
    └── <addon_id>/            # Sandboxed Jinja2 templates
```

---

## 2. Manifest Schema (`manifest.json`)
The `manifest.json` file is strictly required. The core loader inspects this before executing any code:

```json
{
  "id": "addon_unique_id",
  "name": "Human-Readable Name",
  "version": "1.0.0",
  "author": "Author or Community Name",
  "description": "Short summary of the addon functionality.",
  "category": "Desktop_Apps",
  "icon": "icon_name.png",
  "entrypoint": "plugin.py",
  "requires_db": true,
  "min_core_version": "1.0.8",
  "dependencies": ["requests"],
  "settings_route": "/addons/<addon_id>/settings",
  "nav_items": [
    {
      "label": "Display Label",
      "route": "/addons/<addon_id>/main",
      "icon": "🧩"
    }
  ]
}
```

- `id`: Unique lowercase alphanumeric identifier (`snake_case`, e.g., `tcg_pos`).
- `requires_db`: If true, the installer will automatically run the appropriate migration in `migrations/` before enabling the blueprint.
- `entrypoint`: Python file containing the Flask blueprint (default: `plugin.py`).
- `min_core_version`: The minimum OpenPOS version required to mount this addon.

---

## 3. Blueprint Contract (`plugin.py`)
Addons must expose an instance of `flask.Blueprint` named `addon_bp`:

```python
from flask import Blueprint, render_template

addon_bp = Blueprint(
    '<addon_id>',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/addons/<addon_id>/static'
)

# Routes are mounted automatically at: /addons/<addon_id>/...
@addon_bp.route('/')
def index():
    return render_template('<addon_id>/index.html')
```

---

## 4. Isolated Data Storage Rules
Addons must never write runtime data, image caches, or dynamic settings inside their own code directory or the git tree. All mutable files must be stored within the core's isolated `data/` structure:

- **Databases:** Interacted with via the core connection pool, or stored in `data/db/` if using SQLite.
- **Asset & Image Caching:** `data/cache/<addon_id>/`
- **Custom Configuration & Secrets:** `data/config/<addon_id>.json`
- **Logs:** `data/logs/<addon_id>.log`

---

## 5. UI Design & Styling Standard
To maintain visual consistency across all windows:

- **Top Header:** All addon views must include the standard return header:

```html
<header class="subview-header">
    <div class="header-left">
        <a href="/manager" class="btn-back">
            <span class="btn-icon">←</span>
            <span>Return to Dashboard</span>
        </a>
        <div class="header-divider"></div>
        <h2 class="subview-title">{{ addon_title }}</h2>
    </div>
</header>
```

- **Theme Variables:** Use the core CSS variables declared in `/static/css/manager.css`:
  - `--bg-primary` (Main dark background)
  - `--bg-secondary` (Card/Sidebar background)
  - `--border-color` (Subtle 1px outlines)
  - `--accent-blue` (Primary buttons & active states)
  - `--text-main` (Headings and primary text)
  - `--text-muted` (Helper text and secondary descriptions)

---

## 6. Failure Isolation & Error Safety
- If an addon crashes during registration or has missing dependencies, the core will mark the addon as `STATE_ERROR` in the Manager UI.
- Addons must never execute blocking operations (like heavy network calls) on the main thread during module import.
