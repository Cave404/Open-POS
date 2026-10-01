/**
 * =============================================================================
 * Open-POS Lockout Form Controller (static/js/auth_lock.js)
 * =============================================================================
 * Handles asynchronous PIN submission, validation feedback, and clean redirect
 * to requested target view without client-side modal stacking.
 * =============================================================================
 */
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('managerLockForm');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const pinInput = document.getElementById('adminPinInput');
        const errorDiv = document.getElementById('pinError');
        const nextUrl = document.getElementById('nextUrl').value || '/manager';

        errorDiv.classList.add('d-none');
        pinInput.classList.remove('is-invalid');

        try {
            const res = await fetch('/auth/verify-pin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pin: pinInput.value, next_url: nextUrl })
            });
            const data = await res.json();

            if (data.success) {
                window.location.href = data.redirect_url;
            } else {
                pinInput.classList.add('is-invalid');
                errorDiv.textContent = data.error || 'Incorrect PIN';
                errorDiv.classList.remove('d-none');
                pinInput.value = '';
                pinInput.focus();
            }
        } catch (err) {
            errorDiv.textContent = 'Server communication error';
            errorDiv.classList.remove('d-none');
        }
    });
});
