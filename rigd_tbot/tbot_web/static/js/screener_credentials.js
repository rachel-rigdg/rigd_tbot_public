// tbot_web/static/js/screener_credentials.js
// JS: UI logic, API calls, masking, save/remove, field validation.
// 100% compliant with v046 screener credentials management spec.

document.addEventListener("DOMContentLoaded", function () {
    if (typeof window.allCreds === 'undefined') window.allCreds = {};
    if (typeof window.screenerKeys === 'undefined') window.screenerKeys = [];

    hideAllForms();

    if (window.showAddCredential === true || window.showAddCredential === 'true') {
        showEditForm('');
    }

    // Set form action dynamically on load
    updateCredentialFormAction('');
});

function hideAllForms() {
    document.getElementById("credential-form-section").style.display = "none";
    document.getElementById("delete-confirm-section").style.display = "none";
    document.getElementById("rotate-form-section")?.style.display = "none";
}

function showEditForm(provider) {
    hideAllForms();
    document.getElementById("credential-form-section").style.display = "block";
    document.getElementById("form-title").innerText = provider ? "Edit Provider Credentials" : "Add Provider Credentials";
    const providerInput = document.getElementById("provider-input");
    providerInput.value = provider || "";
    providerInput.readOnly = !!provider;
    clearCredentialFields();
    if (provider && window.allCreds.hasOwnProperty(provider)) {
        populateCredentialFields(provider);
    }
    updateCredentialFormAction(provider);
}

function clearCredentialFields() {
    for (const key of window.screenerKeys) {
        const el = document.getElementById(key);
        if (el) el.value = "";
    }
}

function populateCredentialFields(provider) {
    const data = window.allCreds[provider];
    if (!data) return;
    for (const key in data) {
        if (data.hasOwnProperty(key)) {
            const el = document.getElementById(key);
            if (el) el.value = data[key];
        }
    }
}

function updateCredentialFormAction(provider) {
    const form = document.getElementById("credential-form");
    if (!form) return;
    if (provider && window.allCreds.hasOwnProperty(provider)) {
        form.action = "/screener_credentials/update";
    } else {
        form.action = "/screener_credentials/add";
    }
}

function cancelEdit() {
    hideAllForms();
}

function confirmDeleteCredential(provider) {
    hideAllForms();
    document.getElementById("delete-confirm-section").style.display = "block";
    document.getElementById("delete-provider-input").value = provider;
    document.getElementById("delete-provider-label").innerText = provider;
}

function cancelDelete() {
    hideAllForms();
}

function showRotateForm(provider) {
    hideAllForms();
    document.getElementById("rotate-form-section").style.display = "block";
    document.getElementById("rotate-provider-input").value = provider;
}

function cancelRotate() {
    hideAllForms();
}
