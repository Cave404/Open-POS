# Open-POS Developer Wiki & Technical Reference (v1.0.8)

Welcome to the **Open-POS** internal developer documentation. This living guide defines the runtime architecture, threading model, file layout, applet lifecycle, branding pipeline, security controls, and testing standards for the project.

---

## 1. System Architecture & Threading Model

Open-POS is a hybrid desktop application combining a native Microsoft Windows WebView2 desktop container, a local Flask/Waitress WSGI microservice, and a persistent system tray supervisor.

```
┌──────────────────────────────────────────────────────────┐
│                   Operating System (Win32)               │
└────────────────────────────┬─────────────────────────────┘
                             │
            ┌────────────────┴────────────────┐
            │       Main OS Process Thread    │
            │   (run.py -> webview.start())   │
            │       HWnd Window Message Pump   │
            └───────┬──────────────────┬──────┘
                    │                  │
                    ▼                  ▼
      ┌─────────────────────────┐  ┌─────────────────────────┐
      │  Background Daemon #1   │  │  Background Daemon #2   │
      │  Flask / WSGI Backend   │  │  Pystray System Tray    │
      │  (127.0.0.1:5000)       │  │  (tray.run_detached())  │
      └─────────────┬───────────┘  └─────────────┬───────────┘
                    │                            │
                    ▼                            ▼
            REST APIs & Views            Tray Icon / Menu
         (/manager, /api/settings)     (Minimize to Tray / Exit)
```

### Threading Rules & Collision Prevention

1. **Main Thread Isolation:**
   - On Windows, `pywebview.start()` **MUST** execute on the primary operating system thread.
   - Calling `webview.start()` from a spawned Python worker thread causes message pump collisions, deadlocks, and `WebViewException: Thread collision`.
2. **Background Backend Worker:**
   - Flask runs on an independent daemon thread (`OpenPOS-BackendWorker`).
   - `use_reloader=False` prevents duplicate sub-processes from attempting to bind to port 5000.
3. **Detached System Tray Loop:**
   - `pystray.Icon.run_detached()` executes the tray message pump in a non-blocking background thread.
4. **Window Close Interception:**
   - The window `closing` event is registered with a custom callback (`active_window.events.closing += on_window_closing`).
   - Clicking the window close button (`X`) calls `window.hide()` and returns `False`, suppressing window destruction and keeping the background server alive in the Windows system tray.
   - Selecting **Exit Open-POS** sets `is_terminating = True`, closes the tray, destroys the window, and invokes `os._exit(0)`.

---

## 2. File & Directory Map

