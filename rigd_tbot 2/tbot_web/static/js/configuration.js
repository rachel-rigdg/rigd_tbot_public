// tbot_web/static/js/configuration.js
// Handles config form submission and triggers wait.html redirect after initial setup

document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("config-form");
    if (!form) return;

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        const formData = new FormData(form);

        fetch(form.action, {
            method: "POST",
            body: formData,
        })
        .then(response => {
            if (response.redirected) {
                // If backend redirects, follow it
                window.location.href = response.url;
                return;
            }
            return response.text();
        })
        .then(data => {
            // Optional: Check for a success flag/message
            // On success, force iframe or window reload to /main (which shows wait.html during provisioning/bootstrapping)
            window.location.href = "/main";
        })
        .catch(() => {
            // Optional: Show an error
            alert("Configuration failed. Please try again.");
        });
    });
});
