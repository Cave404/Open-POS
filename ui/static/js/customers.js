/**
 * customers.js — Customer Directory client-side controller
 * Open-POS v1.0.9
 *
 * Responsibilities:
 *  - Debounced search with AbortController cancellation
 *  - Customer table rendering
 *  - Profile drawer: editable fields + immutable ledger audit table
 *  - New Customer, Badge Assignment, Credit Adjustment modals
 *  - Ghost Tag Safeguard: listens for openpos:hardware-scan events
 *  - Toast notification system
 */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let _currentCustomerId = null;
let _creditType = 'deposit';        // 'deposit' | 'redeem'
let _currentBalance = 0.0;
let _searchDebounce = null;
let _searchController = null;

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    loadCustomers('');

    // Debounced search
    document.getElementById('customerSearchInput').addEventListener('input', (e) => {
        clearTimeout(_searchDebounce);
        _searchDebounce = setTimeout(() => loadCustomers(e.target.value.trim()), 300);
    });

    // Ghost Tag Safeguard — listen for hardware NFC scan events
    window.addEventListener('openpos:hardware-scan', (e) => {
        const uid = (e.detail && e.detail.uid) ? e.detail.uid.toString().toUpperCase() : '';
        if (uid && document.getElementById('badgeModal').classList.contains('open')) {
            document.getElementById('badgeUidInput').value = uid.slice(0, 14);
            validateUidInput(document.getElementById('badgeUidInput'));
        }
    });
});

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function apiFetch(url, opts = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
        ...opts
    });
    const data = await resp.json();
    return { ok: resp.ok, status: resp.status, data };
}

