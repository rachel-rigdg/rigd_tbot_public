// static/js/test_ui.js

let logPoller = null;
let currentTest = null;

function startLogPolling() {
    if (logPoller) clearInterval(logPoller);
    logPoller = setInterval(fetchLogs, 1500);
}

function fetchLogs() {
    fetch("/test/logs")
    .then(response => response.json())
    .then(data => {
        document.getElementById('test-log-output').textContent = data.logs || '';
        const statusEl = document.getElementById('test-status');
        statusEl.textContent = data.status || '';
        statusEl.className = '';
        if (currentTest) {
            document.getElementById('running-test-label').textContent = "Running: " + currentTest;
        }
        if (data.status === "completed") {
            statusEl.classList.add('status-completed');
            clearInterval(logPoller);
            enableButtons();
            if (currentTest) {
                document.getElementById('running-test-label').textContent = currentTest + " — Completed";
            }
            currentTest = null;
        } else if (data.status === "idle") {
            statusEl.classList.remove('status-running', 'status-error', 'status-completed');
            clearInterval(logPoller);
            enableButtons();
            document.getElementById('running-test-label').textContent = '';
            currentTest = null;
        } else if (data.status === "error") {
            statusEl.classList.add('status-error');
            clearInterval(logPoller);
            enableButtons();
            if (currentTest) {
                document.getElementById('running-test-label').textContent = currentTest + " — Error";
            }
            currentTest = null;
        } else {
            statusEl.classList.add('status-running');
        }
    });
}

function disableButtons() {
    document.querySelectorAll('.test-btn').forEach(btn => btn.disabled = true);
}

function enableButtons() {
    document.querySelectorAll('.test-btn').forEach(btn => btn.disabled = false);
}

function runAllTests() {
    disableButtons();
    currentTest = "ALL TESTS";
    document.getElementById('running-test-label').textContent = "Running: ALL TESTS";
    const statusEl = document.getElementById('test-status');
    statusEl.textContent = "triggered";
    statusEl.className = 'status-running';
    fetch("/test/trigger", {method: "POST"})
        .then(() => startLogPolling());
}

function runIndividualTest(testName) {
    disableButtons();
    currentTest = testName;
    document.getElementById('running-test-label').textContent = "Running: " + testName;
    const statusEl = document.getElementById('test-status');
    statusEl.textContent = "triggered";
    statusEl.className = 'status-running';
    fetch("/test/run/" + encodeURIComponent(testName), {method: "POST"})
        .then(response => response.json())
        .then(data => {
            if (data.result === "already_running") {
                statusEl.textContent = "A test is already running.";
                statusEl.className = 'status-error';
                enableButtons();
                currentTest = null;
                document.getElementById('running-test-label').textContent = '';
            } else if (data.result === "unknown_test") {
                statusEl.textContent = "Unknown test: " + testName;
                statusEl.className = 'status-error';
                enableButtons();
                currentTest = null;
                document.getElementById('running-test-label').textContent = '';
            } else {
                startLogPolling();
            }
        });
}

window.onload = function() {
    fetchLogs();
};
