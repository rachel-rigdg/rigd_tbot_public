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

function filterTables() {
    const search = document.querySelector('input[name="search"]').value.toUpperCase();
    ['unfiltered', 'partial', 'final'].forEach(tableType => {
        document.querySelectorAll(`.${tableType}-row`).forEach(row => {
            const symbolCell = row.querySelector('.symbol-cell');
            if (symbolCell && symbolCell.textContent.toUpperCase().indexOf(search) !== -1) {
                row.style.display = '';
            } else {
                row.style.display = search ? 'none' : '';
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", function() {
    fetchBuildLog();
    fetchStatusMessage();

    setInterval(fetchBuildLog, 15000);
    setInterval(fetchStatusMessage, 15000);

    const searchBox = document.querySelector('input[name="search"]');
    if (searchBox) {
        searchBox.addEventListener('input', filterTables);
    }
});
