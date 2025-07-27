// tbot_web/static/js/ledger.js

let currentSort = {col: 'datetime_utc', desc: true};

function autoCalcTotal(rowPrefix) {
    var qty = parseFloat(document.querySelector(rowPrefix + ' input[name="quantity"]').value) || 0;
    var price = parseFloat(document.querySelector(rowPrefix + ' input[name="price"]').value) || 0;
    var fee = parseFloat(document.querySelector(rowPrefix + ' input[name="fee"]').value) || 0;
    var total = (qty * price) - fee;
    document.querySelector(rowPrefix + ' input[name="total_value"]').value = isNaN(total) ? '' : total.toFixed(2);
}

function sortTable(col, desc) {
    fetch(`/ledger/search?sort_by=${col}&sort_desc=${desc ? "1":"0"}`)
    .then(res => res.json())
    .then(data => {
        // Only render entries with at least one primary field non-empty
        let filtered = data.filter(entry =>
            (entry.symbol && String(entry.symbol).trim()) ||
            (entry.datetime_utc && String(entry.datetime_utc).trim()) ||
            (entry.action && String(entry.action).trim()) ||
            (entry.price !== null && entry.price !== "" && entry.price !== "None") ||
            (entry.quantity !== null && entry.quantity !== "" && entry.quantity !== "None") ||
            (entry.total_value !== null && entry.total_value !== "" && entry.total_value !== "None")
        );
        renderLedgerRows(filtered);
    })
    .catch(e => alert("Sort error: " + e));
    currentSort = {col, desc};
    updateSortIndicators();
}

function updateSortIndicators() {
    document.querySelectorAll('.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.col === currentSort.col) {
            th.classList.add(currentSort.desc ? 'sort-desc' : 'sort-asc');
        }
    });
}

function toggleCollapse(groupId) {
    fetch(`/ledger/collapse_expand/${groupId}`, {method:"POST"})
    .then(()=>location.reload());
}

function renderLedgerRows(data) {
    let tbody = document.getElementById('ledger-tbody');
    tbody.innerHTML = '';
    data.forEach(function(entry) {
        // Only render if at least one display field is set
        if (
            (entry.symbol && String(entry.symbol).trim()) ||
            (entry.datetime_utc && String(entry.datetime_utc).trim()) ||
            (entry.action && String(entry.action).trim()) ||
            (entry.price !== null && entry.price !== "" && entry.price !== "None") ||
            (entry.quantity !== null && entry.quantity !== "" && entry.quantity !== "None") ||
            (entry.total_value !== null && entry.total_value !== "" && entry.total_value !== "None")
        ) {
            let trTop = document.createElement('tr');
            trTop.className = "row-top " + (entry.status || "");
            trTop.innerHTML = `
                <td>
                    <button class="collapse-btn" onclick="toggleCollapse('${entry.group_id}')">
                        ${entry.collapsed ? "+" : "-"}
                    </button> ${entry.datetime_utc ? entry.datetime_utc.split('T')[0] : ""}
                </td>
                <td>${entry.symbol || ""}</td>
                <td>${entry.action || ""}</td>
                <td>${entry.quantity || ""}</td>
                <td>${entry.price || ""}</td>
                <td>${entry.fee || ""}</td>
                <td>${entry.total_value || ""}</td>
                <td>${entry.status || ""}</td>
                <td>${entry.running_balance !== undefined ? entry.running_balance : ""}</td>
            `;
            tbody.appendChild(trTop);
            if (!entry.collapsed && entry.sub_entries && entry.sub_entries.length) {
                entry.sub_entries.forEach(function(sub) {
                    let trSub = document.createElement('tr');
                    trSub.className = "row-bottom " + (sub.status || "");
                    trSub.innerHTML = `
                        <td>${sub.trade_id || ""}</td>
                        <td>${sub.account || ""}</td>
                        <td>${sub.strategy || ""}</td>
                        <td>${sub.tags || ""}</td>
                        <td>${sub.notes || ""}</td>
                        <td colspan="3"></td>
                        <td></td>
                    `;
                    tbody.appendChild(trSub);
                });
            }
        }
    });
    updateSortIndicators();
}

document.addEventListener("DOMContentLoaded", function() {
    // Only apply to add-entry row (first add row)
    var prefix = 'tr.row-top form[action$="add_ledger_entry_route"] ';
    ['quantity', 'price', 'fee'].forEach(function(field) {
        var el = document.querySelector(prefix + 'input[name="' + field + '"]');
        if (el) {
            el.addEventListener('input', function() { autoCalcTotal(prefix); });
        }
    });
    document.querySelectorAll('.sortable').forEach(function(th) {
        th.addEventListener('click', function() {
            let col = th.dataset.col;
            let desc = currentSort.col === col ? !currentSort.desc : true;
            sortTable(col, desc);
        });
    });
    updateSortIndicators();
});