// ---------------------------------------------------------------------------
// Load & render customer table
// ---------------------------------------------------------------------------
async function loadCustomers(query) {
    if (_searchController) _searchController.abort();
    _searchController = new AbortController();

    const tbody = document.getElementById('customersTableBody');

    try {
        const url = `/api/core/customers/search?q=${encodeURIComponent(query)}&limit=50`;
        const resp = await fetch(url, { signal: _searchController.signal });
        const rows = await resp.json();
        renderTable(rows);
    } catch (err) {
        if (err.name === 'AbortError') return;
        tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state">
            <div class="empty-icon">⚠️</div>
            <h3>Failed to load customers</h3>
            <p>${err.message}</p>
        </div></td></tr>`;
    }
}

function renderTable(rows) {
    const tbody = document.getElementById('customersTableBody');
    if (!rows || rows.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state">
            <div class="empty-icon">👥</div>
            <h3>No customers found</h3>
            <p>Create your first customer or refine your search.</p>
        </div></td></tr>`;
        return;
    }

    tbody.innerHTML = rows.map(c => {
        const badge = c.nfc_uid
            ? `<span class="badge-pill assigned">📡 ${c.nfc_uid}</span>`
            : `<span class="badge-pill unassigned">Unassigned</span>`;

        const balanceClass = c.store_credit_balance > 0 ? 'credit-balance' : 'credit-balance zero';
        const balance = `<span class="${balanceClass}">$${c.store_credit_balance.toFixed(2)}</span>`;

        return `<tr onclick="openDrawer(${c.id})">
            <td>
                <div class="customer-name">${escHtml(c.name)}</div>
                ${c.email ? `<div class="customer-email">${escHtml(c.email)}</div>` : ''}
            </td>
            <td>${c.phone ? escHtml(c.phone) : '<span style="color:var(--text-muted)">—</span>'}</td>
            <td>${c.email ? escHtml(c.email) : '<span style="color:var(--text-muted)">—</span>'}</td>
            <td>${badge}</td>
            <td>${balance}</td>
            <td onclick="event.stopPropagation()">
                <div class="action-btns">
                    <button class="btn-icon-sm credit" title="Adjust Credit"
                            onclick="openCreditModal(${c.id}, ${c.store_credit_balance})">💳</button>
                    <button class="btn-icon-sm badge-btn" title="Assign Badge"
                            onclick="openBadgeModal(${c.id})">📡</button>
                    <button class="btn-icon-sm" title="View Profile"
                            onclick="openDrawer(${c.id})">👁</button>
                </div>
            </td>
        </tr>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Profile Drawer
// ---------------------------------------------------------------------------
async function openDrawer(customerId) {
    _currentCustomerId = customerId;
    document.getElementById('drawerOverlay').style.display = 'block';
    document.getElementById('profileDrawer').classList.add('open');
    document.getElementById('drawerBody').innerHTML = '<p style="padding:20px;color:var(--text-muted);">Loading…</p>';
    document.getElementById('drawerTitle').textContent = 'Customer Profile';

    try {
        const { ok, data } = await apiFetch(`/api/core/customers/${customerId}`);
        if (!ok) { showToast(data.message || 'Failed to load customer', 'error'); return; }
        const c = data.customer;
        _currentBalance = c.store_credit_balance;
        document.getElementById('drawerTitle').textContent = c.name;
        renderDrawer(c);
        loadLedger(customerId);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderDrawer(c) {
    const badge = c.nfc_uid
        ? `<span class="badge-pill assigned">📡 ${c.nfc_uid}</span>`
        : `<span class="badge-pill unassigned">Unassigned</span>`;

    document.getElementById('drawerBody').innerHTML = `
        <!-- Balance hero -->
        <div class="balance-hero">
            <div>
                <div class="balance-hero-amount">$${c.store_credit_balance.toFixed(2)}</div>
                <div class="balance-hero-label">Store Credit Balance</div>
            </div>
            <button class="btn-adjust-credit" onclick="openCreditModal(${c.id}, ${c.store_credit_balance})">
                💳 Adjust Credit
            </button>
        </div>

        <!-- Editable fields -->
        <div class="profile-fields">
            <div class="form-group">
                <label>Full Name</label>
                <input type="text" id="editName" value="${escHtml(c.name || '')}">
            </div>
            <div class="form-group">
                <label>Phone</label>
                <input type="text" id="editPhone" value="${escHtml(c.phone || '')}">
            </div>
            <div class="form-group">
                <label>Email</label>
                <input type="text" id="editEmail" value="${escHtml(c.email || '')}">
            </div>
            <div class="form-group" style="grid-column:1/-1">
                <label>Notes</label>
                <input type="text" id="editNotes" value="${escHtml(c.notes || '')}">
            </div>
        </div>

        <!-- NFC Badge row -->
        <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.4px;display:block;margin-bottom:8px;">NFC Badge</label>
            <div class="badge-row">
                ${badge}
                <button class="btn-assign-badge" onclick="openBadgeModal(${c.id})">
                    📡 ${c.nfc_uid ? 'Reassign Badge' : 'Assign Badge'}
                </button>
            </div>
        </div>

        <!-- Save profile button -->
        <div class="drawer-save-row">
            <button class="btn-primary" onclick="saveProfile(${c.id})">💾 Save Profile</button>
        </div>

        <!-- Lifetime stats -->
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">
            <div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:18px;font-weight:700;color:#34d399;">$${c.stats.total_deposited.toFixed(2)}</div>
                <div style="font-size:10px;color:var(--text-muted);margin-top:3px;text-transform:uppercase;letter-spacing:0.4px;">Total Deposited</div>
            </div>
            <div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:18px;font-weight:700;color:#f87171;">$${c.stats.total_redeemed.toFixed(2)}</div>
                <div style="font-size:10px;color:var(--text-muted);margin-top:3px;text-transform:uppercase;letter-spacing:0.4px;">Total Redeemed</div>
            </div>
            <div style="background:var(--bg-card);border:1px solid var(--border-color);border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:18px;font-weight:700;color:#60a5fa;">${c.stats.total_transactions}</div>
                <div style="font-size:10px;color:var(--text-muted);margin-top:3px;text-transform:uppercase;letter-spacing:0.4px;">Transactions</div>
            </div>
        </div>

        <!-- Immutable Ledger -->
        <div class="ledger-section">
            <h4>📋 Credit Audit Ledger (Immutable)</h4>
            <table class="ledger-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Type</th>
                        <th>Amount</th>
                        <th>Balance After</th>
                        <th>Source</th>
                        <th>Notes</th>
                    </tr>
                </thead>
                <tbody id="ledgerTableBody">
                    <tr><td colspan="6" class="ledger-empty">Loading ledger…</td></tr>
                </tbody>
            </table>
        </div>
    `;
}

async function loadLedger(customerId) {
    const { ok, data } = await apiFetch(`/api/core/customers/${customerId}/ledger?per_page=100`);
    const tbody = document.getElementById('ledgerTableBody');
    if (!tbody) return;

    if (!ok || !data.entries || data.entries.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="ledger-empty">No ledger entries yet.</td></tr>`;
        return;
    }

    tbody.innerHTML = data.entries.map(e => {
        const amtClass = e.amount > 0 ? 'ledger-amount positive' : 'ledger-amount negative';
        const amtStr = e.amount > 0 ? `+$${e.amount.toFixed(2)}` : `-$${Math.abs(e.amount).toFixed(2)}`;
        const typeChip = `<span class="ledger-type-chip ${e.transaction_type}">${e.transaction_type.replace('_',' ')}</span>`;
        const date = e.created_at ? e.created_at.replace('T', ' ').slice(0, 16) : '—';
        return `<tr>
            <td style="color:var(--text-muted);font-size:11px;">${date}</td>
            <td>${typeChip}</td>
            <td class="${amtClass}">${amtStr}</td>
            <td style="font-weight:600;">$${e.balance_after.toFixed(2)}</td>
            <td style="color:var(--text-muted);font-size:11px;">${escHtml(e.source_addon || 'core')}</td>
            <td style="color:var(--text-muted);font-size:11px;">${escHtml(e.notes || e.reference_id || '—')}</td>
        </tr>`;
    }).join('');
}

function closeDrawer() {
    document.getElementById('drawerOverlay').style.display = 'none';
    document.getElementById('profileDrawer').classList.remove('open');
    _currentCustomerId = null;
}

async function saveProfile(customerId) {
    const payload = {
        name: document.getElementById('editName').value.trim(),
        phone: document.getElementById('editPhone').value.trim() || null,
        email: document.getElementById('editEmail').value.trim() || null,
        notes: document.getElementById('editNotes').value.trim() || null,
    };
    const { ok, data } = await apiFetch(`/api/core/customers/${customerId}`, {
        method: 'PATCH', body: JSON.stringify(payload)
    });
    if (ok) {
        showToast('Profile saved.', 'success');
        loadCustomers(document.getElementById('customerSearchInput').value);
    } else {
        showToast(data.message || 'Save failed.', 'error');
    }
}

// ---------------------------------------------------------------------------
// New Customer Modal
// ---------------------------------------------------------------------------
function openNewCustomerModal() {
    ['newName','newPhone','newEmail','newNotes'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const ic = document.getElementById('newInitialCredit');
    if (ic) ic.value = '0';
    openModal('newCustomerModal');
}

async function createCustomer() {
    const name = document.getElementById('newName').value.trim();
    if (!name) { showToast('Customer name is required.', 'error'); return; }

    const payload = {
        name,
        phone: document.getElementById('newPhone').value.trim() || null,
        email: document.getElementById('newEmail').value.trim() || null,
        notes: document.getElementById('newNotes').value.trim() || null,
        initial_credit: parseFloat(document.getElementById('newInitialCredit').value) || 0,
        source_addon: 'core',
    };

    const btn = document.getElementById('btnCreateCustomer');
    btn.disabled = true;
    btn.textContent = 'Creating…';

    const { ok, data } = await apiFetch('/api/core/customers', {
        method: 'POST', body: JSON.stringify(payload)
    });

    btn.disabled = false;
    btn.textContent = 'Create Customer';

    if (ok) {
        showToast(`Customer '${name}' created successfully.`, 'success');
        closeModal('newCustomerModal');
        loadCustomers('');
    } else {
        showToast(data.message || 'Failed to create customer.', 'error');
    }
}

// ---------------------------------------------------------------------------
// Badge Assignment Modal
// ---------------------------------------------------------------------------
function openBadgeModal(customerId) {
    _currentCustomerId = customerId;
    document.getElementById('badgeUidInput').value = '';
    document.getElementById('uidCharCount').textContent = '0 / 14 characters';
    document.getElementById('uidCharCount').className = 'uid-chars-counter';
    openModal('badgeModal');
}

function validateUidInput(el) {
    // Strip and uppercase on the fly
    const cleaned = el.value.replace(/[^A-Fa-f0-9]/g, '').toUpperCase().slice(0, 14);
    el.value = cleaned;
    const counter = document.getElementById('uidCharCount');
    counter.textContent = `${cleaned.length} / 14 characters`;
    counter.className = 'uid-chars-counter ' + (cleaned.length === 14 ? 'valid' : (cleaned.length > 0 ? 'invalid' : ''));
}

async function assignBadge() {
    const uid = document.getElementById('badgeUidInput').value.trim();
    if (uid.length !== 14) {
        showToast('UID must be exactly 14 hexadecimal characters.', 'error');
        return;
    }

    const btn = document.getElementById('btnAssignBadge');
    btn.disabled = true;
    btn.textContent = 'Assigning…';

    const { ok, data } = await apiFetch(`/api/core/customers/${_currentCustomerId}/badge`, {
        method: 'POST', body: JSON.stringify({ nfc_uid: uid })
    });

    btn.disabled = false;
    btn.textContent = 'Assign Badge';

    if (ok) {
        showToast(`Badge ${uid} assigned. Ghost Tag Safeguard dispatched.`, 'success');
        closeModal('badgeModal');
        loadCustomers(document.getElementById('customerSearchInput').value);
        if (_currentCustomerId) openDrawer(_currentCustomerId);
    } else {
        showToast(data.message || 'Badge assignment failed.', 'error');
    }
}

// ---------------------------------------------------------------------------
// Credit Adjustment Modal
// ---------------------------------------------------------------------------
function openCreditModal(customerId, currentBalance) {
    _currentCustomerId = customerId;
    _currentBalance = currentBalance;
    setCreditType('deposit');
    document.getElementById('creditAmount').value = '';
    document.getElementById('creditRefId').value = '';
    document.getElementById('creditNotes').value = '';
    document.getElementById('creditBalancePreview').textContent = `Current balance: $${currentBalance.toFixed(2)}`;
    openModal('creditModal');
}

function setCreditType(type) {
    _creditType = type;
    const dBtn = document.getElementById('btnDeposit');
    const rBtn = document.getElementById('btnRedeem');
    dBtn.className = 'credit-type-btn ' + (type === 'deposit' ? 'active-deposit' : '');
    rBtn.className = 'credit-type-btn ' + (type === 'redeem' ? 'active-redeem' : '');

    document.getElementById('creditModalTitle').textContent =
        type === 'deposit' ? '💳 Deposit Store Credit' : '💳 Redeem Store Credit';
}

async function submitCredit() {
    const amount = parseFloat(document.getElementById('creditAmount').value);
    const notes = document.getElementById('creditNotes').value.trim();
    const refId = document.getElementById('creditRefId').value.trim();

    if (!amount || amount <= 0) { showToast('Enter a valid amount greater than $0.', 'error'); return; }
    if (!notes) { showToast('An audit reason / note is required.', 'error'); return; }

    const endpoint = _creditType === 'deposit' ? 'deposit' : 'redeem';
    const btn = document.getElementById('btnConfirmCredit');
    btn.disabled = true;
    btn.textContent = 'Processing…';

    const { ok, data } = await apiFetch(
        `/api/core/customers/${_currentCustomerId}/credit/${endpoint}`,
        {
            method: 'POST',
            body: JSON.stringify({
                amount,
                source_addon: 'core',
                reference_id: refId || null,
                notes,
            })
        }
    );

    btn.disabled = false;
    btn.textContent = 'Confirm';

    if (ok) {
        const action = _creditType === 'deposit' ? 'Deposited' : 'Redeemed';
        showToast(`${action} $${amount.toFixed(2)}. New balance: $${data.new_balance.toFixed(2)}`, 'success');
        closeModal('creditModal');
        loadCustomers(document.getElementById('customerSearchInput').value);
        if (_currentCustomerId) openDrawer(_currentCustomerId);
    } else {
        showToast(data.message || 'Credit operation failed.', 'error');
    }
}

// ---------------------------------------------------------------------------
// Modal helpers
// ---------------------------------------------------------------------------
function openModal(id) {
    document.getElementById(id).classList.add('open');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function showToast(message, type = 'info', durationMs = 3500) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 320);
    }, durationMs);
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
function escHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