```
Open-POS/
├── Start_POS.bat              # One-click Windows terminal-free launcher (environment checker & runner)
├── Open_POS.vbs               # Silent one-click shortcut executing Start_POS.bat without terminal flash
├── run.py                     # Consolidated desktop runner & supervisor entry point
├── app.py                     # Flask application factory (create_app), DB init & blueprint mounting
├── requirements.txt           # Python package dependencies and version specifications
├── pytest.ini                 # Pytest configuration specifying pythonpath = .
│
├── data/                      # Isolated private store data (untracked by git)
│   ├── db/                    # Local databases (pos_store.db, shop_inventory.db)
│   ├── cache/                 # Card art and asset caches
│   ├── uploads/               # Store logos and custom media assets
│   ├── logs/                  # Activity and runtime diagnostic logs (open_pos.log)
│   ├── config/                # Isolated configuration & encrypted security policies (manager_auth.json)
│   └── custom_addons/         # Store-specific custom extensions
│
├── core/
│   ├── config.py              # Configuration dataclass (ports, data paths, DB credentials, defaults)
│   ├── db.py                  # Database connection manager (SQLite/PostgreSQL) & query abstraction
│   ├── settings.py            # Dynamic settings engine (get_setting, set_setting, seeding, JSON parsing)
│   ├── notifications.py       # Rolling thread-safe notification queue and log trace writer
│   └── boot.py                # Multi-phase startup boot sequencer & progress dispatcher
│
├── manager/
│   ├── routes.py              # System Manager controller: applet discovery, fallback guards, and APIs
│   ├── open_pos_splash.png    # High-resolution frameless startup splash screen graphic
│   └── templates/
│       ├── manager.html       # Primary HTML5 full-window System Manager dashboard & sidebar
│       ├── splash.html        # Frameless startup splash window with animated progress bar
│       ├── branding.html      # Store Branding & Business Rules configuration panel
│       ├── logs.html          # Terminal Logs, filtering, CSV export, and SSE live daemon terminal
│       ├── configure_manager.html # Access control, salted PIN lockout, bypass modes, and package manager
│       ├── placeholder.html   # Universal Safe Navigation Guard for applets under construction
│       └── about.html         # System credits, contributor ledger, and dependency audit table
│
├── static/
│   ├── css/
│   │   ├── manager.css        # Unified dark dashboard styling, card grid, forms, and toast notifications
│   │   └── cde_theme.css      # Retro CDE desktop styling tokens
│   └── js/
│       └── notifications.js   # Client-side 5s polling tray, badge counter, and dropdown controller
│
├── docs/
│   └── WIKI.md                # Developer wiki and architectural documentation (this document)
│
└── tests/
    ├── test_settings.py       # Automated pytest test suite covering settings, routes, and APIs
    └── test_boot.py           # Automated tests for boot sequencer and splash view routes
```

---

## 3. Applet Lifecycle & Safe Navigation Guard

All applets accessible from the System Manager dashboard are discovered through `manager/routes.py` via `BUILTIN_APPLETS` and dynamic manifest scanning in the `/addons` folder.

### Safe Navigation Guarantee

> [!IMPORTANT]
> **No route or applet in Open-POS may ever lead to a 404 dead end.**

Every applet registered in `BUILTIN_APPLETS` must resolve to:
1. A **dedicated business logic page** (e.g., `/manager/branding`, `/manager/logs`, `/manager/configure_manager`, `/manager/about`), OR
2. The **universal fallback view** (`/manager/placeholder/<applet_id>` -> `placeholder.html`).

---

## 4. Unified Navigation Header Standard (`.subview-header`)

To prevent layout shifting and guarantee tactile navigation across every subview:
- The top header must strictly employ `.subview-header`:
  ```html
  <header class="subview-header">
      <div class="header-left">
          <a href="/manager" class="btn-back">
              <span class="btn-icon">←</span>
              <span>Return to Dashboard</span>
          </a>
          <div class="header-divider"></div>
          <h2 class="subview-title">{{ page_title }}</h2>
      </div>
      <div class="header-right">
          <div class="notification-wrapper">
              <button id="notifBellBtn" class="btn-icon-tray" title="System Notifications">
                  🔔 <span id="notifBadge" class="badge-count" style="display: none;">0</span>
              </button>
              <div id="notifDropdown" class="notif-dropdown-menu" style="display: none;">
                  ...
              </div>
          </div>
          <span class="status-pill status-online">Engine: Online</span>
          <a href="/manager/about" class="version-badge-link">v1.0.8</a>
      </div>
  </header>
  ```
- Subviews embed `static/js/notifications.js` to initialize background polling and interactive badge updates.

---

## 5. Persistent Notification Service

- **Core Module:** `core/notifications.py` provides a thread-safe rolling in-memory queue (`maxlen=100`) backed by a persistent log trace on disk at `data/logs/openpos_system.log`.
- **API Endpoints:**
  - `GET /api/notifications`: Returns current notifications array and unread count.
  - `POST /api/notifications/clear`: Clears the notification queue.
  - `POST /api/notifications/test`: Synthetic test alert generator.
