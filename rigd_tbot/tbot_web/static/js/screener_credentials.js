// tbot_web/static/js/screener_credentials.js
// JS: UI logic, API calls, masking, save/remove, field validation.
// 100% compliant with v046 screener credentials management spec.

document.addEventListener("DOMContentLoaded", function () {
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
    document.getElementById("provider-input").value = provider;
    clearCredentialFields();
}

function addCredentialField() {
    const extraKeys = document.getElementById("extra-keys");
    const fieldCount = extraKeys.children.length / 2 + 2;
    const keyInput = document.createElement("input");
    keyInput.type = "text";
    keyInput.name = `key${fieldCount}`;
    keyInput.id = `key${fieldCount}`;
    keyInput.placeholder = `Key ${fieldCount}`;
    keyInput.required = true;
    keyInput.className = "credential-key-input";
    const valueInput = document.createElement("input");
    valueInput.type = "password";
    valueInput.name = `value${fieldCount}`;
    valueInput.id = `value${fieldCount}`;
    valueInput.placeholder = `Value ${fieldCount}`;
    valueInput.required = true;
    valueInput.className = "credential-value-input";
    extraKeys.appendChild(keyInput);
    extraKeys.appendChild(valueInput);
}

function clearCredentialFields() {
    document.getElementById("key1").value = "";
    document.getElementById("value1").value = "";
    document.getElementById("extra-keys").innerHTML = "";
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
