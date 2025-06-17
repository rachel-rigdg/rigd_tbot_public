// tbot_web/static/js/main_ui.js
// Handles live dashboard behavior, state polling, and controls config overlay in main.html
// Requires shared_utils.js to be loaded first

document.addEventListener("DOMContentLoaded", async () => {
    const configOverlay = document.getElementById("config-overlay");
    const configIframe = document.getElementById("config-iframe");

    async function checkBotStateAndRender() {
        try {
            const data = await apiGet("/main/state");
            if (!data) return; // API call failed
            const state = data.bot_state || data.state;

            if (state === "registration") {
                window.location.replace("/registration");
                return;
            }

            if (
                state === "initialize" ||
                state === "provisioning" ||
                state === "bootstrapping"
            ) {
                if (configOverlay) configOverlay.style.display = "flex";
                if (configIframe) configIframe.src = "/configuration";
            } else {
                if (configOverlay) configOverlay.style.display = "none";
            }
            updateStatusBanner(state);
        } catch (e) {
            // Silent fail, will retry on next interval
        }
    }

    setInterval(checkBotStateAndRender, 3000);
    checkBotStateAndRender();
});

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
