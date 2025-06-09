// tbot_web/static/js/wait.js
// Provides shared API helpers and utility functions for frontend JavaScript modules
// Requires shared_utils.js to be loaded first

const bootstrapStates = ["provisioning", "bootstrapping", "initialize"];

async function checkBotState() {
    const data = await apiGet("/main/state");
    if (!data) {
        setTimeout(checkBotState, 2000);
        return;
    }
    const state = data.bot_state;
    // Redirect when NOT in a bootstrap/init state
    if (!bootstrapStates.includes(state)) {
        window.location.replace("/main");
    } else {
        setTimeout(checkBotState, 2000);
    }
}

window.onload = checkBotState;
