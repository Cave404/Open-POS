/**
 * Open-POS Notification Poller & Dropdown Controller
 */
(function() {
    let notifs = [];

    async function fetchNotifications() {
        try {
            const res = await fetch('/api/notifications');
            if (!res.ok) return;
            const data = await res.json();
            notifs = data.notifications || [];
            updateBadge(data.unread_count !== undefined ? data.unread_count : notifs.length);
        } catch (err) {
            // Silently swallow background polling errors
        }
    }

    function updateBadge(count) {
        const badge = document.getElementById('notifBadge');
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : count;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    }

    function renderDropdownList() {
        const listEl = document.getElementById('notifList');
        if (!listEl) return;
        listEl.innerHTML = '';

        if (!notifs || notifs.length === 0) {
            listEl.innerHTML = '<div class="notif-empty">No active system notifications.</div>';
            return;
        }

        notifs.forEach(n => {
            const item = document.createElement('div');
            item.className = 'notif-item';
            const lvlClass = `tag-${(n.level || 'info').toLowerCase()}`;
            item.innerHTML = `
                <div class="notif-meta">
                    <div class="notif-meta-left">
                        <span class="notif-tag ${lvlClass}">${n.level}</span>
                        <span class="notif-subsystem">${n.subsystem || 'CORE'}</span>
                    </div>
                    <span>${n.timestamp || ''}</span>
                </div>
                <div class="notif-msg">${escapeHtml(n.message || '')}</div>
            `;
            listEl.appendChild(item);
        });
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    async function clearAllNotifications() {
        try {
            await fetch('/api/notifications/clear', { method: 'POST' });
            notifs = [];
            updateBadge(0);
            renderDropdownList();
        } catch (err) {
            console.error('Failed to clear notifications:', err);
        }
    }

    function initNotificationTray() {
        const bellBtn = document.getElementById('notifBellBtn');
        const dropdown = document.getElementById('notifDropdown');
        const clearBtn = document.getElementById('clearNotifsBtn');

        if (bellBtn && dropdown) {
            bellBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isHidden = dropdown.style.display === 'none' || !dropdown.style.display;
                if (isHidden) {
                    renderDropdownList();
                    dropdown.style.display = 'flex';
                } else {
                    dropdown.style.display = 'none';
                }
            });

            document.addEventListener('click', (e) => {
                if (!dropdown.contains(e.target) && e.target !== bellBtn) {
                    dropdown.style.display = 'none';
                }
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                clearAllNotifications();
            });
        }

        // Initial fetch and start 5-second polling interval
        fetchNotifications();
        setInterval(fetchNotifications, 5000);
    }

    document.addEventListener('DOMContentLoaded', initNotificationTray);
})();
