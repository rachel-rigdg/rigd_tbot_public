// tbot_web/static/js/wait.js
// Fix redirect logic to include registration as a bootstrap state to prevent redirect loops

const bootstrapStates = ["provisioning", "bootstrapping", "initialize", "registration"];

async function checkBotState() {
    try {
        const data = await apiGet("/main/state");
        if (!data) {
            setTimeout(checkBotState, 2000);
            return;
        }
        const state = data.bot_state || data.state;
        // Redirect only when NOT in a bootstrap/init/registration state
        if (!bootstrapStates.includes(state)) {
            window.location.replace("/main");
        } else {
            setTimeout(checkBotState, 2000);
        }
    } catch (error) {
        setTimeout(checkBotState, 2000);
    }
}

window.onload = checkBotState;
