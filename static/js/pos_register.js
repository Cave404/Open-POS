/**
 * =============================================================================
 * Open-POS Register Controller (pos_register.js)
 * =============================================================================
 * Governs:
 *   1. Hardware barcode & NFC wedge timing listener (< 35ms inter-key).
 *   2. Keyboard Hotkeys (F2, F4, F8, F12, Escape).
 *   3. Pluggable dynamic canvas swapping & workspace mode switcher.
 *   4. Cart synchronization, line item steppers, and quick-key products.
 *   5. Split tender payments (Cash, Card, Store Credit) & live change due.
 * =============================================================================
 */

(function () {
    'use strict';

    // State
    let activeCart = null;
    let heldOrdersCount = 0;
    let quickProducts = [];

    // Hardware Barcode Scanner Buffer State
    let barcodeBuffer = '';
    let lastKeyTimestamp = 0;
    const BARCODE_MAX_INTER_KEY_MS = 35; // Hardware scanners emit keystrokes faster than 35ms

    // -------------------------------------------------------------------------
    // Toast Notification Utility
    // -------------------------------------------------------------------------
    function showToast(message, isError = false) {
        const toast = document.getElementById('posToast');
        const msgEl = document.getElementById('posToastMsg');
        const iconEl = document.getElementById('posToastIcon');
        if (!toast || !msgEl) return;

        msgEl.textContent = message;
        iconEl.textContent = isError ? '⚠️' : '✓';
        toast.style.borderColor = isError ? 'var(--accent-red)' : 'var(--border-color)';
        toast.style.display = 'flex';

        setTimeout(() => {
            toast.style.display = 'none';
        }, 3200);
    }

    // -------------------------------------------------------------------------
    // 1. Hardware Barcode & NFC Scanner Listener (< 35ms)
    // -------------------------------------------------------------------------
    window.addEventListener('keydown', function (e) {
        const now = Date.now();
        const delta = now - lastKeyTimestamp;
        lastKeyTimestamp = now;

        // Hotkey Routing (F2, F4, F8, F12, Escape)
        if (e.key === 'F2') {
            e.preventDefault();
            const input = document.getElementById('barcodeOmniInput');
            if (input) input.focus();
            return;
        }

        if (e.key === 'F4') {
            e.preventDefault();
            openCustomerModal();
            return;
        }

        if (e.key === 'F8') {
            e.preventDefault();
            openHoldModal();
            return;
        }

        if (e.key === 'F12') {
            e.preventDefault();
            openTenderModal();
            return;
        }

        if (e.key === 'Escape') {
            dismissAllModals();
            return;
        }

        // Check if user is typing into an active text input or modal form
        const isFocusedOnInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);

        // Hardware scanners burst keystrokes with ultra-low timing
        if (delta < BARCODE_MAX_INTER_KEY_MS || barcodeBuffer.length === 0) {
            if (e.key === 'Enter') {
                if (barcodeBuffer.length >= 3) {
                    // Valid hardware scanner payload received
                    e.preventDefault();
                    const scannedCode = barcodeBuffer.trim();
                    barcodeBuffer = '';
                    handleHardwareScan(scannedCode);
                    return;
                }
                barcodeBuffer = '';
            } else if (e.key.length === 1) {
                barcodeBuffer += e.key;
            }
        } else {
            // Delta too large: clear buffer, assume manual typing unless single character start
            if (e.key.length === 1) {
                barcodeBuffer = e.key;
            } else {
                barcodeBuffer = '';
            }
        }
    });

    async function handleHardwareScan(barcode) {
        showToast(`Scanning: ${barcode}...`);
        try {
            const res = await fetch(`/api/pos/scan?barcode=${encodeURIComponent(barcode)}`);
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                if (data.type === 'customer_attached') {
                    showToast(`Customer Attached: ${data.customer.name}`);
                } else {
                    showToast(`Added: ${data.product.name}`);
                }
                updateCartUI(data.cart);
            } else {
                showToast(data.message || 'Item not found.', true);
            }
        } catch (err) {
            console.error('Scan error:', err);
            showToast('Scan lookup error.', true);
        }
    }

    // -------------------------------------------------------------------------
    // 2. Pluggable Workspace Canvas Swapping
    // -------------------------------------------------------------------------
    function initCanvasSwitcher() {
        const tabButtons = document.querySelectorAll('.workspace-tab-btn, .btn-canvas-toggle');
        const panes = document.querySelectorAll('.workspace-pane, .canvas-view');

        tabButtons.forEach(btn => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                let targetSelector = btn.getAttribute('data-target');
                let canvasId = btn.getAttribute('data-canvas');
                
                if (!targetSelector && canvasId) {
                    targetSelector = (canvasId === 'default-retail') 
                        ? '#canvas-default-retail' 
                        : `#canvas-addon-${canvasId.replace(/^addon-/, '')}`;
                }
                if (!canvasId && targetSelector) {
                    canvasId = targetSelector.replace('#canvas-addon-', '').replace('#canvas-', '');
                }

                // Update button active classes
                tabButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // Toggle pane visibility
                panes.forEach(pane => {
                    pane.classList.remove('active');
                    pane.classList.add('d-none');
                });

                const targetPane = targetSelector ? document.querySelector(targetSelector) : null;
                if (targetPane) {
                    targetPane.classList.remove('d-none');
                    targetPane.classList.add('active');
                    targetPane.style.display = '';

                    // Notify addon canvas if it has an onActivate hook
                    window.dispatchEvent(new CustomEvent('pos:workspace_changed', { 
                        detail: { target: targetSelector, canvasId: canvasId } 
                    }));
                    window.dispatchEvent(new CustomEvent('openpos:canvas_switched', { 
                        detail: { canvasId: canvasId } 
                    }));
                }
            });
        });

        // Initialize active workspace pane matching active button or defaultCanvas
        const activeBtn = document.querySelector('.workspace-tab-btn.active, .btn-canvas-toggle.active');
        if (activeBtn) {
            let targetSelector = activeBtn.getAttribute('data-target');
            if (!targetSelector) {
                const canvasId = activeBtn.getAttribute('data-canvas');
                if (canvasId) {
                    targetSelector = (canvasId === 'default-retail') 
                        ? '#canvas-default-retail' 
                        : `#canvas-addon-${canvasId.replace(/^addon-/, '')}`;
                }
            }
            if (targetSelector) {
                const targetPane = document.querySelector(targetSelector);
                if (targetPane) {
                    panes.forEach(p => {
                        if (p !== targetPane) {
                            p.classList.remove('active');
                            p.classList.add('d-none');
                        }
                    });
                    targetPane.classList.remove('d-none');
                    targetPane.classList.add('active');
                }
            }
        }
    }

    function switchCanvas(canvasId) {
        const cleanId = canvasId.replace(/^addon-/, '');
        const targetBtn = document.querySelector(
            `[data-target="#canvas-addon-${cleanId}"], [data-target="#canvas-${canvasId}"], [data-canvas="${canvasId}"], [data-canvas="${cleanId}"]`
        );
        if (targetBtn) {
            targetBtn.click();
        }
    }

    // -------------------------------------------------------------------------
    // 3. Cart State Synchronization & UI Rendering
    // -------------------------------------------------------------------------
    async function fetchCart() {
        try {
            const res = await fetch('/api/pos/cart');
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
            }
        } catch (err) {
            console.error('Failed to fetch active cart:', err);
        }
    }

    function updateCartUI(cart) {
        if (!cart) return;
        activeCart = cart;

        // Item count
        const totalItems = (cart.items || []).reduce((acc, i) => acc + (i.quantity || 1), 0);
        const countBadge = document.getElementById('ticketItemCount');
        if (countBadge) countBadge.textContent = `${totalItems} ${totalItems === 1 ? 'Item' : 'Items'}`;

        // Customer Pill State
        const labelEl = document.getElementById('customerPillLabel');
        const attachBtn = document.getElementById('btnOpenCustomerModal');
        const activeBadge = document.getElementById('customerActiveBadge');
        const custNameEl = document.getElementById('custBadgeName');
        const custCreditEl = document.getElementById('custBadgeCredit');

        if (cart.customer_id) {
            if (attachBtn) attachBtn.style.display = 'none';
            if (activeBadge) activeBadge.style.display = 'flex';
            if (custNameEl) custNameEl.textContent = cart.customer_name || 'Customer';
            if (custCreditEl) custCreditEl.textContent = `Credit: $${(cart.customer_credit || 0).toFixed(2)}`;
        } else {
            if (attachBtn) attachBtn.style.display = 'inline-flex';
            if (activeBadge) activeBadge.style.display = 'none';
        }

        // Render Lines
        const listEl = document.getElementById('ticketLinesList');
        const emptyEl = document.getElementById('ticketEmptyState');

        if (!cart.items || cart.items.length === 0) {
            if (listEl) listEl.style.display = 'none';
            if (emptyEl) emptyEl.style.display = 'flex';
        } else {
            if (emptyEl) emptyEl.style.display = 'none';
            if (listEl) {
                listEl.style.display = 'flex';
                listEl.innerHTML = cart.items.map(item => {
                    const metaBadges = [];
                    if (item.metadata && typeof item.metadata === 'object') {
                        if (item.metadata.condition) metaBadges.push(item.metadata.condition);
                        if (item.metadata.is_foil) metaBadges.push('FOIL');
                        if (item.metadata.trade_in) metaBadges.push('TRADE-IN');
                    }
                    if (item.sku) metaBadges.push(item.sku);

                    const badgesHtml = metaBadges.length > 0
                        ? `<span class="line-meta-badge">${metaBadges.join(' • ')}</span>`
                        : '';

                    const lineTotal = ((item.price - (item.discount || 0)) * item.quantity).toFixed(2);

                    return `
                        <div class="ticket-line-card" data-item-id="${item.item_id}">
                            <div class="ticket-line-info">
                                <div class="line-title" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
                                ${badgesHtml}
                                <div class="line-unit-price">$${item.price.toFixed(2)} each</div>
                            </div>
                            <div class="ticket-line-controls">
                                <div class="quantity-stepper">
                                    <button type="button" class="btn-stepper btn-qty-dec" data-id="${item.item_id}">−</button>
                                    <span class="stepper-value">${item.quantity}</span>
                                    <button type="button" class="btn-stepper btn-qty-inc" data-id="${item.item_id}">+</button>
                                </div>
                                <span class="line-total-price">$${lineTotal}</span>
                                <button type="button" class="btn-line-delete" data-id="${item.item_id}" title="Remove Item">✕</button>
                            </div>
                        </div>
                    `;
                }).join('');

                // Wire line controls
                listEl.querySelectorAll('.btn-qty-inc').forEach(b => {
                    b.addEventListener('click', () => modifyItemQty(b.dataset.id, 1));
                });
                listEl.querySelectorAll('.btn-qty-dec').forEach(b => {
                    b.addEventListener('click', () => modifyItemQty(b.dataset.id, -1));
                });
                listEl.querySelectorAll('.btn-line-delete').forEach(b => {
                    b.addEventListener('click', () => removeItem(b.dataset.id));
                });
            }
        }

        // Summary Calculations
        const subtotalEl = document.getElementById('sumSubtotal');
        if (subtotalEl) subtotalEl.textContent = `$${(cart.subtotal || 0).toFixed(2)}`;

        const discountRow = document.getElementById('sumDiscountRow');
        const discountEl = document.getElementById('sumDiscount');
        if (cart.discount_total > 0) {
            if (discountRow) discountRow.style.display = 'flex';
            if (discountEl) discountEl.textContent = `-$${cart.discount_total.toFixed(2)}`;
        } else if (discountRow) {
            discountRow.style.display = 'none';
        }

        const creditRow = document.getElementById('sumCreditRow');
        const creditEl = document.getElementById('sumCredit');
        if (cart.credit_applied > 0) {
            if (creditRow) creditRow.style.display = 'flex';
            if (creditEl) creditEl.textContent = `-$${cart.credit_applied.toFixed(2)}`;
        } else if (creditRow) {
            creditRow.style.display = 'none';
        }

        const taxRateEl = document.getElementById('sumTaxRate');
        if (taxRateEl) taxRateEl.textContent = `${((cart.tax_rate || 0.0825) * 100).toFixed(2)}%`;

        const taxEl = document.getElementById('sumTax');
        if (taxEl) taxEl.textContent = `$${(cart.tax_total || 0).toFixed(2)}`;

        const grandTotalEl = document.getElementById('sumGrandTotal');
        const dockAmountEl = document.getElementById('dockTenderAmount');
        const grandTotalFormatted = `$${(cart.grand_total || 0).toFixed(2)}`;

        if (grandTotalEl) grandTotalEl.textContent = grandTotalFormatted;
        if (dockAmountEl) dockAmountEl.textContent = grandTotalFormatted;

        // Auto-scroll ticket lines down to latest item
        const scrollContainer = document.getElementById('ticketLinesScroll');
        if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }

    async function modifyItemQty(itemId, change) {
        if (!activeCart) return;
        const item = activeCart.items.find(i => i.item_id === itemId);
        if (!item) return;

        const newQty = item.quantity + change;
        try {
            const res = await fetch(`/api/pos/cart/item/${itemId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ quantity: newQty })
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
            }
        } catch (err) {
            console.error('Error modifying quantity:', err);
        }
    }

    async function removeItem(itemId) {
        try {
            const res = await fetch(`/api/pos/cart/item/${itemId}`, { method: 'DELETE' });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
            }
        } catch (err) {
            console.error('Error removing item:', err);
        }
    }

    async function clearTicket() {
        if (!activeCart || !activeCart.items || activeCart.items.length === 0) return;
        try {
            const res = await fetch('/api/pos/cart/clear', { method: 'POST' });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
                showToast('Ticket cleared.');
            }
        } catch (err) {
            console.error('Error clearing cart:', err);
        }
    }

    // -------------------------------------------------------------------------
    // 4. Quick Products Grid & Omni-Search Bar
    // -------------------------------------------------------------------------
    async function loadPresetProducts() {
        try {
            const res = await fetch('/api/pos/products');
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                quickProducts = data.products || [];
                renderQuickProducts('ALL');
            }
        } catch (err) {
            console.error('Failed to load preset products:', err);
        }
    }

    function renderQuickProducts(filterCategory = 'ALL') {
        const grid = document.getElementById('quickProductsGrid');
        if (!grid) return;

        const filtered = filterCategory === 'ALL'
            ? quickProducts
            : quickProducts.filter(p => p.category === filterCategory);

        grid.innerHTML = filtered.map(prod => `
            <div class="product-quick-card" data-sku="${prod.sku}">
                <div class="prod-card-top">
                    <span class="prod-card-icon">${prod.icon || '🏷️'}</span>
                    <span class="prod-card-price">$${prod.price.toFixed(2)}</span>
                </div>
                <div class="prod-card-name">${escapeHtml(prod.name)}</div>
            </div>
        `).join('');

        grid.querySelectorAll('.product-quick-card').forEach(card => {
            card.addEventListener('click', () => {
                const sku = card.dataset.sku;
                const prod = quickProducts.find(p => p.sku === sku);
                if (prod) {
                    addItemToTicket(prod.name, prod.price, 1, prod.sku, prod.taxable);
                }
            });
        });
    }

    async function addItemToTicket(name, price, quantity = 1, sku = '', taxable = true, metadata = {}) {
        try {
            const res = await fetch('/api/pos/cart/item', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, price, quantity, sku, taxable, metadata })
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
                showToast(`Added: ${name}`);
            } else {
                showToast(data.message || 'Error adding item.', true);
            }
        } catch (err) {
            console.error('Error adding item:', err);
            showToast('Failed to add item.', true);
        }
    }

    function initSearchAndCategories() {
        const omniInput = document.getElementById('barcodeOmniInput');
        const btnClear = document.getElementById('btnClearSearch');

        if (omniInput) {
            omniInput.addEventListener('input', () => {
                btnClear.style.display = omniInput.value.length > 0 ? 'inline-block' : 'none';
            });

            omniInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && omniInput.value.trim().length > 0) {
                    e.preventDefault();
                    const val = omniInput.value.trim();
                    omniInput.value = '';
                    btnClear.style.display = 'none';
                    handleHardwareScan(val);
                }
            });
        }

        if (btnClear) {
            btnClear.addEventListener('click', () => {
                omniInput.value = '';
                btnClear.style.display = 'none';
                omniInput.focus();
            });
        }

        // Category Tabs
        const catTabs = document.querySelectorAll('.cat-pill');
        catTabs.forEach(tab => {
            tab.addEventListener('click', function () {
                catTabs.forEach(t => t.classList.remove('active'));
                this.classList.add('active');
                const cat = this.dataset.category;
                if (cat === 'CUSTOM') {
                    const manualBar = document.getElementById('manualEntryBar');
                    if (manualBar) {
                        manualBar.scrollIntoView({ behavior: 'smooth' });
                        document.getElementById('manualItemName')?.focus();
                    }
                } else {
                    renderQuickProducts(cat);
                }
            });
        });

        // Manual Item Entry
        const btnAddManual = document.getElementById('btnAddManualItem');
        if (btnAddManual) {
            btnAddManual.addEventListener('click', () => {
                const nameInput = document.getElementById('manualItemName');
                const priceInput = document.getElementById('manualItemPrice');
                const taxInput = document.getElementById('manualItemTaxable');

                const name = (nameInput.value || 'Custom Item').trim();
                const price = parseFloat(priceInput.value) || 0.0;
                const taxable = taxInput.checked;

                if (price < 0) {
                    showToast('Price cannot be negative.', true);
                    return;
                }

                addItemToTicket(name, price, 1, 'CUSTOM', taxable);
                nameInput.value = '';
                priceInput.value = '';
            });
        }
    }

    // -------------------------------------------------------------------------
    // 5. Customer Attachment & NFC Tap Modal (F4)
    // -------------------------------------------------------------------------
    function openCustomerModal() {
        const modal = document.getElementById('customerModalBackdrop');
        if (modal) {
            modal.style.display = 'flex';
            const input = document.getElementById('customerSearchInput');
            if (input) {
                input.value = '';
                input.focus();
            }
            document.getElementById('customerSearchResults').innerHTML = '';
        }
    }

    function closeCustomerModal() {
        const modal = document.getElementById('customerModalBackdrop');
        if (modal) modal.style.display = 'none';
    }

    async function searchCustomers() {
        const input = document.getElementById('customerSearchInput');
        const term = input?.value.trim() || '';
        if (!term) return;

        try {
            // Use core customer search endpoint
            const res = await fetch(`/api/core/customers?search=${encodeURIComponent(term)}&per_page=10`);
            const data = await res.json();
            const resultsEl = document.getElementById('customerSearchResults');
            if (!resultsEl) return;

            if (res.ok && data.customers && data.customers.length > 0) {
                resultsEl.innerHTML = data.customers.map(c => `
                    <div class="customer-result-card" data-id="${c.id}" data-name="${escapeHtml(c.name)}" data-credit="${c.store_credit_balance}">
                        <div>
                            <div class="res-cust-name">${escapeHtml(c.name)}</div>
                            <div class="res-cust-sub">${c.phone || 'No phone'} • ${c.email || 'No email'}</div>
                        </div>
                        <div class="res-cust-credit">$${(c.store_credit_balance || 0).toFixed(2)}</div>
                    </div>
                `).join('');

                resultsEl.querySelectorAll('.customer-result-card').forEach(card => {
                    card.addEventListener('click', () => {
                        attachCustomerById(card.dataset.id);
                    });
                });
            } else {
                resultsEl.innerHTML = `
                    <div class="p-3 text-muted text-center">
                        No customer found matching "${escapeHtml(term)}".
                    </div>
                `;
            }
        } catch (err) {
            console.error('Customer search error:', err);
        }
    }

    async function attachCustomerById(customerIdOrIdentifier) {
        try {
            const res = await fetch('/api/pos/cart/customer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ identifier: customerIdOrIdentifier })
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
                closeCustomerModal();
                showToast(`Customer Attached: ${data.customer.name}`);
            } else {
                showToast(data.message || 'Failed to attach customer.', true);
            }
        } catch (err) {
            console.error('Error attaching customer:', err);
            showToast('Error attaching customer.', true);
        }
    }

    async function detachCustomer() {
        try {
            const res = await fetch('/api/pos/cart/customer', { method: 'DELETE' });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
                showToast('Customer detached.');
            }
        } catch (err) {
            console.error('Error detaching customer:', err);
        }
    }

    // -------------------------------------------------------------------------
    // 6. Tender & Split Payment Modal (F12)
    // -------------------------------------------------------------------------
    function openTenderModal() {
        if (!activeCart || !activeCart.items || activeCart.items.length === 0) {
            showToast('Cannot tender an empty ticket.', true);
            return;
        }

        const modal = document.getElementById('tenderModalBackdrop');
        if (!modal) return;

        modal.style.display = 'flex';

        // Set Total Due Display
        const totalDue = activeCart.grand_total || 0;
        document.getElementById('tenderTotalDueDisplay').textContent = `$${totalDue.toFixed(2)}`;

        // Customer Store Credit Section
        const creditSec = document.getElementById('tenderCreditSection');
        const creditBalanceEl = document.getElementById('tenderCustomerCreditBalance');
        const creditInput = document.getElementById('tenderCreditInput');

        if (activeCart.customer_id && activeCart.customer_credit > 0) {
            if (creditSec) creditSec.style.display = 'block';
            if (creditBalanceEl) creditBalanceEl.textContent = `Balance: $${activeCart.customer_credit.toFixed(2)}`;
            if (creditInput) creditInput.value = activeCart.credit_applied > 0 ? activeCart.credit_applied.toFixed(2) : '';
        } else {
            if (creditSec) creditSec.style.display = 'none';
            if (creditInput) creditInput.value = '';
        }

        // Reset tender inputs
        const cashInput = document.getElementById('tenderCashInput');
        const cardInput = document.getElementById('tenderCardInput');
        if (cashInput) cashInput.value = '';
        if (cardInput) cardInput.value = '';

        recalcTenderTotals();

        // Focus Cash Input by default
        if (cashInput) cashInput.focus();
    }

    function closeTenderModal() {
        const modal = document.getElementById('tenderModalBackdrop');
        if (modal) modal.style.display = 'none';
    }

    function recalcTenderTotals() {
        if (!activeCart) return;
        const totalDue = activeCart.grand_total || 0;

        const creditVal = parseFloat(document.getElementById('tenderCreditInput')?.value) || 0.0;
        const cashVal = parseFloat(document.getElementById('tenderCashInput')?.value) || 0.0;
        const cardVal = parseFloat(document.getElementById('tenderCardInput')?.value) || 0.0;

        const totalTendered = creditVal + cashVal + cardVal;
        document.getElementById('tenderTotalTenderedDisplay').textContent = `$${totalTendered.toFixed(2)}`;

        const balanceCard = document.getElementById('tenderBalanceCard');
        const balanceLabel = document.getElementById('tenderBalanceLabel');
        const balanceValEl = document.getElementById('tenderBalanceDisplay');
        const submitBtn = document.getElementById('btnSubmitCheckout');

        if (totalTendered >= totalDue) {
            // Covered or Change Due
            const nonCash = creditVal + cardVal;
            const cashRequired = Math.max(0, totalDue - nonCash);
            const changeDue = Math.max(0, cashVal - cashRequired);

            if (balanceLabel) balanceLabel.textContent = 'CHANGE DUE';
            if (balanceValEl) {
                balanceValEl.textContent = `$${changeDue.toFixed(2)}`;
                balanceValEl.style.color = '#58a6ff';
            }
            if (balanceCard) {
                balanceCard.style.backgroundColor = 'rgba(88, 166, 255, 0.12)';
                balanceCard.style.borderColor = 'rgba(88, 166, 255, 0.4)';
            }
            if (submitBtn) submitBtn.disabled = false;
        } else {
            // Still underpaid
            const remaining = totalDue - totalTendered;
            if (balanceLabel) balanceLabel.textContent = 'REMAINING DUE';
            if (balanceValEl) {
                balanceValEl.textContent = `$${remaining.toFixed(2)}`;
                balanceValEl.style.color = '#f85149';
            }
            if (balanceCard) {
                balanceCard.style.backgroundColor = 'rgba(248, 81, 73, 0.12)';
                balanceCard.style.borderColor = 'rgba(248, 81, 73, 0.4)';
            }
            if (submitBtn) submitBtn.disabled = true;
        }
    }

    async function submitCheckout() {
        if (!activeCart) return;
        const submitBtn = document.getElementById('btnSubmitCheckout');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Processing...';
        }

        const creditVal = parseFloat(document.getElementById('tenderCreditInput')?.value) || 0.0;
        const cashVal = parseFloat(document.getElementById('tenderCashInput')?.value) || 0.0;
        const cardVal = parseFloat(document.getElementById('tenderCardInput')?.value) || 0.0;
        const notes = document.getElementById('tenderOrderNotes')?.value || '';

        const payload = {
            tenders: {
                cash: cashVal,
                card: cardVal,
                store_credit: creditVal
            },
            notes: notes
        };

        try {
            const res = await fetch('/api/pos/cart/checkout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (res.ok && data.status === 'success') {
                closeTenderModal();
                showReceiptModal(data.receipt, data.change_due);
                // Refresh cart state to empty
                await fetchCart();
            } else {
                showToast(data.message || 'Checkout failed.', true);
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = '✓ Complete Transaction';
                }
            }
        } catch (err) {
            console.error('Checkout error:', err);
            showToast('Network error during checkout.', true);
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = '✓ Complete Transaction';
            }
        }
    }

    function showReceiptModal(receipt, changeDue) {
        const modal = document.getElementById('receiptModalBackdrop');
        if (!modal) return;

        document.getElementById('receiptOrderId').textContent = receipt.order_id;
        const changeBox = document.getElementById('receiptChangeBox');
        if (changeDue > 0) {
            if (changeBox) changeBox.style.display = 'block';
            document.getElementById('receiptChangeAmount').textContent = `$${changeDue.toFixed(2)}`;
        } else if (changeBox) {
            changeBox.style.display = 'none';
        }

        const detailsEl = document.getElementById('receiptDetailsCard');
        if (detailsEl) {
            detailsEl.innerHTML = `
                <div class="summary-line">
                    <span>Total Amount:</span>
                    <span class="font-mono font-bold">$${receipt.grand_total.toFixed(2)}</span>
                </div>
                <div class="summary-line">
                    <span>Cash Tendered:</span>
                    <span class="font-mono">$${(receipt.tenders?.cash || 0).toFixed(2)}</span>
                </div>
                <div class="summary-line">
                    <span>Card Tendered:</span>
                    <span class="font-mono">$${(receipt.tenders?.card || 0).toFixed(2)}</span>
                </div>
                <div class="summary-line">
                    <span>Store Credit Tendered:</span>
                    <span class="font-mono">$${(receipt.tenders?.store_credit || 0).toFixed(2)}</span>
                </div>
            `;
        }

        modal.style.display = 'flex';
    }

    // -------------------------------------------------------------------------
    // 7. Hold & Recall Orders Modal (F8)
    // -------------------------------------------------------------------------
    function openHoldModal() {
        const modal = document.getElementById('holdModalBackdrop');
        if (!modal) return;
        modal.style.display = 'flex';
        loadHeldOrdersList();
    }

    function closeHoldModal() {
        const modal = document.getElementById('holdModalBackdrop');
        if (modal) modal.style.display = 'none';
    }

    async function loadHeldOrdersList() {
        try {
            const res = await fetch('/api/pos/cart/holds');
            const data = await res.json();
            const listEl = document.getElementById('heldOrdersList');
            const badgeEl = document.getElementById('heldOrdersCountBadge');

            if (res.ok && data.held_orders) {
                heldOrdersCount = data.held_orders.length;
                if (badgeEl) {
                    badgeEl.textContent = heldOrdersCount;
                    badgeEl.style.display = heldOrdersCount > 0 ? 'inline-block' : 'none';
                }

                if (listEl) {
                    if (heldOrdersCount === 0) {
                        listEl.innerHTML = '<div class="p-3 text-muted text-center">No tickets are currently parked.</div>';
                    } else {
                        listEl.innerHTML = data.held_orders.map(h => `
                            <div class="held-order-card">
                                <div>
                                    <div class="held-id">${h.hold_id} — ${escapeHtml(h.customer_name)}</div>
                                    <div class="held-meta">${h.item_count} items • ${h.notes || 'No notes'}</div>
                                </div>
                                <div style="display: flex; align-items: center; gap: 0.75rem;">
                                    <span class="held-total">$${h.grand_total.toFixed(2)}</span>
                                    <button type="button" class="btn btn-sm btn-primary btn-resume-hold" data-id="${h.hold_id}">Resume</button>
                                </div>
                            </div>
                        `).join('');

                        listEl.querySelectorAll('.btn-resume-hold').forEach(b => {
                            b.addEventListener('click', () => resumeHeldOrder(b.dataset.id));
                        });
                    }
                }
            }
        } catch (err) {
            console.error('Error fetching held orders:', err);
        }
    }

    async function holdActiveTicket() {
        const notesInput = document.getElementById('holdNotesInput');
        const notes = notesInput?.value.trim() || '';

        try {
            const res = await fetch('/api/pos/cart/hold', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notes })
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
                if (notesInput) notesInput.value = '';
                showToast(`Ticket Parked (${data.hold.hold_id})`);
                closeHoldModal();
                loadHeldOrdersList();
            } else {
                showToast(data.message || 'Cannot hold ticket.', true);
            }
        } catch (err) {
            console.error('Error holding ticket:', err);
        }
    }

    async function resumeHeldOrder(holdId) {
        try {
            const res = await fetch(`/api/pos/cart/resume/${holdId}`, { method: 'POST' });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
                closeHoldModal();
                showToast(`Resumed Ticket ${holdId}`);
                loadHeldOrdersList();
            } else {
                showToast(data.message || 'Cannot resume ticket.', true);
            }
        } catch (err) {
            console.error('Error resuming held order:', err);
        }
    }

    // -------------------------------------------------------------------------
    // 8. Order Discount Modal
    // -------------------------------------------------------------------------
    function openDiscountModal() {
        const modal = document.getElementById('discountModalBackdrop');
        if (modal) modal.style.display = 'flex';
    }

    function closeDiscountModal() {
        const modal = document.getElementById('discountModalBackdrop');
        if (modal) modal.style.display = 'none';
    }

    async function applyOrderDiscount(amount) {
        try {
            const res = await fetch('/api/pos/cart/discount', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: parseFloat(amount) || 0.0 })
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                updateCartUI(data.cart);
                closeDiscountModal();
                showToast('Discount applied.');
            }
        } catch (err) {
            console.error('Error applying discount:', err);
        }
    }

    // -------------------------------------------------------------------------
    // Modal Helpers & Escape Handling
    // -------------------------------------------------------------------------
    function dismissAllModals() {
        closeCustomerModal();
        closeTenderModal();
        closeHoldModal();
        closeDiscountModal();
        const receiptModal = document.getElementById('receiptModalBackdrop');
        if (receiptModal) receiptModal.style.display = 'none';
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // -------------------------------------------------------------------------
    // Initialization & Event Binding
    // -------------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        initCanvasSwitcher();
        fetchCart();
        loadPresetProducts();
        initSearchAndCategories();
        loadHeldOrdersList();

        // Customer Pill Button
        document.getElementById('btnOpenCustomerModal')?.addEventListener('click', openCustomerModal);
        document.getElementById('btnCloseCustomerModal')?.addEventListener('click', closeCustomerModal);
        document.getElementById('btnDismissCustomerModal')?.addEventListener('click', closeCustomerModal);
        document.getElementById('btnSearchCustomer')?.addEventListener('click', searchCustomers);
        document.getElementById('customerSearchInput')?.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                searchCustomers();
            }
        });
        document.getElementById('btnDetachCustomer')?.addEventListener('click', detachCustomer);

        // Simulate NFC Tap Button
        document.getElementById('btnSimulateNfcTap')?.addEventListener('click', () => {
            handleHardwareScan('04A1B2C3D4E5F6');
            closeCustomerModal();
        });

        // Ticket Controls
        document.getElementById('btnClearTicket')?.addEventListener('click', clearTicket);
        document.getElementById('btnHoldTicket')?.addEventListener('click', openHoldModal);
        document.getElementById('btnOrderDiscount')?.addEventListener('click', openDiscountModal);
        document.getElementById('btnOpenTenderModal')?.addEventListener('click', openTenderModal);
        document.getElementById('btnEditDiscount')?.addEventListener('click', openDiscountModal);
        document.getElementById('btnClearCredit')?.addEventListener('click', () => {
            fetch('/api/pos/cart/credit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: 0.0 })
            }).then(r => r.json()).then(d => updateCartUI(d.cart));
        });

        // Tender Modal Controls
        document.getElementById('btnCloseTenderModal')?.addEventListener('click', closeTenderModal);
        document.getElementById('tenderCashInput')?.addEventListener('input', recalcTenderTotals);
        document.getElementById('tenderCardInput')?.addEventListener('input', recalcTenderTotals);
        document.getElementById('tenderCreditInput')?.addEventListener('input', recalcTenderTotals);

        document.getElementById('btnApplyMaxCredit')?.addEventListener('click', () => {
            if (!activeCart) return;
            const maxCredit = Math.min(activeCart.customer_credit || 0, activeCart.grand_total || 0);
            const input = document.getElementById('tenderCreditInput');
            if (input) input.value = maxCredit.toFixed(2);
            recalcTenderTotals();
        });

        document.getElementById('btnExactCash')?.addEventListener('click', () => {
            if (!activeCart) return;
            const creditVal = parseFloat(document.getElementById('tenderCreditInput')?.value) || 0.0;
            const cardVal = parseFloat(document.getElementById('tenderCardInput')?.value) || 0.0;
            const remaining = Math.max(0, (activeCart.grand_total || 0) - creditVal - cardVal);
            const input = document.getElementById('tenderCashInput');
            if (input) input.value = remaining.toFixed(2);
            recalcTenderTotals();
        });

        document.getElementById('btnRemainingCard')?.addEventListener('click', () => {
            if (!activeCart) return;
            const creditVal = parseFloat(document.getElementById('tenderCreditInput')?.value) || 0.0;
            const cashVal = parseFloat(document.getElementById('tenderCashInput')?.value) || 0.0;
            const remaining = Math.max(0, (activeCart.grand_total || 0) - creditVal - cashVal);
            const input = document.getElementById('tenderCardInput');
            if (input) input.value = remaining.toFixed(2);
            recalcTenderTotals();
        });

        document.querySelectorAll('.btn-cash-chip').forEach(chip => {
            chip.addEventListener('click', function () {
                const add = parseFloat(this.dataset.cash) || 0;
                const input = document.getElementById('tenderCashInput');
                if (input) {
                    const current = parseFloat(input.value) || 0.0;
                    input.value = (current + add).toFixed(2);
                    recalcTenderTotals();
                }
            });
        });

        document.getElementById('btnSubmitCheckout')?.addEventListener('click', submitCheckout);

        // Hold Modal Controls
        document.getElementById('btnCloseHoldModal')?.addEventListener('click', closeHoldModal);
        document.getElementById('btnDismissHoldModal')?.addEventListener('click', closeHoldModal);
        document.getElementById('btnConfirmHold')?.addEventListener('click', holdActiveTicket);

        // Discount Modal Controls
        document.getElementById('btnCloseDiscountModal')?.addEventListener('click', closeDiscountModal);
        document.getElementById('btnApplyDiscount')?.addEventListener('click', () => {
            const amt = document.getElementById('orderDiscountAmount')?.value || 0;
            applyOrderDiscount(amt);
        });
        document.getElementById('btnRemoveDiscount')?.addEventListener('click', () => {
            applyOrderDiscount(0);
        });

        // Receipt Modal Controls
        document.getElementById('btnNewSale')?.addEventListener('click', () => {
            dismissAllModals();
            document.getElementById('barcodeOmniInput')?.focus();
        });

        // Addon Inter-Process Event Listeners
        window.addEventListener('openpos:item_added', (e) => {
            if (e.detail?.cart) {
                updateCartUI(e.detail.cart);
            } else {
                fetchCart();
            }
        });

        window.addEventListener('openpos:refresh_cart', () => {
            fetchCart();
        });
    });

})();
