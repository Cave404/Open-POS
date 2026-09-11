# Open-POS Developer Wiki & Technical Reference (v1.0.1)

Welcome to the **Open-POS** internal developer documentation. This living guide defines the runtime architecture, threading model, file layout, applet lifecycle, branding pipeline, and testing standards for the project.


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
│   ├── logs/                  # Activity and runtime diagnostic logs
│   └── custom_addons/         # Store-specific custom extensions
│
├── core/
│   ├── config.py              # Configuration dataclass (ports, data paths, DB credentials, defaults)
│   ├── db.py                  # Database connection manager (SQLite/PostgreSQL) & query abstraction
│   ├── settings.py            # Dynamic settings engine (get_setting, set_setting, seeding, JSON parsing)
│   └── boot.py                # Multi-phase startup boot sequencer & progress dispatcher
│
├── manager/
│   ├── routes.py              # System Manager controller: applet discovery, fallback guards, and APIs
│   ├── open_pos_splash.png    # High-resolution frameless startup splash screen graphic
│   └── templates/
│       ├── manager.html       # Primary HTML5 full-window System Manager dashboard & sidebar
│       ├── splash.html        # Frameless startup splash window with animated progress bar
│       ├── branding.html      # Store Branding & Business Rules configuration panel
│       ├── placeholder.html   # Universal Safe Navigation Guard for applets under construction
│       └── about.html         # System credits, contributor ledger, and dependency audit table
│
├── static/
│   └── css/
│       ├── manager.css        # Unified dark dashboard styling, card grid, forms, and toast notifications
│       └── cde_theme.css      # Retro CDE desktop styling tokens
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
1. A **dedicated business logic page** (e.g., `/manager/branding` -> `branding.html`, `/manager/about` -> `about.html`), OR
2. The **universal fallback view** (`/manager/placeholder/<applet_id>` -> `placeholder.html`).

### How to Add a New Applet

1. **Register the Applet in `manager/routes.py`:**
   ```python
   BUILTIN_APPLETS.append({
       "id": "inventory_sync",
       "title": "Inventory_Sync",
       "category": "Desktop_Tools",
       "icon": "sync.png",
       "target": "/manager/inventory_sync"
   })
   ```

2. **Add Informative Metadata to `APPLETS_META`:**
   ```python
   APPLETS_META["inventory_sync"] = {
       "title": "Inventory Synchronization",
       "icon": "🔄",
       "category": "Desktop Tools",
       "description": "Sync local stock levels with external TCG marketplaces and online kiosks."
   }
   ```

3. **Bind the Route:**
   - During prototyping, bind to `manager_placeholder`:
     ```python
     @manager_bp.route('/inventory_sync')
     def manager_inventory_sync():
         return manager_placeholder('inventory_sync')
     ```
   - When production-ready, replace with a dedicated template (e.g. `render_template('inventory_sync.html')`).

4. **Add UI Metadata in `manager/templates/manager.html`:**
   Add the applet's display icon and summary description to the JavaScript lookup objects (`ICONS` and `DESCRIPTIONS`).

---

## 4. Debugging & Runtime Modes

### Running in Headless / Web Dev Mode
For rapid web UI and API testing in standard web browsers:
```powershell
.\venv\Scripts\python.exe app.py
```
- Starts Flask on `http://127.0.0.1:5000` with live reload.
- Navigate to `http://127.0.0.1:5000/manager`.

### Running in Desktop Container Mode
To launch the full desktop application with Edge WebView2, Splash Screen, and System Tray supervisor:
```powershell
.\venv\Scripts\python.exe run.py
```

### Running the Automated Test Suite
Open-POS uses `pytest` for all unit and integration testing:
```powershell
.\venv\Scripts\pytest.exe tests/ -v
```

---

## 5. Security & Decoupling Checklist

- **No Hardcoded Secrets:** Cryptographic keys and database passwords must reside in `.env` or system environment variables.
- **Dynamic Database Portability:** Always use `execute_sql()` from `core/db.py` to ensure queries execute identically on both SQLite and PostgreSQL.
- **Input Type Sanitization:** All payload updates in `manager/routes.py` must validate boundaries (e.g., percentages 0–100, limits >= 1, non-empty strings) before calling `set_setting()`.

---

## 6. Boot Lifecycle & Splash Orchestration

Open-POS implements a visual, multi-phase boot sequence orchestrated by `core/boot.py` and `run.py`.

```
[0% - 20%] Phase 1: Environment & Config Verification
    │       - Validate .env and load core configuration.
    ▼
[20% - 45%] Phase 2: Git Repository Update Checker Hook
    │       - Query git remote status via dry-run or API.
    ▼
[45% - 70%] Phase 3: Database & Cache Sanity Check
    │       - Verify connection pool and settings schema integrity.
    ▼
[70% - 90%] Phase 4: Addon Manifest Discovery
    │       - Scan /addons directory for registered plugins.
    ▼
[90% - 100%] Phase 5: Finalization & Smooth Handoff
            - Hold on 'Finishing up...' (1.5s buffer) and spawn System Manager.
```

