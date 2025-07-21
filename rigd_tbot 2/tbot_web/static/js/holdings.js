// tbot_web/static/js/holdings.js

document.addEventListener("DOMContentLoaded", () => {
    loadConfig();
    loadStatus();

    const configForm = document.getElementById("holdings-config-form");
    const rebalanceBtn = document.getElementById("trigger-rebalance-btn");

    if (configForm) {
        configForm.addEventListener("submit", (e) => {
            e.preventDefault();
            saveConfig();
        });
    }

    if (rebalanceBtn) {
        rebalanceBtn.addEventListener("click", () => {
            triggerManualRebalance();
        });
    }
});

function loadConfig() {
    fetch("/holdings/config")
        .then(res => res.json())
        .then(data => {
            for (const key in data) {
                const el = document.getElementById(key);
                if (el) el.value = data[key];
            }
        })
        .catch(err => {
            alert("Error loading config: " + err.message);
        });
}

function saveConfig() {
    const payload = {
        HOLDINGS_FLOAT_TARGET_PCT: parseFloat(document.getElementById("HOLDINGS_FLOAT_TARGET_PCT").value),
        HOLDINGS_TAX_RESERVE_PCT: parseFloat(document.getElementById("HOLDINGS_TAX_RESERVE_PCT").value),
        HOLDINGS_PAYROLL_PCT: parseFloat(document.getElementById("HOLDINGS_PAYROLL_PCT").value),
        HOLDINGS_REBALANCE_INTERVAL: parseInt(document.getElementById("HOLDINGS_REBALANCE_INTERVAL").value),
        HOLDINGS_ETF_LIST: document.getElementById("HOLDINGS_ETF_LIST").value
    };

    fetch("/holdings/config", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(data => {
        if (data.status === "success") {
            alert("Settings saved.");
            loadStatus();
        } else {
            alert("Error saving config: " + (data.error || "Unknown error"));
        }
    })
    .catch(err => {
        alert("Config save failed: " + err.message);
    });
}

function loadStatus() {
    fetch("/holdings/status")
        .then(res => res.json())
        .then(data => {
            if (data.error) {
                alert("Status load error: " + data.error);
                return;
            }
            document.getElementById("account_value").textContent = formatCurrency(data.account_value);
            document.getElementById("cash").textContent = formatCurrency(data.cash);
            document.getElementById("etf_holdings").textContent = JSON.stringify(data.etf_holdings, null, 2);
            document.getElementById("next_rebalance_due").textContent = data.next_rebalance_due || "N/A";
        })
        .catch(err => {
            alert("Failed to load status: " + err.message);
        });
}

function triggerManualRebalance() {
    fetch("/holdings/rebalance", { method: "POST" })
        .then(res => res.json())
        .then(data => {
            if (data.status === "rebalance_triggered") {
                alert("Manual rebalance triggered.");
                loadStatus();
            } else {
                alert("Rebalance failed: " + (data.error || "Unknown error"));
            }
        })
        .catch(err => {
            alert("Rebalance error: " + err.message);
        });
}

function formatCurrency(value) {
    if (isNaN(value)) return "$0.00";
    return "$" + parseFloat(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
