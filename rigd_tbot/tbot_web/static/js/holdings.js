// tbot_web/static/js/holdings.js

document.addEventListener("DOMContentLoaded", () => {
    loadConfig();
    loadStatus();

    const configForm = document.getElementById("holdings-config-form");
    const rebalanceBtn = document.getElementById("trigger-rebalance-btn");
    const addEtfBtn = document.getElementById("add-etf-btn");

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

    if (addEtfBtn) {
        addEtfBtn.addEventListener("click", () => {
            addEtfRow();
        });
    }
});

function loadConfig() {
    fetch("/holdings/config")
        .then(res => res.json())
        .then(data => {
            document.getElementById("HOLDINGS_FLOAT_TARGET_PCT").value = data.HOLDINGS_FLOAT_TARGET_PCT;
            document.getElementById("HOLDINGS_TAX_RESERVE_PCT").value = data.HOLDINGS_TAX_RESERVE_PCT;
            document.getElementById("HOLDINGS_PAYROLL_PCT").value = data.HOLDINGS_PAYROLL_PCT;
            document.getElementById("HOLDINGS_REBALANCE_INTERVAL").value = data.HOLDINGS_REBALANCE_INTERVAL;

            if (data.HOLDINGS_ETF_LIST) {
                const list = data.HOLDINGS_ETF_LIST.split(",").map(x => x.trim());
                list.forEach(entry => {
                    const [symbol, pct] = entry.split(":");
                    addEtfRow(symbol, pct);
                });
            }
        })
        .catch(err => {
            alert("Error loading config: " + err.message);
        });
}

function saveConfig() {
    const rows = document.querySelectorAll("#etf-table-body tr");
    const etfEntries = [];

    rows.forEach(row => {
        const symbol = row.querySelector(".etf-symbol").value.trim();
        const alloc = row.querySelector(".etf-alloc").value.trim();
        if (symbol) etfEntries.push(`${symbol}:${alloc}`);
    });

    const payload = {
        HOLDINGS_FLOAT_TARGET_PCT: parseFloat(document.getElementById("HOLDINGS_FLOAT_TARGET_PCT").value),
        HOLDINGS_TAX_RESERVE_PCT: parseFloat(document.getElementById("HOLDINGS_TAX_RESERVE_PCT").value),
        HOLDINGS_PAYROLL_PCT: parseFloat(document.getElementById("HOLDINGS_PAYROLL_PCT").value),
        HOLDINGS_REBALANCE_INTERVAL: parseInt(document.getElementById("HOLDINGS_REBALANCE_INTERVAL").value),
        HOLDINGS_ETF_LIST: etfEntries.join(",")
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
            document.getElementById("next_rebalance_due").textContent = data.next_rebalance_due || "N/A";

            const tbody = document.getElementById("etf-table-body");
            tbody.innerHTML = "";
            if (Array.isArray(data.etf_holdings)) {
                data.etf_holdings.forEach(etf => {
                    const row = addEtfRow(etf.symbol, etf.allocation_pct);
                    row.querySelector(".etf-price").textContent = formatCurrency(etf.purchase_price);
                    row.querySelector(".etf-units").textContent = etf.units;
                    row.querySelector(".etf-market").textContent = formatCurrency(etf.market_price);
                    row.querySelector(".etf-value").textContent = formatCurrency(etf.market_value);
                    row.querySelector(".etf-pl").textContent = formatCurrency(etf.unrealized_pl);
                    row.querySelector(".etf-total").textContent = formatCurrency(etf.total_gain_loss);
                });
            }
        })
        .catch(err => {
            alert("Failed to load status: " + err.message);
        });
}

function addEtfRow(symbol = "", alloc = "") {
    const tbody = document.getElementById("etf-table-body");
    const row = document.createElement("tr");

    row.innerHTML = `
        <td><input class="etf-symbol" value="${symbol}" autocomplete="off"></td>
        <td><input class="etf-alloc" type="number" step="0.1" value="${alloc}" autocomplete="off"></td>
        <td class="etf-price">--</td>
        <td class="etf-units">--</td>
        <td class="etf-market">--</td>
        <td class="etf-value">--</td>
        <td class="etf-pl">--</td>
        <td class="etf-total">--</td>
        <td><button class="remove-etf-btn">X</button></td>
    `;

    row.querySelector(".remove-etf-btn").addEventListener("click", () => row.remove());
    tbody.appendChild(row);
    return row;
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
