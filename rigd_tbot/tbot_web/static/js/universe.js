// /static/js/universe.js
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
    fetch("/universe/status_message")
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

// Infinite scroll and async table reload for universe tables
function fetchAndRenderTable(type, bodyId, countId, limit=100) {
    const search = document.getElementById("search-symbol").value || "";
    fetch(`/universe/table/${type}?search=${encodeURIComponent(search)}&offset=0&limit=${limit}`)
        .then(r => r.json()).then(rows => {
            document.getElementById(bodyId).innerHTML = rows.map(renderRow).join("");
            if (countId) document.getElementById(countId).textContent = rows.length;
        });
}

function renderRow(s) {
    return "<tr>" +
        `<td>${s.symbol || ""}</td>` +
        `<td>${s.exchange || ""}</td>` +
        `<td>${typeof s.lastClose === "number" ? s.lastClose.toLocaleString() : (s.lastClose || "")}</td>` +
        `<td>${typeof s.marketCap === "number" ? s.marketCap.toLocaleString() : (s.marketCap || "")}</td>` +
        `<td>${s.companyName || s.name || ""}</td>` +
        `<td>${s.sector || ""}</td>` +
    "</tr>";
}

function refreshTables() {
    fetchAndRenderTable("unfiltered", "unfiltered-table-body", "unfiltered-count");
    fetchAndRenderTable("partial", "partial-table-body", "partial-count");
    fetchAndRenderTable("final", "final-table-body", "final-count", 400);
}

function fetchCounts() {
    fetch("/universe/counts").then(r => r.json()).then(obj => {
        document.getElementById("unfiltered-count").textContent = obj.unfiltered;
        document.getElementById("partial-count").textContent = obj.partial;
        document.getElementById("final-count").textContent = obj.filtered;
    });
}

document.addEventListener("DOMContentLoaded", function() {
    fetchBuildLog();
    fetchStatusMessage();
    refreshTables();
    fetchCounts();

    setInterval(fetchBuildLog, 15000);
    setInterval(fetchStatusMessage, 15000);

    const searchBox = document.getElementById("search-symbol");
    if (searchBox) {
        searchBox.addEventListener('keyup', function(e) {
            if (e.key === "Enter") refreshTables();
        });
    }
});
