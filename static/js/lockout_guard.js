/**
 * =============================================================================
 * Open-POS Manager Access Control Lockout Guard
 * =============================================================================
 * Injected on every protected subview via:
 *   <script src="/static/js/lockout_guard.js" data-section="<section_id>"></script>
 *
 * On DOMContentLoaded:
 *   1. Reads the data-section attribute from this <script> tag.
 *   2. Fetches GET /api/admin/auth/status to check whether access control is active.
 *   3. If require_password === true and the current section is in protected_sections,
 *      renders a full-viewport blur overlay with a PIN/password modal.
 *   4. The modal always surfaces a "Return to Dashboard" escape link.
 *   5. On correct PIN: overlay fades out and page access is restored.
 *   6. On incorrect PIN: input shakes with an error message (no page reload).
 * =============================================================================
 */
(function () {
    'use strict';

    // -------------------------------------------------------------------------
    // Inject the lockout overlay styles dynamically (self-contained, no CSS file
    // dependency so the guard works even on pages missing manager.css partials).
    // -------------------------------------------------------------------------
    const STYLE = `
        #lockoutOverlay {
            position: fixed;
            inset: 0;
            z-index: 99999;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(10, 12, 18, 0.75);
            backdrop-filter: blur(10px) brightness(0.4);
            -webkit-backdrop-filter: blur(10px) brightness(0.4);
            animation: lockoutFadeIn 0.25s ease;
        }
        #lockoutOverlay.hidden {
            display: none;
        }
        @keyframes lockoutFadeIn {
            from { opacity: 0; }
            to   { opacity: 1; }
        }
        @keyframes lockoutFadeOut {
            from { opacity: 1; }
            to   { opacity: 0; }
        }
        @keyframes lockoutShake {
            0%,100% { transform: translateX(0); }
            20%     { transform: translateX(-8px); }
            40%     { transform: translateX(8px); }
            60%     { transform: translateX(-6px); }
            80%     { transform: translateX(6px); }
        }
        .lockout-card {
            background: #1a1d24;
            border: 1px solid #3d4455;
            border-radius: 14px;
            padding: 36px 40px 32px;
            max-width: 420px;
            width: 90%;
            box-shadow: 0 24px 64px rgba(0,0,0,0.6), 0 0 0 1px rgba(59,130,246,0.12);
            display: flex;
            flex-direction: column;
            gap: 16px;
            animation: lockoutFadeIn 0.3s ease;
        }
        .lockout-card.shake {
            animation: lockoutShake 0.4s ease;
        }
        .lockout-icon {
            font-size: 36px;
            text-align: center;
            line-height: 1;
        }
        .lockout-title {
            font-size: 18px;
            font-weight: 700;
            color: #f1f5f9;
            text-align: center;
            margin: 0;
            letter-spacing: -0.3px;
        }
        .lockout-subtitle {
            font-size: 13px;
            color: #94a3b8;
            text-align: center;
            margin: 0;
            line-height: 1.5;
        }
        .lockout-input-wrap {
            position: relative;
        }
        .lockout-input {
            width: 100%;
            background: #222631;
            border: 1px solid #3d4455;
            border-radius: 8px;
            padding: 12px 14px;
            font-size: 15px;
            color: #f1f5f9;
            outline: none;
            letter-spacing: 2px;
            transition: border-color 0.15s ease;
            box-sizing: border-box;
        }
        .lockout-input:focus {
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59,130,246,0.2);
        }
        .lockout-input.error {
            border-color: #ef4444;
        }
        .lockout-error-msg {
            font-size: 12px;
            color: #f87171;
            text-align: center;
            min-height: 16px;
            margin: -6px 0 0;
        }
        .lockout-actions {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-top: 4px;
        }
        .btn-lockout-unlock {
            background: #3b82f6;
            color: #ffffff;
            border: none;
            border-radius: 8px;
            padding: 12px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.15s ease, transform 0.1s ease;
            width: 100%;
        }
        .btn-lockout-unlock:hover {
            background: #2563eb;
            transform: translateY(-1px);
        }
        .btn-lockout-unlock:active {
            transform: translateY(0);
        }
        .btn-lockout-unlock:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        .btn-lockout-return {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            color: #cbd5e1;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            padding: 10px 14px;
            border-radius: 7px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.12);
            transition: color 0.15s ease, background 0.15s ease, border-color 0.15s ease;
            text-align: center;
        }
        .btn-lockout-return:hover {
            color: #ffffff;
            background: rgba(255,255,255,0.12);
            border-color: rgba(255,255,255,0.22);
        }
        .lockout-divider {
            height: 1px;
            background: #2d3343;
            margin: 4px 0;
        }
    `;

    function injectStyles() {
        if (document.getElementById('lockout-guard-styles')) return;
        const style = document.createElement('style');
        style.id = 'lockout-guard-styles';
        style.textContent = STYLE;
        document.head.appendChild(style);
    }

    // -------------------------------------------------------------------------
    // Build and mount the lockout overlay DOM
    // -------------------------------------------------------------------------
    function buildOverlay(sectionLabel) {
        const overlay = document.createElement('div');
        overlay.id = 'lockoutOverlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Protected Section — Authentication Required');

        overlay.innerHTML = `
            <div class="lockout-card" id="lockoutCard">
                <div class="lockout-icon">&#128274;</div>
                <h2 class="lockout-title">Protected Section</h2>
                <p class="lockout-subtitle">
                    <strong>${escapeHtml(sectionLabel)}</strong> requires your administrator
                    PIN or password to access.
                </p>
                <div class="lockout-input-wrap">
                    <input
                        type="password"
                        id="lockoutPinInput"
                        class="lockout-input"
                        placeholder="Enter admin PIN / password"
                        autocomplete="current-password"
                        maxlength="128"
                    >
                </div>
                <p class="lockout-error-msg" id="lockoutErrorMsg"></p>
                <div class="lockout-actions">
                    <button class="btn-lockout-unlock" id="lockoutUnlockBtn">
                        Unlock Access
                    </button>
                    <div class="lockout-divider"></div>
                    <a href="/manager" class="btn-lockout-return" id="lockoutReturnBtn">
                        &larr; Return to Home
                    </a>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
        return overlay;
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    // Humanize section IDs for display (e.g., "configure_manager" -> "Configure Manager")
    function formatSectionLabel(section) {
        return section
            .replace(/_/g, ' ')
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    // -------------------------------------------------------------------------
    // Core lockout logic
    // -------------------------------------------------------------------------
    function showLockout(section) {
        injectStyles();
        const label = formatSectionLabel(section);
        const overlay = buildOverlay(label);

        const pinInput = document.getElementById('lockoutPinInput');
        const unlockBtn = document.getElementById('lockoutUnlockBtn');
        const errorMsg = document.getElementById('lockoutErrorMsg');
        const card = document.getElementById('lockoutCard');

        // Focus PIN input after brief animation delay
        setTimeout(() => pinInput && pinInput.focus(), 300);

        // Allow Enter key to trigger unlock
        pinInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') attemptUnlock();
        });

        unlockBtn.addEventListener('click', attemptUnlock);

        async function attemptUnlock() {
            const pwd = pinInput.value;
            if (!pwd) {
                shakeError('Please enter your administrator PIN or password.');
                return;
            }

            unlockBtn.disabled = true;
            unlockBtn.textContent = 'Verifying';
            errorMsg.textContent = '';
            pinInput.classList.remove('error');

            try {
                const res = await fetch('/api/admin/auth/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pwd, section: section })
                });
                const data = await res.json();

                if (data.authorized) {
                    // Unlock: fade overlay out then remove it
                    overlay.style.animation = 'lockoutFadeOut 0.3s ease forwards';
                    setTimeout(() => {
                        overlay.remove();
                    }, 300);
                } else {
                    shakeError(data.message || 'Incorrect PIN or password. Try again.');
                    pinInput.value = '';
                    pinInput.focus();
                }
            } catch (err) {
                shakeError('Network error — could not verify credentials.');
            } finally {
                unlockBtn.disabled = false;
                unlockBtn.textContent = 'Unlock Access';
            }
        }

        function shakeError(msg) {
            errorMsg.textContent = msg;
            pinInput.classList.add('error');
            // Remove and re-add the shake class to allow re-triggering
            card.classList.remove('shake');
            void card.offsetWidth; // reflow to reset animation
            card.classList.add('shake');
        }
    }

    // -------------------------------------------------------------------------
    // Initialization: check auth status then conditionally show lockout
    // -------------------------------------------------------------------------
    async function init() {
        // Resolve section ID from script tag data-section attribute
        const scriptTag = document.currentScript || (function () {
            const tags = document.querySelectorAll('script[data-section]');
            return tags[tags.length - 1];
        })();
        const section = scriptTag ? (scriptTag.getAttribute('data-section') || '') : '';

        try {
            const res = await fetch('/api/admin/auth/status');
            if (!res.ok) return; // Fail open — don't block access on API errors

            const data = await res.json();

            if (!data.require_password) return; // No lockout configured
            if (!data.has_password) return;     // Password not yet set — allow access
            if (data.authenticated || data.authorized) return; // Already authenticated in active session

            const protected_sections = data.protected_sections || [];

            // Check if 'all' is a wildcard or if this specific section is protected
            const isProtected = (
                protected_sections.includes('all') ||
                (section && protected_sections.includes(section))
            );

            if (isProtected) {
                showLockout(section);
            }
        } catch (err) {
            // Network error or server not ready — fail open
        }
    }

    // Run on DOM ready; use currentScript before DOMContentLoaded fires
    // so we can capture the script tag reference before it's out of scope.
    const _section = (document.currentScript || {}).getAttribute
        ? document.currentScript.getAttribute('data-section') || ''
        : '';

    document.addEventListener('DOMContentLoaded', function () {
        // Re-check with a slight delay to ensure Flask session data is settled
        init();
    });

    // Also catch pages that are already fully loaded (e.g., HMR, SPA navigation)
    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(init, 50);
    }

})();
