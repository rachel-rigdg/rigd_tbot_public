// tbot_web/static/js/shared_utils.js
// Generic GET API helper
async function apiGet(url) {
    try {
        const resp = await fetch(url, { cache: "no-store" });
        if (!resp.ok) throw new Error("API error " + resp.status);
        const data = await resp.json();
        // Normalize bot_state key for all responses
        if (data.bot_state === undefined && data.state !== undefined) data.bot_state = data.state;
        return data;
    } catch (err) {
        console.error("API GET failed:", url, err);
        return null;
    }
}

// Generic POST API helper (optional)
async function apiPost(url, body = {}) {
    try {
        const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error("API error " + resp.status);
        const data = await resp.json();
        if (data.bot_state === undefined && data.state !== undefined) data.bot_state = data.state;
        return data;
    } catch (err) {
        console.error("API POST failed:", url, err);
        return null;
    }
}

// Overlay show/hide helpers (optional)
function showOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = "flex";
}
function hideOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
}
