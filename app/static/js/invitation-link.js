(() => {
    'use strict';

    const button = document.getElementById('copy-invite-link');
    const field = document.getElementById('invite-url-field');
    const status = document.getElementById('invite-copy-status');
    if (!button || !field || !status) return;

    const label = button.textContent;
    button.addEventListener('click', async () => {
        button.disabled = true;
        button.textContent = label;
        status.textContent = '';
        try {
            // Il valore del campo resta un dato: non viene interpretato come codice o HTML.
            await navigator.clipboard.writeText(field.value);
            button.textContent = 'Copiato!';
            status.textContent = 'Link di invito copiato.';
        } catch {
            field.focus();
            field.select();
            status.textContent = 'Copia automatica non disponibile. Copia manualmente il link selezionato.';
        } finally {
            button.disabled = false;
        }
    });
})();
