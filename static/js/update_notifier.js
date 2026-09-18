/**
 * Open-POS Universal Update Notifier, Changelog Inspector & Modal Controller
 * (static/js/update_notifier.js)
 */

(function () {
    'use strict';

    let currentUpdateData = null;

    // -------------------------------------------------------------------------
    // 1. Lifecycle Initialization
    // -------------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        setupVersionBadgeClick();
        pollUpdateStatus();
    });

    // -------------------------------------------------------------------------
    // 2. Version Badge & About Modal Bindings
    // -------------------------------------------------------------------------
    function setupVersionBadgeClick() {
        const badges = document.querySelectorAll('.version-badge-link, #headerVersionBadge');
        badges.forEach(badge => {
            badge.addEventListener('click', (e) => {
                // If modifier keys are held or user specifically wants about view, allow default navigation
                if (e.ctrlKey || e.metaKey) return;
                e.preventDefault();
                openAboutModal();
            });
        });
    }

    // -------------------------------------------------------------------------
    // 3. Status Polling & Floating Toast Beside Bell
    // -------------------------------------------------------------------------
    async function pollUpdateStatus() {
        try {
            const res = await fetch('/api/system/update/status');
            if (!res.ok) return;
            const data = await res.json();
            currentUpdateData = data;

            // Sync about modal version fields if present
            const aboutVer = document.getElementById('aboutModalVersion');
            if (aboutVer && data.current_version) {
                aboutVer.textContent = data.current_version;
            }

            const aboutStatusText = document.getElementById('aboutCheckStatusText');
            if (aboutStatusText) {
                if (data.update_available) {
                    aboutStatusText.innerHTML = `⚠️ <span style="color:#fb923c;">New Version Available: <strong>${data.latest_version}</strong></span>`;
                } else {
                    aboutStatusText.innerHTML = `✓ <span style="color:#34d399;">Up to date (${data.current_version})</span>`;
                }
            }

            if (data.update_available) {
                renderFloatingToast(data);
            }
        } catch (err) {
            console.debug('[UPDATER] Status check silently deferred:', err);
        }
    }

    function renderFloatingToast(data) {
        // Look for existing toast anchor
        let toast = document.getElementById('openposUpdateToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'openposUpdateToast';
            toast.className = 'openpos-update-toast';
            toast.style.cssText = `
                display: inline-flex;
                align-items: center;
                gap: 8px;
                background: linear-gradient(135deg, #1e293b, #0f172a);
                border: 1px solid #38bdf860;
                color: #f1f5f9;
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
                box-shadow: 0 4px 14px rgba(0,0,0,0.4);
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
                margin-right: 8px;
                animation: toastPulse 2.5s infinite;
            `;

            // Insert adjacent to notification bell wrapper
            const bellWrapper = document.querySelector('.notification-bell-wrapper') ||
                                document.querySelector('.notification-wrapper') ||
                                document.querySelector('.header-right');

            if (bellWrapper && bellWrapper.parentNode) {
                bellWrapper.parentNode.insertBefore(toast, bellWrapper);
            } else {
                // Fallback fixed bottom-right toast
                toast.style.position = 'fixed';
                toast.style.bottom = '24px';
                toast.style.right = '24px';
                toast.style.zIndex = '9998';
                document.body.appendChild(toast);
            }
        }

        const tag = data.latest_version || 'New Version';
        toast.innerHTML = `
            <span style="color: #38bdf8;">▲</span>
            <span>OpenPOS <strong>${tag}</strong> Available</span>
            <span style="color: #38bdf8; text-decoration: underline; margin-left: 2px;">[Review Changes]</span>
        `;

        toast.onclick = (e) => {
            e.stopPropagation();
            openChangelogModal();
        };
    }

    // -------------------------------------------------------------------------
    // 4. Changelog Modal Rendering & Actions
    // -------------------------------------------------------------------------
    window.openChangelogModal = function () {
        const modal = document.getElementById('changelogModal');
        if (!modal) return;

        const info = currentUpdateData || {};
        const curVer = info.current_version || 'v1.0.9';
        const newVer = info.latest_version || 'v1.1.0';

        const deltaBadge = document.getElementById('clModalDeltaBadge');
        if (deltaBadge) deltaBadge.textContent = `${curVer} → ${newVer}`;

        const modalTitle = document.getElementById('clModalTitle');
        if (modalTitle) modalTitle.textContent = info.release_name || `Release ${newVer}`;

        const modalDate = document.getElementById('clModalDate');
        if (modalDate) modalDate.textContent = (info.published_at || '').substring(0, 10) || 'Recently';

        const body = document.getElementById('clModalBody');
        if (body) {
            body.innerHTML = '';
            const cl = info.changelog || { added: [], changed: [], fixed: [], removed: [] };
            let hasAny = false;

            const renderBucket = (title, items, bucketClass) => {
                if (!items || items.length === 0) return;
                hasAny = true;
                const wrap = document.createElement('div');
                wrap.style.marginBottom = '14px';

                const badge = document.createElement('span');
                badge.className = `bucket-title ${bucketClass}`;
                badge.style.cssText = `
                    display: inline-flex;
                    align-items: center;
                    font-size: 11px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.8px;
                    padding: 2px 8px;
                    border-radius: 6px;
                    margin-bottom: 6px;
                `;
                badge.textContent = title;
                wrap.appendChild(badge);

                const ul = document.createElement('ul');
                ul.style.cssText = 'margin: 4px 0 0 16px; padding: 0; color: #cbd5e1; font-size: 13px; line-height: 1.5;';
                items.forEach(it => {
                    const li = document.createElement('li');
                    li.textContent = it;
                    li.style.marginBottom = '3px';
                    ul.appendChild(li);
                });
                wrap.appendChild(ul);
                body.appendChild(wrap);
            };

            renderBucket('● Added', cl.added, 'bucket-added');
            renderBucket('● Changed', cl.changed, 'bucket-changed');
            renderBucket('● Fixed', cl.fixed, 'bucket-fixed');
            renderBucket('● Removed', cl.removed, 'bucket-removed');

            if (!hasAny) {
                const p = document.createElement('p');
                p.style.color = '#94a3b8';
                p.textContent = info.raw_notes || 'No detailed changelog provided for this release.';
                body.appendChild(p);
            }
        }

        modal.style.display = 'flex';
    };

    window.closeChangelogModal = function () {
        const modal = document.getElementById('changelogModal');
        if (modal) modal.style.display = 'none';
    };

    window.executeInstallFromModal = async function () {
        if (!confirm('Are you sure you want to install and restart OpenPOS now?')) return;

        const installBtn = document.getElementById('clModalInstallBtn');
        const progressWrap = document.getElementById('clModalProgressWrap');
        const progressBar = document.getElementById('clModalProgressBar');
        const progressMsg = document.getElementById('clModalProgressMsg');

        if (installBtn) installBtn.disabled = true;
        if (progressWrap) progressWrap.style.display = 'block';
        if (progressBar) progressBar.style.width = '30%';
        if (progressMsg) progressMsg.textContent = 'Downloading release archive from GitHub...';

        try {
            const dlUrl = currentUpdateData ? currentUpdateData.download_url : null;
            const newVer = currentUpdateData ? currentUpdateData.latest_version : null;

            setTimeout(() => {
                if (progressBar) progressBar.style.width = '70%';
                if (progressMsg) progressMsg.textContent = 'Unpacking payload & executing engine health check...';
            }, 1200);

            const res = await fetch('/api/system/update/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ download_url: dlUrl, new_version: newVer })
            });

            const data = await res.json();

            if (data.success) {
                if (progressBar) progressBar.style.width = '100%';
                if (progressMsg) {
                    progressMsg.style.color = '#34d399';
                    progressMsg.textContent = 'Update verified OK! Detached supervisor restarting OpenPOS...';
                }
                setTimeout(() => {
                    window.location.reload();
                }, 3500);
            } else {
                if (progressBar) progressBar.style.background = '#ef4444';
                if (progressMsg) {
                    progressMsg.style.color = '#f87171';
                    progressMsg.textContent = data.message || 'Update failed and was rolled back.';
                }
                if (installBtn) installBtn.disabled = false;
            }
        } catch (err) {
            if (progressMsg) {
                progressMsg.style.color = '#f87171';
                progressMsg.textContent = 'Error during update: ' + err.message;
            }
            if (installBtn) installBtn.disabled = false;
        }
    };

    // -------------------------------------------------------------------------
    // 5. About Modal Controls
    // -------------------------------------------------------------------------
    window.openAboutModal = function () {
        const modal = document.getElementById('aboutModal');
        if (modal) modal.style.display = 'flex';
    };

    window.closeAboutModal = function () {
        const modal = document.getElementById('aboutModal');
        if (modal) modal.style.display = 'none';
    };

    window.checkUpdatesFromAboutModal = async function () {
        const btn = document.getElementById('aboutCheckBtn');
        const statusText = document.getElementById('aboutCheckStatusText');

        if (btn) btn.disabled = true;
        if (statusText) statusText.textContent = 'Querying GitHub API...';

        try {
            const res = await fetch('/api/system/update/check-now', { method: 'POST' });
            const data = await res.json();
            currentUpdateData = data;

            if (data.update_available) {
                if (statusText) {
                    statusText.innerHTML = `⚠️ <span style="color:#fb923c;">Update Available: <strong>${data.latest_version}</strong></span>`;
                }
                renderFloatingToast(data);
                // Transition to Changelog modal
                setTimeout(() => {
                    closeAboutModal();
                    openChangelogModal();
                }, 800);
            } else {
                if (statusText) {
                    statusText.innerHTML = `✓ <span style="color:#34d399;">OpenPOS is up to date (${data.current_version})</span>`;
                }
            }
        } catch (err) {
            if (statusText) statusText.textContent = 'Check failed: ' + err.message;
        } finally {
            if (btn) btn.disabled = false;
        }
    };

})();