### Hooking Subsystems into the Boot Pipeline
Subsystem initialization routines (e.g., peripheral serial port scanning, receipt printer discovery, or card cache warming) can be registered inside `core/boot.py`:

```python
# Example: Adding a hardware verification step to Phase 3
_notify(65, "Scanning connected peripheral devices...")
# invoke peripheral scanner
_notify(70, "Hardware peripherals initialized.")
```

### Configuring Update Checks & Splash Assets
- **Update Checks:** Controlled by the dynamic setting `auto_updates_enabled` (`set_setting('auto_updates_enabled', True)`). When deferred or offline, the boot sequence completes cleanly without blocking.
- **Splash Screen Assets:** The splash graphic is located at `manager/open_pos_splash.png` (656x404 PNG). To rebrand the splash graphic, replace this file; the frameless window automatically scales and centres the asset.

---

## 7. Store Logo Uploads & POS-Wide Branding Architecture

Open-POS v1.0.1 introduces dynamic store logo image support:
- **API Endpoint:** `POST /api/settings/logo` (and `/manager/api/settings/logo`) accepts multipart form file uploads under key `logo`.
- **Validation:** 
  - Max file size: 2MB.
  - Permitted MIME types: `.png`, `.jpg`, `.jpeg`, `.svg`, `.webp`.
- **Storage:** Files are sanitized and stored in the isolated private data directory under `data/uploads/store_logo.<ext>`.
- **Setting Integration:** The relative URL path `/data/uploads/store_logo.<ext>` is saved to the `store_logo_url` key in the database `settings` table.
- **Sidebar Integration:** In `manager.html`, if `store_logo_url` is present, the sidebar dynamically renders the logo image and hides the fallback `POS` gradient badge. The store name dynamically displays the value of `store_name`.
- **Removal Action:** `DELETE /api/settings/logo` unlinks the uploaded file and sets `store_logo_url` to `""`.

---

## 8. Dashboard Applet Pinning System & Dedicated "Home" Tab

The System Manager provides a pinning mechanism for high-frequency control cards:
- **Dedicated "Home" Dashboard:** The `🏠 Home` view is the top-level tab and active by default on system launch.
  - Displays exclusively the tools pinned by the store.
  - If no tools are pinned, displays a clean placeholder empty-state card guiding staff to pin tools from categories.
- **Visual Pinning Mechanism:** Each `.control-card` features a pin button (`📌`). Pinned cards display with a `.pinned` class providing a glowing accent border.
- **Dual Persistence:**
  - **Client-Side:** Instant persistence via `localStorage.getItem('openpos_pinned_tools')`.
  - **Backend Synchronization:** Persisted across sessions and network workstations via `POST /api/settings/pinned` storing a JSON-encoded array into the `settings` table key `pinned_tools`. Default tools: `["branding", "database"]`.

---

## 9. Tactile Navigation & Native Layout Guarantee

- All pseudo-window styling (window-in-a-window headers, faux minimize/maximize buttons, `.cde-title-controls`) has been eradicated.
- Views flow natively across `.main-content` and `.view-container`.
- Safe back-navigation is standardized across all subviews (`branding.html`, `about.html`, `placeholder.html`) using the styled tactile component:
  ```html
  <a href="/manager" class="btn-back">
      <span class="btn-icon">←</span>
      <span>Return to Dashboard</span>
  </a>
  ```
- Version indicators link directly to About & Credits:
  ```html
  <a href="/manager/about" class="version-badge-link" title="View System Credits & Documentation">v1.0.1</a>
  ```

---

## 10. One-Click OOTB Desktop Launchers

Staff and cashiers run Open-POS without interacting with a command prompt:
- **`Open_POS.vbs`:** A clean VBScript wrapper that invokes `Start_POS.bat` in hidden mode (`0`), preventing console windows from flashing on screen.
- **`Start_POS.bat`:**
  - Automatically verifies and bootstraps the Python virtual environment (`venv/`) from `requirements.txt` if missing.
  - Initializes `.env` from `.env.example` if not already present.
  - Executes `run.py` using `venv\Scripts\python.exe`.
  - Features error traps that pause with diagnostic advice if execution fails.

---

## 11. Isolated Private Data Directory Architecture (`data/`)

All store-specific data is strictly quarantined inside an untracked `data/` directory to prevent git collision during upstream repository pulls:
- `data/db/`: SQLite database files (`pos_store.db`, `shop_inventory.db`).
- `data/cache/`: Cached card artwork and metadata.
- `data/uploads/`: Store brand logos and uploaded images.
- `data/logs/`: Application telemetry and execution traces.
- `data/custom_addons/`: Custom site-specific addons.
- All folders are tracked in git via `.gitkeep` files while `.gitignore` ignores all actual data files.