- **Client Polling:** `static/js/notifications.js` polls every 5 seconds, dynamically toggling the unread badge and rendering formatted severity chips (`INFO`, `WARNING`, `ERROR`, `CRITICAL`).

---

## 6. Terminal Logs & Live Subsystem Monitor

- **Route:** `GET /manager/logs` (`manager/templates/logs.html`).
- **Telemetry Endpoints:**
  - `GET /api/logs`: Retrieves recent structured logs with timestamp, subsystem, level, and message.
  - `GET /api/logs/export/csv` (or `/api/logs/export`): Downloads log traces in standard RFC 4180 CSV format.
  - `GET /api/logs/download/txt` (or `/api/logs/download`): Direct stream download of raw `data/logs/openpos_system.log`.
  - `GET /api/logs/live_stream?subsystem=<name>`: Server-Sent Events (SSE) streaming daemon output line-by-line in real time into a styled retro-dark terminal container with pause and clear controls.

---

## 7. Configure Manager Admin Panel

- **Route:** `GET /manager/configure_manager` (`manager/templates/configure_manager.html`).
- **Password Layout & Alignment:**
  - Password inputs align in a uniform 3-column CSS grid (`.password-grid`): Current Password, New PIN/Password, Confirm Password.
  - When no password exists in `data/config/manager_auth.json`, "Current Password" is disabled with placeholder "No current password set", and "Require Manager Password" defaults to unchecked (`False`).
- **Access Control & Employee Lockout:**
  - Enforces manager PIN/password before allowing access to sensitive administrative modules.
  - Configuration saved to `data/config/manager_auth.json` (untracked by git).
  - Passwords are salted using `secrets.token_hex(16)` and hashed with SHA-256 (`hashlib.sha256`).
- **Startup & Register Bypass:**
  - "Bypass Manager on Boot" toggle saves to `manager_auth.json`. When enabled, supervisor launches directly into the Cashier Register UI.
- **Python Dependency Maintenance:**
  - `GET /api/system/packages`: Runs `pip list --outdated --format=json` in the active virtual environment.
  - `POST /api/system/packages/upgrade`: Upgrades individual packages safely with input validation.
  - Core peripheral updates (`waitress`, `pywebview`, `flask`, `pystray`) trigger a warning banner prompting a restart via `POST /api/system/restart`.

---

## 8. Isolated Private Data Directory Architecture (`data/`)

All store-specific data is strictly quarantined inside an untracked `data/` directory to prevent git collision during upstream repository pulls:
- `data/db/`: SQLite database files (`pos_store.db`, `shop_inventory.db`).
- `data/cache/`: Cached card artwork and metadata.
- `data/uploads/`: Store brand logos and uploaded images.
- `data/logs/`: Application telemetry and execution traces (`openpos_system.log`).
- `data/config/`: Configuration `.env`, security policies (`manager_auth.json`), and setup lock (`.setup_complete`).
- `data/custom_addons/`: Custom site-specific addons.
- All folders are tracked in git via `.gitkeep` files while `.gitignore` ignores all actual data files, keys, and DBs.

---

## 9. First-Run Setup Wizard (`core/setup/` & `/setup`)

- **Onboarding Pipeline:**
  - On application boot, `run.py` checks for `data/config/.setup_complete`.
  - If missing, launches the Setup Wizard (`980x800`, min `900x720`, title="OpenPOS - Initial Setup & Security Initialization") to guide store owners through initial configuration.
- **Setup Tamper & Re-provisioning Guard:**
  - If `data/config/.setup_complete` is removed but existing credentials (`data/config/manager_auth.json`) or encryption keys (`data/config/.env`) are detected, access to Step 1 is locked behind a **Re-Configuration Authentication** gate.
  - The administrator password must be verified before setup can be modified. Users can also select "Cancel & Launch System" to immediately restore `.setup_complete` and launch Open-POS.
