// static/js/test_ui.js

let logPoller = null;
let statusPoller = null;
let currentTest = null;
let allTests = [];

function startLogPolling() {
    if (logPoller) clearInterval(logPoller);
    logPoller = setInterval(fetchLogs, 1500);
}

function startStatusPolling() {
    if (statusPoller) clearInterval(statusPoller);
    statusPoller = setInterval(fetchTestStatus, 1000);
}

function stopPolling() {
    if (logPoller) clearInterval(logPoller);
    if (statusPoller) clearInterval(statusPoller);
}

function fetchLogs() {
    fetch("/test/logs")
    .then(response => response.json())
    .then(data => {
        document.getElementById('test-log-output').textContent = data.logs || '';
    });
}

function fetchTestStatus() {
    fetch("/test/test_status")
    .then(response => response.json())
    .then(statusDict => {
        allTests.forEach(test => {
            const ind = document.getElementById('test-status-' + test);
            if (!ind) return;
            let status = statusDict[test] || "";
            ind.textContent = status;
            ind.className = "test-status-indicator";
            if (status === "RUNNING") ind.classList.add("test-status-running");
            else if (status === "PASSED") ind.classList.add("test-status-passed");
            else if (status === "ERRORS") ind.classList.add("test-status-errors");
        });

        let isAnyRunning = Object.values(statusDict).some(st => st === "RUNNING");
        if (!isAnyRunning) {
            enableButtons();
            stopPolling();
            currentTest = null;
            document.getElementById('running-test-label').textContent = '';
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
    allTests.forEach(test => setIndicator(test, ""));
    fetch("/test/trigger", {method: "POST"})
        .then(() => {
            startLogPolling();
            startStatusPolling();
        });
}

function runIndividualTest(testName) {
    disableButtons();
    currentTest = testName;
    document.getElementById('running-test-label').textContent = "Running: " + testName;
    setIndicator(testName, "RUNNING");
    fetch("/test/run/" + encodeURIComponent(testName), {method: "POST"})
        .then(response => response.json())
        .then(data => {
            if (data.result === "already_running") {
                setIndicator(testName, "RUNNING");
                enableButtons();
                currentTest = null;
                document.getElementById('running-test-label').textContent = '';
            } else if (data.result === "unknown_test") {
                setIndicator(testName, "ERRORS");
                enableButtons();
                currentTest = null;
                document.getElementById('running-test-label').textContent = '';
            } else {
                startLogPolling();
                startStatusPolling();
            }
        });
}

function setIndicator(test, status) {
    const ind = document.getElementById('test-status-' + test);
    if (!ind) return;
    ind.textContent = status || "";
    ind.className = "test-status-indicator";
    if (status === "RUNNING") ind.classList.add("test-status-running");
    else if (status === "PASSED") ind.classList.add("test-status-passed");
    else if (status === "ERRORS") ind.classList.add("test-status-errors");
}

window.onload = function() {
    allTests = window.allTests || [];
    fetchLogs();
    fetchTestStatus();
    startStatusPolling();
};
