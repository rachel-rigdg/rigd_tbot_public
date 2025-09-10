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
            setStatusBanner(state);
        } catch (e) {
            // Silent fail, will retry on next interval
        }
    }

    setInterval(checkBotStateAndRender, 60000);
    checkBotStateAndRender();
});
function setStatusBanner(state) {
    const banner = document.getElementById('status-banner');
    if (!banner) return;
    banner.className = '';
    if (state === "running") {
        banner.classList.add("banner-running");
        banner.textContent = "RUNNING";
    } else if (state === "idle") {
        banner.classList.add("banner-idle");
        banner.textContent = "IDLE";
    } else if (
        state === "provisioning" ||
        state === "bootstrapping" ||
        state === "initialize"
    ) {
        banner.classList.add("banner-wait");
        banner.textContent = "Initializing…";
    } else if (state === "registration") {
        banner.classList.add("banner-wait");
        banner.textContent = "Registration Required";
    } else if (state === "analyzing") {
        banner.classList.add("banner-idle");
        banner.textContent = "ANALYZING";
    } else if (state === "trading") {
        banner.classList.add("banner-running");
        banner.textContent = "TRADING";
    } else if (state === "monitoring") {
        banner.classList.add("banner-idle");
        banner.textContent = "MONITORING";
    } else if (state === "updating") {
        banner.classList.add("banner-idle");
        banner.textContent = "UPDATING";
    } else if (state === "graceful_closing_positions") {
        banner.classList.add("banner-idle");
        banner.textContent = "GRACEFUL CLOSING";
    } else if (state === "emergency_closing_positions") {
        banner.classList.add("banner-error");
        banner.textContent = "EMERGENCY CLOSING";
    } else if (state === "stopped") {
        banner.classList.add("banner-other");
        banner.textContent = "STOPPED";
    } else if (state === "shutdown" || state === "shutdown_triggered") {
        banner.classList.add("banner-error");
        banner.textContent = "SHUTDOWN";
    } else if (state === "error") {
        banner.classList.add("banner-error");
        banner.textContent = "ERROR";
    } else {
        banner.classList.add("banner-other");
        banner.textContent = (state ? state.toUpperCase() : "UNKNOWN");
    }
}
