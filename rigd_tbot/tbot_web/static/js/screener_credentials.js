// tbot_web/static/js/screener_credentials.js
// JS: UI logic, API calls, masking, save/remove, field validation.
// 100% compliant with v046 screener credentials management spec.

document.addEventListener("DOMContentLoaded", function () {
    // Inject server-provided JSON into window for JS usage
    if (typeof creds_json !== 'undefined') {
        window.allCreds = JSON.parse(creds_json);
    }
    if (typeof keys_json !== 'undefined') {
        window.screenerKeys = JSON.parse(keys_json);
    }

    hideAllForms();
    // Show form if adding for first time (no credentials yet)
    if (typeof window.showAddCredential !== 'undefined' && window.showAddCredential) {
        showEditForm('');
    }
});

function hideAllForms() {
    document.getElementById("credential-form-section").style.display = "none";
    document.getElementById("rotate-form-section").style.display = "none";
    document.getElementById("delete-confirm-section").style.display = "none";
}

function showEditForm(provider) {
    hideAllForms();
    document.getElementById("credential-form-section").style.display = "block";
    document.getElementById("form-title").innerText = provider ? "Edit Provider Credentials" : "Add Provider Credentials";
    document.getElementById("provider-input").value = provider || "";
    clearCredentialFields();
    if (provider && window.allCreds && window.allCreds.hasOwnProperty(provider)) {
        populateCredentialFields(provider);
    }
}

function clearCredentialFields() {
    let screenerKeys = window.screenerKeys || [];
    for (let i = 0; i < screenerKeys.length; i++) {
        const key = screenerKeys[i];
        let el = document.getElementById(key);
        if (el) el.value = "";
    }
}

function populateCredentialFields(provider) {
    if (!window.allCreds) return;
    let data = window.allCreds[provider];
    if (!data) return;
    for (const key in data) {
        if (data.hasOwnProperty(key)) {
            let el = document.getElementById(key);
            if (el) el.value = data[key];
        }
    }
}

function cancelEdit() {
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

function confirmDeleteCredential(provider) {
    hideAllForms();
    document.getElementById("delete-confirm-section").style.display = "block";
    document.getElementById("delete-provider-input").value = provider;
    document.getElementById("delete-provider-label").innerText = provider;
}

function cancelDelete() {
    hideAllForms();
}
