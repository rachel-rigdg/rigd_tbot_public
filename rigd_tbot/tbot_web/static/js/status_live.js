// tbot_web/static/js/status_live.js
// Polls /status/api/bot_state and refreshes bot state on status.html

document.addEventListener("DOMContentLoaded", function () {
    const stateDiv = document.querySelector('.status-grid div:nth-child(2)');
    let lastState = null;

    async function pollBotState() {
        try {
            const resp = await fetch('/status/api/bot_state', {cache: "no-store"});
            if (!resp.ok) return;
            const data = await resp.json();
            const botState = data.bot_state || "unknown";
            if (stateDiv && lastState !== botState) {
                stateDiv.innerHTML = `<strong>Bot State:</strong> ${botState}`;
                lastState = botState;
            }
        } catch (e) {
            // fail silent
        }
    }

    setInterval(pollBotState, 2000);
    pollBotState();
});
