// static/js/test_ui.js

let logPoller = null;
let statusPoller = null;
let currentTest = null;

// Keep this in sync with ALL_TESTS in the backend.
let allTests = [
    "integration_test_runner",
    "backtest_engine",
    "broker_sync",
    "broker_trade_stub",
    "coa_consistency",
    "coa_mapping",
    "coa_web_endpoints",
    "env_bot",
    "fallback_logic",
    "holdings_manager",
    "holdings_web_endpoints",
    "ledger_coa_edit",
    "ledger_concurrency",
    "ledger_corruption",
    "ledger_double_entry",
    "ledger_migration",
    "ledger_reconciliation",
    "ledger_schema",
    "ledger_write_failure",
    "logging_format",
    "main_bot",
    "mapping_upsert",
    "opening_balance",
    "screener_credentials",
    "screener_integration",
    "screener_random",
    "strategy_selfcheck",
    "strategy_tuner",
    "symbol_universe_refresh",
    // optional legacy UI/test key; harmless if not present in backend/UI
    "universe_cache"
];

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
    logPoller = null;
    if (statusPoller) clearInterval(statusPoller);
    statusPoller = null;
}

function fetchLogs() {
    fetch("/test/logs")
        .then(response => response.json())
        .then(data => {
            const logBox = document.getElementById('test-log-output');
            if (logBox) logBox.textContent = data.logs || '';
        });
}

function fetchTestStatus() {
    fetch("/test/test_status")
        .then(response => response.json())
        .then(statusDict => {
            allTests.forEach(test => {
                const ind = document.getElementById('status-' + test);
                if (!ind) return;
                let status = statusDict[test] || "";
                ind.textContent = status;
                ind.className = "test-status-indicator";
                if (status === "RUNNING") ind.classList.add("test-status-running");
                else if (status === "PASSED") ind.classList.add("test-status-passed");
                else if (status === "ERRORS" || status === "FAILED") ind.classList.add("test-status-errors");
            });

            let isAnyRunning = Object.values(statusDict).some(st => st === "RUNNING");
            if (!isAnyRunning) {
                enableButtons();
                stopPolling();
                currentTest = null;
                const lbl = document.getElementById('running-test-label');
                if (lbl) lbl.textContent = '';
            }
        });
}

function disableButtons() {
    document.querySelectorAll('.test-btn').forEach(btn => btn.disabled = true);
}

function enableButtons() {
    document.querySelectorAll('.test-btn').forEach(btn => btn.disabled = false);
}

function clearLogs() {
    const logOutput = document.getElementById('test-log-output');
    if (logOutput) {
        logOutput.textContent = '';
    }
}

function runAllTests() {
    disableButtons();
    currentTest = "ALL TESTS";
    const lbl = document.getElementById('running-test-label');
    if (lbl) lbl.textContent = "Running: ALL TESTS";
    allTests.forEach(test => setIndicator(test, ""));
    clearLogs();
    fetch("/test/trigger", { method: "POST" })
        .then(() => {
            startLogPolling();
            startStatusPolling();
        });
}

function runIndividualTest(testName) {
    disableButtons();
    currentTest = testName;
    const lbl = document.getElementById('running-test-label');
    if (lbl) lbl.textContent = "Running: " + testName;
    setIndicator(testName, "RUNNING");
    clearLogs();
    fetch("/test/run/" + encodeURIComponent(testName), { method: "POST" })
        .then(response => response.json())
        .then(data => {
            if (data.result === "already_running") {
                setIndicator(testName, "RUNNING");
                enableButtons();
                currentTest = null;
                if (lbl) lbl.textContent = '';
            } else if (data.result === "unknown_test") {
                setIndicator(testName, "ERRORS");
                enableButtons();
                currentTest = null;
                if (lbl) lbl.textContent = '';
            } else {
                startLogPolling();
                startStatusPolling();
            }
        });
}

function setIndicator(test, status) {
    const ind = document.getElementById('status-' + test);
    if (!ind) return;
    ind.textContent = status || "";
    ind.className = "test-status-indicator";
    if (status === "RUNNING") ind.classList.add("test-status-running");
    else if (status === "PASSED") ind.classList.add("test-status-passed");
    else if (status === "ERRORS" || status === "FAILED") ind.classList.add("test-status-errors");
}

window.onload = function () {
    // Optionally pull from window.allTests if injected, but default to above.
    if (window.allTests && window.allTests.length) {
        allTests = window.allTests;
    }
    fetchLogs();
    fetchTestStatus();
    startStatusPolling();
};
