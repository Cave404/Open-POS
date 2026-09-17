/**
 * Open-POS Addon Management & Lifecycle Controller
 * Provides non-blocking floating toast notifications, instant DOM synchronization,
 * catalog state caching, and quiet background data re-fetching.
 */

// Global registry of catalog addons for tab-switching persistence
window.catalogAddons = window.catalogAddons || [];
window.catalogData = window.catalogData || [];

/**
 * Dispatches a modern floating toast notification in the bottom-right corner.
 * Supports 'info' (in-flight spinner), 'success' (green check + 3.5s progress bar), and 'error' (red alert).
 *
 * @param {string} addonId - Unique identifier of the addon.
 * @param {string} title - Main headline for the toast.
 * @param {string} message - Descriptive subtitle or error detail.
 * @param {'info'|'success'|'error'} type - Notification state.
 */
function showAddonToast(addonId, title, message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '1080';
        document.body.appendChild(container);
    }

    const toastId = `toast-${addonId}`;

    // Remove existing toast for same addon if present
    const existing = document.getElementById(toastId);
    if (existing) existing.remove();

    const icon = type === 'success'
        ? '<span class="text-success me-2" style="font-size: 1.25rem; font-weight: bold;">✓</span>'
        : type === 'error'
        ? '<span class="text-danger me-2" style="font-size: 1.25rem; font-weight: bold;">✕</span>'
        : '<span class="spinner-border spinner-border-sm text-primary me-2" role="status"></span>';

    const safeTitle = escapeToastHtml(title);
    const safeMessage = escapeToastHtml(message);

    const toastHtml = `
        <div id="${toastId}" class="addon-toast" role="alert">
            <div class="d-flex align-items-center justify-content-between p-3">
                <div class="d-flex align-items-center">
                    ${icon}
                    <div>
                        <div class="fw-bold fs-6">${safeTitle}</div>
                        <div class="text-muted small">${safeMessage}</div>
                    </div>
                </div>
                <button type="button" class="btn-close btn-close-white ms-2" aria-label="Close" onclick="document.getElementById('${toastId}').remove()"></button>
            </div>
            ${type === 'success' ? `<div class="addon-toast-progress" id="progress-${toastId}"></div>` : ''}
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);

    if (type === 'success') {
        const progress = document.getElementById(`progress-${toastId}`);
        setTimeout(() => {
            if (progress) progress.style.width = '0%';
        }, 50);
        setTimeout(() => {
            const el = document.getElementById(toastId);
            if (el) el.remove();
        }, 3600);
    }
}

/**
 * Escapes HTML characters for safe toast content injection.
 */
function escapeToastHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Installs an addon via API, mutates catalog DOM immediately, updates cache,
 * syncs notification bell, and performs quiet soft-refresh without page reloads.
 *
 * @param {string} addonId - Addon ID.
 * @param {string} [addonName] - Human-readable display name.
 * @param {HTMLElement} [btnEl] - The button element triggering the install.
 */
async function installAddon(addonId, addonName, btnEl) {
    const name = addonName || addonId;
    const installBtn = btnEl
        || document.querySelector(`.btn-install-addon[data-id="${addonId}"]`)
        || document.querySelector(`#catalog-card-${addonId} .btn-install-addon`);

    const originalHtml = installBtn ? installBtn.innerHTML : '';
    if (installBtn) {
        installBtn.disabled = true;
        installBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> Installing...`;
    }

    // State 1: In-Flight Toast
    showAddonToast(addonId, "Installing Extension", `Setting up ${name}...`, "info");

    try {
        const response = await fetch('/api/addons/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ addon_id: addonId })
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.message || data.error || "Installation rejected by server.");
        }

        // State 2: Success Toast (auto-dismisses after 3.5s)
        showAddonToast(addonId, "Installation Complete", `${name} is mounted and ready.`, "success");

        // 2. Synchronize Catalog Card Immediately in the DOM
        const targetBtn = installBtn
            || document.querySelector(`.btn-install-addon[data-id="${addonId}"]`)
            || document.querySelector(`#catalog-card-${addonId} .btn-install-addon`);
        if (targetBtn) {
            const badge = document.createElement('span');
            badge.className = 'badge bg-success-subtle text-success border border-success-subtle px-3 py-2 fs-6 btn-installed-badge';
            badge.style.cssText = 'background: rgba(35, 134, 54, 0.2); color: #3fb950; border: 1px solid rgba(56, 139, 253, 0.4); padding: 5px 12px; border-radius: 6px; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px;';
            badge.innerHTML = '✓ Installed';
            targetBtn.replaceWith(badge);
        }

        // 3. Mark in internal state / catalog cache
        const updateCache = (list) => {
            if (Array.isArray(list)) {
                const target = list.find(a => a.id === addonId);
                if (target) {
                    target.is_installed = true;
                    target.has_update = false;
                    if (data.version) target.installed_version = data.version;
                }
            }
        };

        if (typeof allCatalogAddons !== 'undefined') updateCache(allCatalogAddons);
        updateCache(window.allCatalogAddons);
        updateCache(window.catalogAddons);
        updateCache(window.catalogData);

        // 4. Clean Soft-Refresh of installed tab without window.location.reload()
        if (typeof renderInstalledAddons === 'function') {
            renderInstalledAddons();
        }
        if (typeof loadInstalledAddons === 'function') {
            await loadInstalledAddons();
        } else if (typeof loadAddons === 'function') {
            await loadAddons();
        }

        // 5. Notification Bell Sync
        syncNotificationBell(name, data.version);

    } catch (err) {
        // State 3: Error Toast
        showAddonToast(addonId, "Installation Failed", err.message, "error");
        if (installBtn) {
            installBtn.disabled = false;
            installBtn.innerHTML = originalHtml || `⬇️ Install Addon`;
        }
    }
}

