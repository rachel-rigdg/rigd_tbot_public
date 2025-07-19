/* tbot_web/static/js/holdings.js */

document.addEventListener("DOMContentLoaded", () => {
    loadConfig();
    loadStatus();

    document.getElementById("holdings-config-form").addEventListener("submit", (e) => {
        e.preventDefault();
        saveConfig();
    });

    document.getElementById("trigger-rebalance-btn").addEventListener("click", () => {
        alert("Manual rebalance trigger not implemented yet.");
    });
});

function loadConfig() {
    fetch("/holdings/config")
        .then(res => res.json())
        .then(data => {
            for (const key in data) {
                const el = document.getElementById(key);
                if (el) el.value = data[key];
            }
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
    }).then(() => {
        alert("Settings saved.");
        loadStatus();
    });
}

function loadStatus() {
    fetch("/holdings/status")
        .then(res => res.json())
        .then(data => {
            document.getElementById("account_value").textContent = `$${data.account_value}`;
            document.getElementById("cash").textContent = `$${data.cash}`;
            document.getElementById("etf_holdings").textContent = JSON.stringify(data.etf_holdings, null, 2);
            document.getElementById("next_rebalance_due").textContent = data.next_rebalance_due;
        });
}
