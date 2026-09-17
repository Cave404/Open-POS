/**
 * static/js/setup_wizard.js
 * ==========================
 * Client-side state machine and navigation controller for Open-POS Setup Wizard.
 * Handles:
 *  - Prerequisite scanning & automatic dependency installer
 *  - Store identity & logo upload
 *  - Security PIN configuration
 *  - Database engine toggle (SQLite / PostgreSQL)
 *  - Addon selection & catalog refresh
 *  - Cryptographic roundtrip & button unlocking for Step 5 & 6
 *  - Desktop Save-As dialog bridge & printable recovery key sheet
 *  - Setup completion & supervisor launch
 */

let currentStep = 1;
let prereqPassed = false;
let selectedEngine = 'sqlite';
let generatedCrypto = {
    fernet_key: '',
    secret_key: '',
    recovery_token: ''
};

// ---------------------------------------------------------------------------
// Step Navigation Helper
// ---------------------------------------------------------------------------
function showStep(step) {
    currentStep = step;
    for (let i = 1; i <= 7; i++) {
        const card = document.getElementById(`stage${i}`);
        const ind = document.getElementById(`stepIndicator${i}`);
        if (card) {
            card.classList.toggle('active', i === step);
            if (i === step) {
                const stepContent = card.querySelector('.wizard-step-content');
                if (stepContent) stepContent.scrollTop = 0;
            }
        }
        if (ind) {
            ind.classList.remove('active', 'completed');
            if (i === step) ind.classList.add('active');
            else if (i < step) ind.classList.add('completed');
        }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Step 5 re-entry guard: ensure Initialize Encryption button resets to active
    if (step === 5) {
        const btnNext5 = document.getElementById('btnNext5');
        if (btnNext5) {
            btnNext5.disabled = false;
            btnNext5.removeAttribute('disabled');
            btnNext5.style.opacity = '1';
            btnNext5.style.pointerEvents = 'auto';
        }
    }

    // Step 6 re-entry guard: if crypto keys were already generated on a prior pass,
    // auto-populate displays and enable the Next button without re-hitting the backend.
    if (step === 6 && generatedCrypto.fernet_key) {
        const nextBtn = document.getElementById('btnNext6');
        if (nextBtn) {
            nextBtn.disabled = false;
            nextBtn.removeAttribute('disabled');
            nextBtn.style.opacity = '1';
            nextBtn.style.pointerEvents = 'auto';
        }
        const roundtripEl = document.getElementById('dispRoundtripStatus');
        if (roundtripEl && roundtripEl.textContent !== '✓ Verified & Decryptable') {
            roundtripEl.textContent = '✓ Verified & Decryptable';
            roundtripEl.style.color = 'var(--wizard-success)';
        }
        const dispFernet = document.getElementById('dispFernetKey');
        if (dispFernet && !dispFernet.textContent.includes('Encrypted')) {
            dispFernet.textContent = generatedCrypto.fernet_key.substring(0, 16) + '... (Encrypted)';
        }
        const dispSecret = document.getElementById('dispSecretKey');
        if (dispSecret && !dispSecret.textContent.includes('...')) {
            dispSecret.textContent = generatedCrypto.secret_key.substring(0, 16) + '...';
        }
        const dispToken = document.getElementById('dispRecoveryToken');
        if (dispToken && !dispToken.textContent) {
            dispToken.textContent = generatedCrypto.recovery_token;
        }
    }
}

let wizardCatalogLoaded = false;
async function loadWizardAddons(forceRefresh = false) {
    if (wizardCatalogLoaded && !forceRefresh) return;
    const container = document.getElementById('wizardAddonsContainer');
    if (!container) return;

    const btnRefresh = document.getElementById('btnRefreshCatalog');
    const refreshIcon = document.getElementById('refreshCatalogIcon');
    if (btnRefresh) {
        btnRefresh.disabled = true;
    }
    if (refreshIcon) {
        refreshIcon.style.display = 'inline-block';
        refreshIcon.style.animation = 'spin 1s linear infinite';
    }

    if (forceRefresh) {
        container.innerHTML = `
            <div style="text-align: center; color: var(--wizard-muted); padding: 24px; font-size: 13px;">
                <span>⏳ Fetching latest catalog extensions...</span>
            </div>
        `;
    }

    try {
        const url = forceRefresh ? '/api/addons/catalog?refresh=1' : '/api/addons/catalog';
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const list = await res.json();
        wizardCatalogLoaded = true;

        if (!list || list.length === 0) {
            container.innerHTML = `
                <div style="background: rgba(255,255,255,0.02); border: 1px dashed var(--wizard-border, #2b3245); border-radius: 8px; padding: 20px; text-align: center; color: var(--wizard-muted, #94a3b8); font-size: 13px;">
                    No remote extensions currently available or device is offline. You can install addons at any time from System Manager.
                </div>
            `;
            return;
        }

        container.innerHTML = '';
        list.forEach(addon => {
            const row = document.createElement('label');
            row.style.cssText = 'display: flex; align-items: flex-start; gap: 14px; background: rgba(255,255,255,0.03); border: 1px solid var(--wizard-border, #2b3245); border-radius: 8px; padding: 14px 16px; cursor: pointer; transition: border-color 0.15s;';
            row.onmouseover = () => row.style.borderColor = '#3b82f6';
            row.onmouseout = () => row.style.borderColor = 'var(--wizard-border, #2b3245)';

            const chk = document.createElement('input');
            chk.type = 'checkbox';
            chk.className = 'wizard-addon-checkbox';
            chk.value = addon.id;
            chk.dataset.name = addon.name || addon.id;
            chk.style.cssText = 'margin-top: 3px; width: 18px; height: 18px; accent-color: #3b82f6; cursor: pointer;';

            const info = document.createElement('div');
            info.style.cssText = 'flex: 1;';
            info.innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                    <strong style="color: #ffffff; font-size: 14px;">${addon.name || addon.id}</strong>
                    <span style="font-size: 11px; background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 4px; color: #94a3b8;">v${addon.version || '1.0.0'}</span>
                    ${addon.requires_db ? '<span style="font-size: 11px; background: rgba(59,130,246,0.15); color: #60a5fa; padding: 2px 6px; border-radius: 4px;">Database Required</span>' : ''}
                </div>
                <div style="font-size: 12px; color: var(--wizard-muted, #94a3b8); line-height: 1.4;">${addon.description || 'No description provided.'}</div>
                <div style="font-size: 11px; color: #64748b; margin-top: 4px;">by ${addon.author || 'Open-POS Community'}</div>
            `;

            row.appendChild(chk);
            row.appendChild(info);
            container.appendChild(row);
        });
    } catch (err) {
        console.warn('loadWizardAddons error:', err);
        container.innerHTML = `
            <div style="background: rgba(255,255,255,0.02); border: 1px dashed var(--wizard-border, #2b3245); border-radius: 8px; padding: 20px; text-align: center; color: var(--wizard-muted, #94a3b8); font-size: 13px;">
                Offline mode: Online addon catalog unavailable. You can install extensions later from System Manager.
            </div>
        `;
    } finally {
        if (btnRefresh) {
            btnRefresh.disabled = false;
        }
        if (refreshIcon) {
            refreshIcon.style.animation = 'none';
        }
    }
}

// ---------------------------------------------------------------------------
// 1. Prerequisites Scanner
// ---------------------------------------------------------------------------
async function scanPrerequisites() {
    const listEl = document.getElementById('prereqList');
    if (!listEl) return;
    listEl.innerHTML = '<div style="text-align: center; color: var(--wizard-muted); padding: 24px;">Scanning runtime environment...</div>';
    const next1 = document.getElementById('btnNext1');
    if (next1) next1.disabled = true;

    try {
        const res = await fetch('/api/setup/prerequisites');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        prereqPassed = data.all_passed;
        listEl.innerHTML = '';

        data.checks.forEach(c => {
            const item = document.createElement('div');
            item.className = 'prereq-item';
            
            let badgeClass = c.status ? 'prereq-pass' : (c.required ? 'prereq-fail' : 'prereq-opt');
            let badgeText = c.status ? '✓ PASSED' : (c.required ? '✗ FAILED' : '⚠ OPTIONAL');

            item.innerHTML = `
                <div class="prereq-info">
                    <h4>${c.name}</h4>
                    <p>${c.detail}</p>
                    ${!c.status && c.upstream_url ? `<div style="margin-top: 4px;"><a href="${c.upstream_url}" target="_blank" style="color: #60a5fa; font-size: 11.5px; text-decoration: underline;">Download from official site &rarr;</a></div>` : ''}
                </div>
                <div class="prereq-badge ${badgeClass}">${badgeText}</div>
            `;
            listEl.appendChild(item);
        });

        const actionArea = document.getElementById('prereqActionArea');
        if (actionArea) {
            actionArea.style.display = (data.has_missing_packages || !prereqPassed) ? 'block' : 'none';
        }

        if (next1) next1.disabled = !prereqPassed;
    } catch (err) {
        listEl.innerHTML = `<div style="color: var(--wizard-danger); padding: 20px;">Failed to scan prerequisites: ${err.message}</div>`;
        if (next1) next1.disabled = true;
    }
}

const btnInstall = document.getElementById('btnInstallDeps');
if (btnInstall) {
    btnInstall.addEventListener('click', async () => {
        const statusEl = document.getElementById('pipInstallStatus');
        btnInstall.disabled = true;
        btnInstall.innerHTML = '<span>⏳</span> Installing Components (pip install -r requirements.txt)...';
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.style.color = 'var(--wizard-warning)';
            statusEl.textContent = 'Executing pip installation... please wait...';
        }

        try {
            const res = await fetch('/api/setup/install_dependencies', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                if (statusEl) {
                    statusEl.textContent = '✓ Dependencies installed successfully! Re-scanning environment...';
                    statusEl.style.color = 'var(--wizard-success)';
                }
                setTimeout(() => {
                    scanPrerequisites();
                }, 1200);
            } else {
                if (statusEl) {
                    statusEl.textContent = 'Installation failed: ' + (data.message || 'Unknown error');
                    statusEl.style.color = 'var(--wizard-danger)';
                }
                btnInstall.disabled = false;
                btnInstall.innerHTML = '<span>📦</span> Retry Installing Components';
            }
        } catch (e) {
            if (statusEl) {
                statusEl.textContent = 'Request failed: ' + e.message;
                statusEl.style.color = 'var(--wizard-danger)';
            }
            btnInstall.disabled = false;
            btnInstall.innerHTML = '<span>📦</span> Retry Installing Components';
        }
    });
}

// ---------------------------------------------------------------------------
// 2. Database Selection Toggle
// ---------------------------------------------------------------------------
const cardSqlite = document.getElementById('cardSqlite');
const cardPostgres = document.getElementById('cardPostgres');
const postgresFields = document.getElementById('postgresFields');

if (cardSqlite && cardPostgres) {
    cardSqlite.addEventListener('click', () => {
        selectedEngine = 'sqlite';
        cardSqlite.classList.add('selected');
        cardPostgres.classList.remove('selected');
        if (postgresFields) postgresFields.style.display = 'none';
    });

    cardPostgres.addEventListener('click', () => {
        selectedEngine = 'postgresql';
        cardPostgres.classList.add('selected');
        cardSqlite.classList.remove('selected');
        if (postgresFields) postgresFields.style.display = 'block';
    });
}

// ---------------------------------------------------------------------------
// 3. Setup Submission & Encryption Engine (Step 5)
// ---------------------------------------------------------------------------
async function executeSetupPersistence() {
    const errorEl = document.getElementById('cryptoErrorMsg');
    if (errorEl) errorEl.style.display = 'none';

    const dispRoundtrip = document.getElementById('dispRoundtripStatus');
    if (dispRoundtrip) {
        dispRoundtrip.textContent = 'Testing encryption roundtrip & database write...';
        dispRoundtrip.style.color = 'var(--wizard-warning)';
    }

    const dispEng = document.getElementById('dispEngine');
    if (dispEng) {
        dispEng.textContent = selectedEngine === 'sqlite' ? 'SQLite (data/db/pos_store.db)' : 'PostgreSQL';
    }

    const payload = {
        store_name: document.getElementById('inputStoreName') ? document.getElementById('inputStoreName').value.trim() : 'Store',
        store_legal_name: document.getElementById('inputLegalName') ? document.getElementById('inputLegalName').value.trim() : '',
        store_location: document.getElementById('inputLocation') ? document.getElementById('inputLocation').value.trim() : '',
        admin_password: document.getElementById('inputAdminPassword') ? document.getElementById('inputAdminPassword').value.trim() : '',
        require_password: document.getElementById('checkRequirePassword') ? document.getElementById('checkRequirePassword').checked : true,
        db_engine: selectedEngine,
        db_host: document.getElementById('inputPgHost') ? document.getElementById('inputPgHost').value.trim() : '',
        db_port: document.getElementById('inputPgPort') ? document.getElementById('inputPgPort').value.trim() : '',
        db_name: document.getElementById('inputPgDb') ? document.getElementById('inputPgDb').value.trim() : '',
        db_user: document.getElementById('inputPgUser') ? document.getElementById('inputPgUser').value.trim() : '',
        db_password: document.getElementById('inputPgPassword') ? document.getElementById('inputPgPassword').value.trim() : ''
    };

    try {
        const res = await fetch('/api/setup/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();

        if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `Setup submission failed (HTTP ${res.status})`);
        }

        generatedCrypto.fernet_key = data.fernet_key;
        generatedCrypto.secret_key = data.secret_key;
        generatedCrypto.recovery_token = data.recovery_token;

        const dispFernet = document.getElementById('dispFernetKey');
        if (dispFernet) dispFernet.textContent = data.fernet_key.substring(0, 16) + '... (Encrypted)';

        const dispSec = document.getElementById('dispSecretKey');
        if (dispSec) dispSec.textContent = data.secret_key.substring(0, 16) + '...';

        if (dispRoundtrip) {
            dispRoundtrip.textContent = '✓ Verified & Decryptable';
            dispRoundtrip.style.color = 'var(--wizard-success)';
        }

        const dispTok = document.getElementById('dispRecoveryToken');
        if (dispTok) dispTok.textContent = data.recovery_token;

        // Immediately unlock Step 6 "View Recovery Key Sheet ->" button
        const nextBtn6 = document.getElementById('btnNext6');
        if (nextBtn6) {
            nextBtn6.disabled = false;
            nextBtn6.removeAttribute('disabled');
            nextBtn6.style.opacity = '1';
            nextBtn6.style.pointerEvents = 'auto';
        }
    } catch (err) {
        if (dispRoundtrip) {
            dispRoundtrip.textContent = '✗ Error';
            dispRoundtrip.style.color = 'var(--wizard-danger)';
        }
        if (errorEl) {
            errorEl.textContent = err.message;
            errorEl.style.display = 'block';
        }
    }
}

// ---------------------------------------------------------------------------
// 4. Logo Upload Handler (Step 2)
// ---------------------------------------------------------------------------
const inputLogo = document.getElementById('inputLogoFile');
if (inputLogo) {
    inputLogo.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        const statusEl = document.getElementById('logoUploadStatus');
        if (!file) return;

        if (statusEl) statusEl.textContent = 'Uploading store logo...';
        const formData = new FormData();
        formData.append('logo', file);

        try {
            const res = await fetch('/api/settings/logo', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (res.ok && data.status === 'success') {
                if (statusEl) {
                    statusEl.textContent = '✓ Logo uploaded and configured.';
                    statusEl.style.color = 'var(--wizard-success)';
                }
            } else {
                if (statusEl) {
                    statusEl.textContent = `Upload failed: ${data.message}`;
                    statusEl.style.color = 'var(--wizard-danger)';
                }
            }
        } catch (err) {
            if (statusEl) {
                statusEl.textContent = `Upload error: ${err.message}`;
                statusEl.style.color = 'var(--wizard-danger)';
            }
        }
    });
}

// ---------------------------------------------------------------------------
// 5. Recovery Key Export & Print
// ---------------------------------------------------------------------------
const btnDownloadRec = document.getElementById('btnDownloadRecoveryFile');
if (btnDownloadRec) {
    btnDownloadRec.addEventListener('click', async () => {
        const storeName = (document.getElementById('inputStoreName') && document.getElementById('inputStoreName').value.trim()) || 'Store';
        const token = generatedCrypto.recovery_token || '';
        const fernet = generatedCrypto.fernet_key || '';

        // Primary: Native Win32 Save-As dialog via pywebview bridge
        if (window.pywebview && window.pywebview.api && window.pywebview.api.save_recovery_file_dialog) {
            try {
                const result = await window.pywebview.api.save_recovery_file_dialog(storeName, token, fernet);
                if (result && result.status === 'success') {
                    const originalText = btnDownloadRec.innerHTML;
                    btnDownloadRec.innerHTML = '<span>✓</span> Saved to Desktop!';
                    btnDownloadRec.style.background = 'var(--wizard-success)';
                    setTimeout(() => { btnDownloadRec.innerHTML = originalText; btnDownloadRec.style.background = ''; }, 2500);
                    return;
                } else if (result && result.status === 'cancelled') {
                    return;
                }
            } catch(e) {
                console.warn('save_recovery_file_dialog error:', e);
            }
        }

        // Browser fallback: redirect to server-side download endpoint
        const qs = `store_name=${encodeURIComponent(storeName)}&recovery_token=${encodeURIComponent(token)}&fernet_key=${encodeURIComponent(fernet)}`;
        window.location.href = `/api/setup/recovery_file?${qs}`;
    });
}

const btnPrintRec = document.getElementById('btnPrintRecoverySheet');
if (btnPrintRec) {
    btnPrintRec.addEventListener('click', () => {
        const storeName = (document.getElementById('inputStoreName') && document.getElementById('inputStoreName').value.trim()) || 'Store';
        const token = generatedCrypto.recovery_token || '';
        const fernet = generatedCrypto.fernet_key || '';

        const printStoreEl = document.getElementById('printStoreName');
        const printDateEl = document.getElementById('printDate');
        const printTokenEl = document.getElementById('printTokenVal');
        const printFernetEl = document.getElementById('printFernetVal');

        if (printStoreEl) printStoreEl.textContent = storeName;
        if (printDateEl) printDateEl.textContent = new Date().toLocaleString();
        if (printTokenEl) printTokenEl.textContent = token;
        if (printFernetEl) printFernetEl.textContent = fernet || 'Configured in data/config/.env';

        window.print();
    });
}

// ---------------------------------------------------------------------------
// 6. Complete Setup & Launch OpenPOS
// ---------------------------------------------------------------------------
const btnFinish = document.getElementById('btnFinishSetup');
if (btnFinish) {
    btnFinish.addEventListener('click', async () => {
        btnFinish.disabled = true;

        // Optional Step 5: Install selected remote addons in sequence with real-time feedback
        const checkedAddons = Array.from(document.querySelectorAll('.wizard-addon-checkbox:checked'));
        if (checkedAddons.length > 0) {
            for (let i = 0; i < checkedAddons.length; i++) {
                const item = checkedAddons[i];
                const aId = item.value;
                const aName = item.dataset.name || aId;
                btnFinish.innerHTML = `<span>⏳</span> Installing ${aName}...`;
                try {
                    await fetch('/api/addons/install_remote', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ addon_id: aId })
                    });
                } catch (ae) {
                    console.warn(`Could not install addon ${aId} during setup:`, ae);
                }
            }
        }

        btnFinish.innerHTML = '<span>⏳</span> Finalizing Setup &amp; Launching OpenPOS...';
        const storeName = (document.getElementById('inputStoreName') && document.getElementById('inputStoreName').value.trim()) || 'Store';

        // Desktop mode: Native clean exit, close window, and spawn detached Start_POS.bat
        if (window.pywebview && window.pywebview.api && window.pywebview.api.finish_and_launch) {
            try {
                await window.pywebview.api.finish_and_launch(storeName);
                return;
            } catch (e) {
                console.warn('Native finish_and_launch error, falling back to HTTP:', e);
            }
        }

        try {
            const res = await fetch('/api/setup/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    completed_by: 'installer',
                    store_name: storeName,
                    restart_supervisor: true
                })
            });
            const data = await res.json();
            if (!res.ok || data.status === 'error') {
                throw new Error(data.message || 'Failed to complete setup');
            }

            // Transition to System Manager
            setTimeout(() => {
                window.location.href = '/manager';
            }, 800);
        } catch (err) {
            alert(`Error finishing setup: ${err.message}`);
            btnFinish.disabled = false;
            btnFinish.innerHTML = '<span>🚀</span> Finish Setup &amp; Launch OpenPOS';
        }
    });
}

// ---------------------------------------------------------------------------
// Stepper Navigation Button Event Listeners
// ---------------------------------------------------------------------------
const btnRescan = document.getElementById('btnRescanPrereq');
if (btnRescan) btnRescan.addEventListener('click', scanPrerequisites);

const btnNext1 = document.getElementById('btnNext1');
if (btnNext1) btnNext1.addEventListener('click', () => showStep(2));

const btnBack2 = document.getElementById('btnBack2');
if (btnBack2) btnBack2.addEventListener('click', () => showStep(1));

const btnNext2 = document.getElementById('btnNext2');
if (btnNext2) btnNext2.addEventListener('click', () => {
    const nameInput = document.getElementById('inputStoreName');
    const name = nameInput ? nameInput.value.trim() : '';
    if (!name) {
        alert('Please enter your store name.');
        return;
    }
    showStep(3);
});

const btnBack3 = document.getElementById('btnBack3');
if (btnBack3) btnBack3.addEventListener('click', () => showStep(2));

const btnNext3 = document.getElementById('btnNext3');
if (btnNext3) btnNext3.addEventListener('click', () => {
    const p1Input = document.getElementById('inputAdminPassword');
    const p2Input = document.getElementById('inputConfirmPassword');
    const p1 = p1Input ? p1Input.value.trim() : '';
    const p2 = p2Input ? p2Input.value.trim() : '';
    if (p1 && p1 !== p2) {
        alert('Admin passwords do not match. Please re-enter.');
        return;
    }
    showStep(4);
});

const btnBack4 = document.getElementById('btnBack4');
if (btnBack4) btnBack4.addEventListener('click', () => showStep(3));

const btnNext4 = document.getElementById('btnNext4');
if (btnNext4) btnNext4.addEventListener('click', () => {
    showStep(5);
    loadWizardAddons();
});

const btnRefreshCat = document.getElementById('btnRefreshCatalog');
if (btnRefreshCat) {
    btnRefreshCat.addEventListener('click', () => {
        loadWizardAddons(true);
    });
}

const btnBack5 = document.getElementById('btnBack5');
if (btnBack5) btnBack5.addEventListener('click', () => showStep(4));

const btnNext5 = document.getElementById('btnNext5');
if (btnNext5) {
    btnNext5.addEventListener('click', async () => {
        // If crypto keys already generated (user navigated back and forward), skip re-submitting.
        if (generatedCrypto.fernet_key) {
            showStep(6);
            return;
        }
        btnNext5.disabled = true;
        await executeSetupPersistence();
        if (generatedCrypto.fernet_key) {
            showStep(6);
        } else {
            btnNext5.disabled = false;
        }
    });
}

const btnBack6 = document.getElementById('btnBack6');
if (btnBack6) btnBack6.addEventListener('click', () => showStep(5));

const btnNext6 = document.getElementById('btnNext6');
if (btnNext6) btnNext6.addEventListener('click', () => showStep(7));

// ---------------------------------------------------------------------------
// Re-Configuration Authentication Gate Handlers (Tamper Protection)
// ---------------------------------------------------------------------------
const reauthOverlay = document.getElementById('reauthOverlay');
if (reauthOverlay) {
    const pwdInput = document.getElementById('reauthPassword');
    const btnVerify = document.getElementById('btnVerifyReauth');
    const btnCancel = document.getElementById('btnCancelReauth');
    const errorEl = document.getElementById('reauthError');
    const cardEl = document.getElementById('reauthCard');

    function shakeReauth(msg) {
        if (errorEl) errorEl.textContent = msg;
        if (pwdInput) {
            pwdInput.classList.add('error');
            pwdInput.focus();
        }
        if (cardEl) {
            cardEl.classList.remove('shake');
            void cardEl.offsetWidth;
            cardEl.classList.add('shake');
        }
    }

    async function doVerifyReauth() {
        const pwd = pwdInput ? pwdInput.value.trim() : '';
        if (errorEl) errorEl.textContent = '';
        if (btnVerify) {
            btnVerify.disabled = true;
            btnVerify.innerHTML = '<span>⏳</span> Verifying...';
        }

        try {
            const res = await fetch('/api/setup/reauth_verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: pwd })
            });
            const data = await res.json();
            if (res.ok && data.authorized) {
                reauthOverlay.style.opacity = '0';
                reauthOverlay.style.transition = 'opacity 0.25s ease';
                setTimeout(() => {
                    reauthOverlay.remove();
                    scanPrerequisites();
                }, 250);
            } else {
                shakeReauth(data.message || 'Incorrect administrator password.');
                if (pwdInput) pwdInput.value = '';
            }
        } catch (e) {
            shakeReauth('Verification failed: ' + e.message);
        } finally {
            if (btnVerify) {
                btnVerify.disabled = false;
                btnVerify.innerHTML = 'Verify &amp; Unlock Setup';
            }
        }
    }

    if (btnVerify) btnVerify.addEventListener('click', doVerifyReauth);
    if (pwdInput) {
        pwdInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') doVerifyReauth();
        });
        setTimeout(() => pwdInput.focus(), 250);
    }

    if (btnCancel) {
        btnCancel.addEventListener('click', async () => {
            btnCancel.disabled = true;
            btnCancel.innerHTML = '<span>⏳</span> Launching System...';

            if (window.pywebview && window.pywebview.api && window.pywebview.api.cancel_reauth) {
                try {
                    await window.pywebview.api.cancel_reauth();
                    return;
                } catch(e) {
                    console.warn('cancel_reauth error:', e);
                }
            }

            try {
                await fetch('/api/setup/cancel_reauth', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ restart_supervisor: true })
                });
                window.location.href = '/manager';
            } catch(e) {
                window.location.href = '/manager';
            }
        });
    }
}

// Scan prerequisites immediately on load if reauth overlay is not active
document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('reauthOverlay')) {
        scanPrerequisites();
    }
});
