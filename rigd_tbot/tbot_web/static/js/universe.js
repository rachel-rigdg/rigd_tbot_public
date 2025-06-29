// /static/js/universe.js
// Periodically refreshes the Universe Build Progress log and status message in the universe cache inspection page.

function fetchBuildLog() {
    fetch("/static/output/screeners/universe_ops.log")
        .then(response => {
            if (!response.ok) { throw new Error("Log not found"); }
            return response.text();
        })
        .then(text => {
            const lines = text.trim().split("\n");
            const lastLines = lines.slice(-10).join("\n");
            document.getElementById('build-log').textContent = lastLines || "No build progress yet.";
        })
        .catch(err => {
            document.getElementById('build-log').textContent = "Log unavailable.";
        });
}

function fetchStatusMessage() {
    fetch("/universe/status_message")  // This endpoint must be implemented in Flask backend
        .then(response => {
            if (!response.ok) { throw new Error("Status message not found"); }
            return response.text();
        })
        .then(text => {
            document.getElementById('status-msg').textContent = text || "No status message available.";
        })
        .catch(err => {
            document.getElementById('status-msg').textContent = "Status unavailable.";
        });
}

// Initial load
fetchBuildLog();
fetchStatusMessage();

// Refresh every 15 seconds
setInterval(fetchBuildLog, 15000);
setInterval(fetchStatusMessage, 15000);
