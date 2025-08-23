// tbot_web/static/js/ledger.js

let currentSort = {col: 'datetime_utc', desc: true};

function autoCalcTotal(rowPrefix) {
    var qty = parseFloat(document.querySelector(rowPrefix + ' input[name="quantity"]').value) || 0;
    var price = parseFloat(document.querySelector(rowPrefix + ' input[name="price"]').value) || 0;
    var fee = parseFloat(document.querySelector(rowPrefix + ' input[name="fee"]').value) || 0;
    var total = (qty * price) - fee;
    document.querySelector(rowPrefix + ' input[name="total_value"]').value = isNaN(total) ? '' : total.toFixed(2);
}

// CLIENT-SIDE sort only, no backend fetch for sort
function sortLedgerTable(col) {
    const table = document.querySelector('.ledger-table');
    const tbody = table.querySelector('tbody');
    let rows = Array.from(tbody.querySelectorAll('tr.row-top')).filter(row => !row.querySelector('form'));
    let asc = !table.dataset.sortDir || table.dataset.sortCol !== col ? true : table.dataset.sortDir !== 'asc';

    rows.sort((a, b) => {
        let av = a.querySelector(`td:nth-child(${getColIdx(col)})`)?.innerText.trim();
        let bv = b.querySelector(`td:nth-child(${getColIdx(col)})`)?.innerText.trim();
        if (!isNaN(parseFloat(av)) && !isNaN(parseFloat(bv))) {
            av = parseFloat(av); bv = parseFloat(bv);
        }
        return asc ? (av > bv ? 1 : av < bv ? -1 : 0) : (av < bv ? 1 : av > bv ? -1 : 0);
    });

    rows.forEach(row => tbody.appendChild(row));
    table.dataset.sortCol = col;
    table.dataset.sortDir = asc ? 'asc' : 'desc';
    currentSort = {col, desc: !asc}; // Set next sort direction for UI
    updateSortIndicators();
}

function getColIdx(col) {
    const mapping = {
        "datetime_utc": 1, "symbol": 2, "action": 3, "quantity": 4,
        "price": 5, "fee": 6, "total_value": 7, "status": 8, "running_balance": 9
    };
    return mapping[col] || 1;
}

function updateSortIndicators() {
    document.querySelectorAll('.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.col === currentSort.col) {
            th.classList.add(currentSort.desc ? 'sort-desc' : 'sort-asc');
        }
    });
}

// --- Collapse/Expand handling ---
const COLLAPSE_ENDPOINT_BASE = "/ledger/collapse_expand/";

function postCollapseState(groupId, expanded) {
    // Server expects collapsed_state: 1/0 (1 = collapsed, 0 = expanded)
    const collapsed_state = expanded ? 0 : 1;
    return fetch(COLLAPSE_ENDPOINT_BASE + encodeURIComponent(groupId), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ collapsed_state })
    });
}

// Back-compat for existing +/- button calls
function toggleCollapse(groupId, wantExpanded = null) {
    if (wantExpanded === null) {
        // Old behavior: no explicit state, let server toggle
        return fetch(COLLAPSE_ENDPOINT_BASE + encodeURIComponent(groupId), { method: "POST" })
            .then(() => location.reload());
    } else {
        return postCollapseState(groupId, wantExpanded).then(() => location.reload());
    }
}

// Delegate checkbox changes (checked = expanded)
document.addEventListener('change', function(ev) {
    const el = ev.target;
    if (!el.classList.contains('toggle-group')) return;
    const gid = el.dataset.groupId;
    const expanded = el.checked;
    postCollapseState(gid, expanded)
        .then(() => location.reload())
        .catch(err => {
            console.error('collapse/expand failed', err);
            alert('Failed to toggle group view. Check logs.');
        });
});

// ---- Collapse-all support (optional) ----
function getGroupCheckboxes() {
    return Array.from(document.querySelectorAll('input.toggle-group[data-group-id]'));
}

function updateCollapseAllIndicator() {
    const master = document.getElementById('collapse-all');
    if (!master) return;
    const boxes = getGroupCheckboxes();
    if (boxes.length === 0) {
        master.checked = true; // nothing to show; treat as collapsed
        master.indeterminate = false;
        return;
    }
    const allExpanded = boxes.every(cb => cb.checked);
    const allCollapsed = boxes.every(cb => !cb.checked);
    if (allExpanded) {
        master.checked = false;         // unchecked = expand all
        master.indeterminate = false;
    } else if (allCollapsed) {
        master.checked = true;          // checked = collapse all
        master.indeterminate = false;
    } else {
        master.checked = false;
        master.indeterminate = true;    // mixed state
    }
}

function attachCollapseAllListener() {
    const master = document.getElementById('collapse-all');
    if (!master) return;
    master.addEventListener('change', async (e) => {
        const collapseAll = e.target.checked; // true => collapse everything
        const targetExpanded = !collapseAll;
        const boxes = getGroupCheckboxes();
        const ops = [];
        for (const cb of boxes) {
            if (cb.checked !== targetExpanded) {
                ops.push(postCollapseState(cb.dataset.groupId, targetExpanded));
            }
        }
        if (ops.length) {
            try { await Promise.all(ops); } catch (err) { console.error(err); }
        }
        location.reload();
    });
}

function renderLedgerRows(data) {
    let tbody = document.getElementById('ledger-tbody');
    tbody.innerHTML = '';
    data.forEach(function(entry) {
        if (
            (entry.symbol && String(entry.symbol).trim()) ||
            (entry.datetime_utc && String(entry.datetime_utc).trim()) ||
            (entry.action && String(entry.action).trim()) ||
            (entry.price !== null && entry.price !== "" && entry.price !== "None") ||
            (entry.quantity !== null && entry.quantity !== "" && entry.quantity !== "None") ||
            (entry.total_value !== null && entry.total_value !== "" && entry.total_value !== "None")
        ) {
            const gid = entry.group_id || entry.trade_id || '';
            let trTop = document.createElement('tr');
            trTop.className = "row-top " + (entry.status || "");
            trTop.innerHTML = `
                <td>
                    <!-- keep old +/- button working; send intended target state -->
                    <button class="collapse-btn" onclick="toggleCollapse('${gid}', ${entry.collapsed ? 'true' : 'false'})" title="${entry.collapsed ? 'Expand' : 'Collapse'}">
                        ${entry.collapsed ? "+" : "-"}
                    </button>
                    <!-- new checkbox: checked = expanded -->
                    <label style="margin-left:.5rem;">
                      <input type="checkbox" class="toggle-group" data-group-id="${gid}" ${entry.collapsed ? '' : 'checked'} />
                      expand
                    </label>
                    ${entry.datetime_utc ? entry.datetime_utc.split('T')[0] : ""}
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
    // After client render, sync master toggle indicator
    updateCollapseAllIndicator();
}

document.addEventListener("DOMContentLoaded", function() {
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
            sortLedgerTable(col);
        });
    });
    updateSortIndicators();
    attachCollapseAllListener();
    // On first load (SSR rows), update master indicator
    updateCollapseAllIndicator();
});

// Expose toggleCollapse globally (used by inline onclick)
window.toggleCollapse = toggleCollapse;
