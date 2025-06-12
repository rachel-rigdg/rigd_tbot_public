// tbot_web/static/js/main_ui.js
// Handles live dashboard behavior, state polling, and controls config overlay in main.html
// Requires shared_utils.js to be loaded first

document.addEventListener("DOMContentLoaded", async () => {
    const configOverlay = document.getElementById("config-overlay");
    const configIframe = document.getElementById("config-iframe");

    async function checkBotStateAndRender() {
        const data = await apiGet("/main/state");
        if (!data) return; // API call failed
        const state = data.bot_state || data.state;

        if (state === "initialize" || state === "provisioning" || state === "bootstrapping") {
            // Show config overlay/iframe until setup is completed
            if (configOverlay) configOverlay.style.display = "flex";
            if (configIframe) configIframe.src = "/configuration";
        } else if (state === "registration") {
            // Show registration overlay
            if (configOverlay) configOverlay.style.display = "flex";
            if (configIframe) configIframe.src = "/register";
        } else {
            // Hide config overlay if not needed
            if (configOverlay) configOverlay.style.display = "none";
        }
        // Optionally: handle other states for dashboard status
        updateStatusBanner(state);
    }

    // Optionally poll for updates every 3 seconds
    setInterval(checkBotStateAndRender, 3000);

    // Initial check
    checkBotStateAndRender();
});

// Example status banner logic
function updateStatusBanner(state) {
    const statusBanner = document.getElementById("status-banner");
    if (!statusBanner) return;
    switch (state) {
        case "monitoring":
        case "idle":
            statusBanner.textContent = "System Ready";
            statusBanner.className = "banner-ok";
            break;
        case "provisioning":
        case "bootstrapping":
        case "initialize":
            statusBanner.textContent = "Initializing…";
            statusBanner.className = "banner-wait";
            break;
        case "registration":
            statusBanner.textContent = "Registration Required";
            statusBanner.className = "banner-wait";
            break;
        case "error":
        case "shutdown":
            statusBanner.textContent = "Error / Shutdown";
            statusBanner.className = "banner-error";
            break;
        default:
            statusBanner.textContent = "Unknown state";
            statusBanner.className = "banner-unknown";
    }
}
