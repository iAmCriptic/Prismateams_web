(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        const root = document.getElementById('mainMailWizard');
        if (!root) return;

        let presets = {};
        try {
            presets = JSON.parse(root.dataset.presets || '{}');
        } catch (_e) {
            presets = {};
        }

        const providerInput = document.getElementById('main_mail_provider');
        const providerBtns = root.querySelectorAll('.main-mail-provider-btn');
        const emailInput = document.getElementById('main_mail_email');
        const passwordInput = document.getElementById('main_mail_password');
        const smtpServerInput = document.getElementById('main_mail_smtp_server');
        const smtpPortInput = document.getElementById('main_mail_smtp_port');
        const smtpSecSelect = document.getElementById('main_mail_smtp_security');
        const defaultSenderInput = document.getElementById('main_mail_default_sender');
        const imapServerInput = document.getElementById('main_mail_imap_server');
        const imapPortInput = document.getElementById('main_mail_imap_port');
        const imapSslInput = document.getElementById('main_mail_imap_ssl');
        const imapUserInput = document.getElementById('main_mail_imap_username');
        const detailsEl = document.getElementById('mainMailAdvancedDetails');
        const alertEl = document.getElementById('mainMailWizardAlert');

        const autodiscoverBtn = document.getElementById('mainMailAutodiscoverBtn');
        const testSmtpBtn = document.getElementById('mainMailTestSmtpBtn');
        const testImapBtn = document.getElementById('mainMailTestImapBtn');

        function showAlert(kind, msg) {
            if (!alertEl) return;
            alertEl.className = 'alert mb-3 alert-' + kind;
            alertEl.textContent = msg;
            alertEl.classList.remove('d-none');
        }

        function setBusy(btn, busy) {
            if (!btn) return;
            btn.disabled = busy;
        }

        function applyPreset(key) {
            const p = presets[key];
            if (providerInput) providerInput.value = key;
            providerBtns.forEach(function (b) {
                b.classList.toggle('active', b.dataset.provider === key);
            });
            if (!p || key === 'custom') {
                if (detailsEl) detailsEl.open = true;
                return;
            }
            if (p.smtp_server && smtpServerInput) smtpServerInput.value = p.smtp_server;
            if (p.smtp_port && smtpPortInput) smtpPortInput.value = p.smtp_port;
            if (smtpSecSelect) {
                smtpSecSelect.value = p.smtp_use_ssl ? 'ssl' : (p.smtp_use_tls ? 'tls' : 'none');
            }
            if (p.imap_server && imapServerInput) imapServerInput.value = p.imap_server;
            if (p.imap_port && imapPortInput) imapPortInput.value = p.imap_port;
            if (imapSslInput) imapSslInput.checked = Boolean(p.imap_use_ssl);
        }

        providerBtns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                applyPreset(btn.dataset.provider || 'custom');
            });
        });

        async function postJson(url, payload) {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            return resp.json();
        }

        function collectPayload() {
            const sec = smtpSecSelect ? smtpSecSelect.value : 'tls';
            return {
                email: emailInput ? emailInput.value.trim() : '',
                password: passwordInput ? passwordInput.value : '',
                smtp_server: smtpServerInput ? smtpServerInput.value.trim() : '',
                smtp_port: smtpPortInput ? parseInt(smtpPortInput.value || '587', 10) : 587,
                smtp_use_ssl: sec === 'ssl',
                smtp_use_tls: sec === 'tls',
                smtp_username: emailInput ? emailInput.value.trim() : '',
                smtp_password: passwordInput ? passwordInput.value : '',
                imap_server: imapServerInput ? imapServerInput.value.trim() : '',
                imap_port: imapPortInput ? parseInt(imapPortInput.value || '993', 10) : 993,
                imap_use_ssl: imapSslInput ? imapSslInput.checked : true,
                imap_username: imapUserInput ? imapUserInput.value.trim() : '',
                imap_password: passwordInput ? passwordInput.value : '',
            };
        }

        if (autodiscoverBtn) {
            autodiscoverBtn.addEventListener('click', async function () {
                const email = emailInput ? emailInput.value.trim() : '';
                const password = passwordInput ? passwordInput.value : '';
                if (!email || !email.includes('@') || !password) {
                    showAlert('warning', root.dataset.i18nIncomplete || 'Bitte E-Mail-Adresse und Passwort eingeben.');
                    return;
                }
                setBusy(autodiscoverBtn, true);
                showAlert('info', root.dataset.i18nDetecting || 'Suche Servereinstellungen...');
                try {
                    const data = await postJson(root.dataset.autodiscoverUrl, { email: email, password: password });
                    if (data.imap && imapServerInput) {
                        if (data.imap.server) imapServerInput.value = data.imap.server;
                        if (data.imap.port && imapPortInput) imapPortInput.value = data.imap.port;
                        if (imapSslInput) imapSslInput.checked = Boolean(data.imap.use_ssl);
                        if (data.imap.username && imapUserInput) imapUserInput.value = data.imap.username;
                    }
                    if (data.smtp && smtpServerInput) {
                        if (data.smtp.server) smtpServerInput.value = data.smtp.server;
                        if (data.smtp.port && smtpPortInput) smtpPortInput.value = data.smtp.port;
                        if (smtpSecSelect) {
                            smtpSecSelect.value = data.smtp.use_ssl ? 'ssl' : (data.smtp.use_tls ? 'tls' : 'none');
                        }
                        if (data.smtp.username && emailInput) emailInput.value = data.smtp.username;
                    }
                    if (defaultSenderInput && !defaultSenderInput.value.trim()) {
                        defaultSenderInput.value = email;
                    }
                    if (data.success) {
                        showAlert('success', data.message || 'OK');
                    } else {
                        if (detailsEl) detailsEl.open = true;
                        showAlert('warning', data.message || root.dataset.i18nError);
                    }
                } catch (_err) {
                    if (detailsEl) detailsEl.open = true;
                    showAlert('danger', root.dataset.i18nError || 'Fehler');
                } finally {
                    setBusy(autodiscoverBtn, false);
                }
            });
        }

        if (testSmtpBtn) {
            testSmtpBtn.addEventListener('click', async function () {
                setBusy(testSmtpBtn, true);
                showAlert('info', root.dataset.i18nTesting || 'Teste...');
                try {
                    const data = await postJson(root.dataset.testSmtpUrl, collectPayload());
                    showAlert(data.success ? 'success' : 'danger', data.message || root.dataset.i18nError);
                } catch (_err) {
                    showAlert('danger', root.dataset.i18nError || 'Fehler');
                } finally {
                    setBusy(testSmtpBtn, false);
                }
            });
        }

        if (testImapBtn) {
            testImapBtn.addEventListener('click', async function () {
                setBusy(testImapBtn, true);
                showAlert('info', root.dataset.i18nTesting || 'Teste...');
                try {
                    const data = await postJson(root.dataset.testImapUrl, collectPayload());
                    showAlert(data.success ? 'success' : 'danger', data.message || root.dataset.i18nError);
                } catch (_err) {
                    showAlert('danger', root.dataset.i18nError || 'Fehler');
                } finally {
                    setBusy(testImapBtn, false);
                }
            });
        }
    });
})();
