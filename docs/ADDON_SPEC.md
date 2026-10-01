# OpenPOS Addon Developer Specification (v1.0)

This document establishes the official architectural contract, directory conventions, URL namespace standards, and integration hooks for building addons on OpenPOS.

---

## 1. Directory Structure

All custom addons reside within `data/custom_addons/<addon_id>/`. The `<addon_id>` must be lowercase alphanumeric with underscores only (matching regex `^[a-z0-9_]+$`).

```text
data/custom_addons/<addon_id>/
├── manifest.json              # Required: Metadata, dependencies, and UI hooks
├── plugin.py                  # Required: Addon lifecycle entrypoint
├── config_schema.json         # Optional: Settings schema for System Manager
├── requirements.txt           # Optional: Third-party Python dependencies
├── routes/                    # Blueprint route handlers
│   ├── __init__.py
│   └── views.py
├── static/                    # Addon-specific static assets
│   ├── css/
│   └── js/
├── templates/                 # Scoped Jinja2 templates
│   └── <addon_id>/
│       └── canvas.html
└── migrations/                # Optional: Database migrations
    ├── schema_sqlite.sql
    └── schema_postgres.sql
```

---

## 2. Manifest Schema (`manifest.json`)
The `manifest.json` file is validated by `core/addons/validator.py` at runtime.

```json
{
  "id": "sample_addon",
  "name": "Sample Retail Addon",
  "version": "1.0.0",
  "author": "OpenPOS Contributor",
  "description": "Demonstration extension for custom workflows.",
  "min_core_version": "1.0.9",
  "entrypoint": "plugin:setup_addon",
  "requires_db": false,
  "dependencies": [
    "requests>=2.31.0"
  ],
  "ui_extensions": {
    "provides_canvas": true,
    "canvas_label": "Custom Desk",
    "canvas_icon": "bi-terminal",
    "canvas_template": "sample_addon/canvas.html",
    "standalone_routes": [
      {
        "path": "/desk",
        "label": "Full Screen Desk",
        "template": "sample_addon/desk.html"
      }
    ],
    "slots": [
      {
        "slot": "pos:header_actions",
        "label": "Custom Action",
        "action": "navigate",
        "target": "/addon/sample_addon/desk"
      }
    ]
  }
}
```

### Manifest Rules
- **id**: Must match the directory name in `data/custom_addons/` exactly.
- **entrypoint**: Formatted as `<module_filename>:<callable_function>`. Default is `plugin:setup_addon`.
- **dependencies**: Pip requirement strings only. Do not include Python standard library modules or the string "python".
- **ui_extensions.canvas_template**: Must be namespaced under the addon's template directory (`<addon_id>/<file>.html`).

---

## 3. Packaging & Import Rules
- **Namespace Isolation**: The core loader does not add individual addon folders to global `sys.path`.
- **Relative Imports**: Addon internal modules must use explicit relative imports:

```python
from .routes import views_bp
from .services.engine import DataProcessor
```

- **Requirements Handling**: Third-party packages declared in `requirements.txt` are installed automatically via an isolated pip sub-process upon addon extraction.

---

## 4. Blueprint & URL Standards
All web routes registered by an addon are mounted under the fixed prefix:

```plaintext
/addon/<addon_id>/
```

### Entrypoint Example (`plugin.py`)
```python
from flask import Blueprint
from .routes.views import views_bp

def setup_addon(app, core_context):
    """
    Entrypoint executed by OpenPOS Core Loader.
    :param app: The Flask application instance.
    :param core_context: Injected dictionary containing:
        - 'cart': CartService
        - 'customers': CustomerService
        - 'events': event_bus
        - 'config': System Config
    """
    addon_bp = Blueprint(
        "sample_addon",
        __name__,
        url_prefix="/addon/sample_addon",
        template_folder="templates",
        static_folder="static",
        static_url_path="/addon/sample_addon/static"
    )

    addon_bp.register_blueprint(views_bp, url_prefix="/views")
    app.register_blueprint(addon_bp)
```

Target URLs resolve as:
- Internal Route: `/addon/sample_addon/views/dashboard`
- Static Resource: `/addon/sample_addon/static/js/main.js`

---

## 5. Core Services API
Addons communicate with the register session, ledger, and customer data using core services provided in `core_context`:

### A. Cart Session
- `POST /api/pos/cart/item`: Adds an item to the active register ticket.
```json
{
  "sku": "CUSTOM-SKU-001",
  "name": "Custom Product",
  "price": 19.99,
  "quantity": 1,
  "taxable": true,
  "metadata": {
    "addon_id": "sample_addon",
    "custom_field": "sample_data"
  }
}
```
- `GET /api/pos/cart`: Retrieves active ticket items and totals.

### B. Customers & Ledger
- `POST /api/core/customers/resolve`: Resolves customer by phone, name, or NFC UID.
- `POST /api/core/customers/<id>/credit/deposit`: Appends a transaction to the double-entry store credit ledger.

### C. Event Bus (`core.events.event_bus`)
```python
event_bus.subscribe("pos:transaction_completed", handler_func)
event_bus.subscribe("customer:badge_assigned", handler_func)
event_bus.dispatch("addon:event_name", **payload)
```