- **6-Step Setup Flow:**
  1. Prerequisites check: Verifies Python 3.12+, DB drivers, cryptography, and writable `data/` directories. Supports automated dependency installation via auto-pip.
  2. Store identity: Collects Store Name, Legal Entity Name, City/State, and optional Store Logo image upload.
  3. Security & Manager Credentials: Sets admin password/PIN and lockout preference.
  4. Database Engine: Standalone SQLite (`data/db/pos_store.db`) vs. Network PostgreSQL.
  5. Cryptographic Initialization: Generates 32-byte Fernet AES-128 key, 32-byte Flask secret key, Emergency Recovery Token, and runs read/write roundtrip test.
  6. Recovery Key Sheet & Desktop Shortcut: Displays high-contrast Master Recovery Key, supports saving `.txt` recovery key file, printing via `@media print` formatted for 8.5x11 paper or PDF printer, and automatically generates an `OpenPOS.lnk` shortcut on the Windows Desktop.
- **Permanent Lockout:**
  - Once completed, creates `data/config/.setup_complete`.
  - Any subsequent attempts to access `/setup` return HTTP 403 Forbidden.

---

## 10. Resilient Addon Engine & Plugin Sandboxing (`core/addons/` & `/manager/addons`)

- **Dual-Directory Discovery:**
  - Built-in addons: `Open-POS/addons/<addon_id>/`
  - Custom / private user extensions: `data/custom_addons/<addon_id>/`
- **Manifest Specification (`manifest.json`):**
  - Requires `id`, `name`, `version`, `entrypoint`.
  - Optional declarations: `category`, `icon`, `author`, `description`, `requires_db`, `dependencies`, `settings_route`, and `min_core_version`.
- **Fault-Tolerant Sandboxed Lifecycle:**
  - Manifest schema validation against the formal contract.
  - Third-party dependency verification via `importlib.import_module()`.
  - Database-agnostic automated migrations (`schema_sqlite.sql` or `schema_postgres.sql`).
  - Dynamic Flask Blueprint mounting under `/addons/<addon_id>/` with automatic 503 guard when disabled.
  - Dynamic Hook Bus registration (`on_sale_complete`, etc.) with event isolation.
  - Complete error boundary: exceptions are caught, formatted with full stack traces, logged to `data/logs/` and `core/notifications.py`, marking the addon `ERROR` / `FAILED` without crashing the core POS.
- **Addons Control Center (`manager/templates/addons.html`):**
  - Real-time enable/disable toggling persisted to SQLite/PostgreSQL `settings` table without server restarts.
  - Diagnostic error trace modal rendering exact Python tracebacks for quick developer debugging.
  - One-click ZIP package import (`POST /api/addons/import`) with automated structure validation and zip-slip path traversal guards.
  - Custom addon uninstallation (`DELETE /api/addons/<addon_id>`) with confirmation modal and core built-in addon deletion protection.

---

## 11. Test Isolation, Error Guardians & Session Persistence (v1.0.7)

- **Absolute Test Isolation (`tests/conftest.py`):**
  - Autouse fixture `isolate_test_environment` guarantees automated test suites (`pytest`) execute strictly in an isolated temporary directory (`tmp_path`).
  - Active store databases (`data/db/pos_store.db`), logo uploads, and credentials are never touched, mutated, or seeded with mock test data.
  - Default settings initialization uses `INSERT ... ON CONFLICT DO NOTHING` to prevent overwriting existing user-configured branding.
- **Global Error Handlers (`app.py`, `manager/templates/error.html`):**
  - Global `@app.errorhandler(404)` and `@app.errorhandler(500)` intercept all broken routes or uncaught runtime exceptions.
  - Standardized OpenPOS error page styled in dark theme with error code badge, requested route chip, and prominent `← Return to System Manager` button.
  - Unregistered addon applet routes gracefully resolve to `/manager/placeholder/<addon_id>` instead of dead-ending on a 404.