/**
 * Increments the notification bell counter and appends a completed item to the drawer.
 *
 * @param {string} name - Addon name.
 * @param {string} [version] - Addon version.
 */
function syncNotificationBell(name, version) {
    // Increment notification badge
    const badge = document.getElementById('notifBadge');
    if (badge) {
        let currentCount = parseInt(badge.textContent, 10);
        if (isNaN(currentCount)) currentCount = 0;
        const newCount = currentCount + 1;
        badge.textContent = newCount > 99 ? '99+' : newCount;
        badge.style.display = 'inline-block';
    }

    // Append completed task item to notification drawer
    const listEl = document.getElementById('notifList');
    if (listEl) {
        const emptyState = listEl.querySelector('.notif-empty');
        if (emptyState) emptyState.remove();

        const item = document.createElement('div');
        item.className = 'notif-item';
        const now = new Date().toLocaleTimeString();
        const verStr = version ? ` v${version}` : '';
        item.innerHTML = `
            <div class="notif-meta">
                <div class="notif-meta-left">
                    <span class="notif-tag tag-info" style="background: rgba(35, 134, 54, 0.2); color: #3fb950; border: 1px solid rgba(56, 139, 253, 0.3); border-radius: 4px; padding: 2px 6px; font-size: 11px; font-weight: 600;">SUCCESS</span>
                    <span class="notif-subsystem" style="color: var(--text-muted); font-size: 11px; margin-left: 6px;">ADDONS</span>
                </div>
                <span style="color: var(--text-muted); font-size: 11px;">${now}</span>
            </div>
            <div class="notif-msg" style="margin-top: 4px; font-size: 13px; color: #f0f6fc;">Addon Installed: ${escapeToastHtml(name)}${verStr}</div>
        `;
        listEl.prepend(item);
    }
}

/**
 * Soft refreshes installed addons without page reload.
 */
function renderInstalledAddons() {
    if (typeof renderAddonsGrid === 'function') {
        renderAddonsGrid();
    }
}

function loadInstalledAddons() {
    if (typeof loadAddons === 'function') {
        return loadAddons();
    }
}

// Global aliases for backwards compatibility
window.showAddonToast = showAddonToast;
window.installAddon = installAddon;
window.installRemoteAddon = installAddon;
window.syncNotificationBell = syncNotificationBell;
window.renderInstalledAddons = renderInstalledAddons;
window.loadInstalledAddons = loadInstalledAddons;