- **Persistent Manager Session & Lockout Guard (`core/config.py`, `manager/routes.py`, `static/js/lockout_guard.js`):**
  - `SECRET_KEY` is permanently generated and persisted to `data/config/.env` on first boot, preventing session invalidation on server reloads.
  - `SESSION_COOKIE_HTTPONLY = True` and `SESSION_COOKIE_SAMESITE = 'Lax'` ensure reliable, secure cookie transport.
  - Once manager credentials are authenticated (`session['manager_authenticated'] = True`), client-side lockout guards immediately bypass password prompts across all subviews.
- **Decoupled Generic Retail Branding:**
  - Store branding is restricted strictly to retail identity: Store Name, Legal Entity Name, City/State, Currency Symbol, Tax Rate (%), and Store Logo.
  - TCG-specific trade-in rules, cash/credit payout ratios, and condition multipliers are decoupled from core into `addons/tcg_pos/default_rules.json`.

---

## 12. Remote Addon Catalog Engine, Network Downloader & Setup Provisioning (v1.0.8)

### Remote Addon Catalog Specification (`core/addons/catalog.py`)
Open-POS supports dynamic discovery and one-click installation of community and internal extensions via remote JSON registries.

- **Catalog Registry URL:** Configured in `settings` table via `addon_catalog_url` (default: `https://raw.githubusercontent.com/Cave404/Open-POS/main/addons_catalog.json`).
- **Catalog JSON Schema:**
  ```json
  [
    {
      "id": "tcg_pos",
      "name": "TCG POS & Singles Engine",
      "version": "1.0.0",
      "author": "Open-POS Community",
      "description": "Inventory, buylist trade-in calculator, and singles sales for Magic: The Gathering and Pokémon.",
      "category": "Desktop_Apps",
      "icon_url": "https://raw.githubusercontent.com/Cave404/Open-POS/main/static/img/addons/cards.png",
      "download_url": "https://github.com/Cave404/Open-POS-TCG/archive/refs/heads/main.zip",
      "dependencies": ["requests"],
      "requires_db": true,
      "min_core_version": "1.0.0"
    }
  ]
  ```
- **Resilient Caching & Offline Fallback:**
  - `fetch_catalog(force_refresh=False)` caches the catalog in `data/cache/catalog_cache.json` for 6 hours.
  - Remote fetches enforce a non-blocking 5-second timeout. If offline or if the registry is unreachable, stale cache or a clean empty array `[]` is returned without raising unhandled exceptions or disrupting local operations.

### Automated Network Downloader & Installation Pipeline (`core/addons/installer.py`)
- **Compatibility Check:** Inspects `min_core_version` against `Config.VERSION`. Outdated core versions are rejected with actionable upgrade messages.
- **Streaming Download:** Downloads the `.zip` archive to `data/cache/temp_<addon_id>.zip`.
- **Zip-Slip Protection & Extraction:** Inspects and validates `manifest.json`, extracting files strictly into `data/custom_addons/<addon_id>/`.
- **Automated Database Migrations:** If `requires_db` is true, detects the active database engine (`sqlite` vs `postgres`) and executes `migrations/schema_sqlite.sql` or `migrations/schema_postgres.sql`.
- **Instant Hot-Mount:** Registers the addon blueprint and hooks dynamically via `addon_manager.load_addon()` without requiring a server reboot.
- **Cleanup:** Automatically deletes temporary downloaded archives.

### Untracked Addon Storage (`data/custom_addons/`)
- All remotely installed plugins reside exclusively inside `data/custom_addons/<addon_id>/`.
- The repository `.gitignore` ignores `data/*` while preserving `.gitkeep`, ensuring custom addons and store data are never committed to the core Git repository.

### Setup Wizard Provisioning Step
- Setup Wizard integrates an optional **Step 5: Optional Integrations & Addons**.
- Asynchronously queries the catalog registry, presents selectable extension checkboxes, and provisions selected items in sequence during finalization before launching OpenPOS.
