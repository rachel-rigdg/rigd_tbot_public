// tbot_web/static/js/ledger.js

/* ========= State (persisted) ========= */
const LS_SORT_KEY = 'ledger.sort';
const LS_EXPANDED_KEY = 'ledger.expandedSet';
const LS_COLLAPSE_ALL_KEY = 'ledger.collapseAll';

let currentSort = loadSort() || { col: 'datetime_utc', desc: true };
let expandedSet = loadExpandedSet();

/* ========= Utils ========= */
function saveSort() { localStorage.setItem(LS_SORT_KEY, JSON.stringify(currentSort)); }
function loadSort() {
  try { return JSON.parse(localStorage.getItem(LS_SORT_KEY) || ''); } catch { return null; }
}

function saveExpandedSet() { localStorage.setItem(LS_EXPANDED_KEY, JSON.stringify(Array.from(expandedSet))); }
function loadExpandedSet() {
  try {
    const raw = JSON.parse(localStorage.getItem(LS_EXPANDED_KEY) || '[]');
    return new Set(Array.isArray(raw) ? raw : []);
  } catch { return new Set(); }
}

function safeNum(x) { const n = Number(x); return Number.isFinite(n) ? n : null; }

function fetchJSON(url, opts={}) {
  return fetch(url, opts).then(res => {
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text().then(() => ({}));
  });
}

function _checkOk(res) { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res; }

/* ========= Column sort (client-side) ========= */

function getColIdx(col) {
  // Keep in sync with template header order (top row)
  const mapping = {
    "datetime_utc": 1,   // DTPOSTED
    "symbol": 2,
    "account": 3,
    "trntype": 4,
    "action": 5,
    "quantity": 6,
    "price": 7,
    "fee": 8,
    "total_value": 9,    // Amount
    "status": 10,
    "running_balance": 11
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

function sortLedgerTable(col) {
  const table = document.querySelector('.ledger-table');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr.row-top')).filter(row => !row.querySelector('form'));
  const asc = (table.dataset.sortCol !== col) ? true : (table.dataset.sortDir !== 'asc');

  rows.sort((a, b) => {
    let av = a.querySelector(`td:nth-child(${getColIdx(col)})`)?.innerText.trim();
    let bv = b.querySelector(`td:nth-child(${getColIdx(col)})`)?.innerText.trim();
    const an = safeNum(av), bn = safeNum(bv);
    if (an !== null && bn !== null) { av = an; bv = bn; }
    if (av === bv) return 0;
    return asc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });

  rows.forEach(row => tbody.appendChild(row));
  table.dataset.sortCol = col;
  table.dataset.sortDir = asc ? 'asc' : 'desc';
  currentSort = { col, desc: !asc };
  saveSort();
  updateSortIndicators();
}

/* ========= Collapse / Expand (server + local) ========= */

const COLLAPSE_ENDPOINT_BASE = "collapse_expand/";
const COLLAPSE_ALL_ENDPOINT  = "collapse_all";

function postCollapseState(groupId, expanded) {
  // Server expects collapsed_state: 1 (collapsed) / 0 (expanded)
  const collapsed_state = expanded ? 0 : 1;
  return fetch(COLLAPSE_ENDPOINT_BASE + encodeURIComponent(groupId), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ collapsed_state })
  }).then(_checkOk);
}

// Back-compat for inline +/- button in the template
function toggleCollapse(groupId, wantExpanded = null) {
  const url = COLLAPSE_ENDPOINT_BASE + encodeURIComponent(groupId);
  let req;
  if (wantExpanded === null) {
    req = fetch(url, { method: "POST" });
  } else {
    const collapsed_state = wantExpanded ? 0 : 1;
    req = fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ collapsed_state })
    });
  }
  // Update local state optimistically
  if (wantExpanded === true) expandedSet.add(groupId);
  if (wantExpanded === false) expandedSet.delete(groupId);
  saveExpandedSet();

  return req.then(_checkOk)
           .then(() => reloadDataOrPage())
           .catch(err => {
              console.error('toggleCollapse failed', err);
              alert('Failed to toggle group view. Check logs.');
           });
}

// Delegate checkbox changes (checked = expanded)
document.addEventListener('change', function(ev) {
  const el = ev.target;
  if (!el.classList.contains('toggle-group')) return;
  const gid = el.dataset.groupId;
  const expanded = el.checked;
  if (expanded) expandedSet.add(gid); else expandedSet.delete(gid);
  saveExpandedSet();
  postCollapseState(gid, expanded)
    .then(() => reloadDataOrPage())
    .catch(err => {
      console.error('collapse/expand failed', err);
      alert('Failed to toggle group view. Check logs.');
    });
});

function setAllCollapsed(collapse) {
  // Persist a user preference (used only as a hint)
  localStorage.setItem(LS_COLLAPSE_ALL_KEY, collapse ? '1' : '0');
  // Server batch toggle (if route exists), otherwise we'll fallback to per-group
  return fetch(COLLAPSE_ALL_ENDPOINT, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ collapse: !!collapse })
  }).then(_checkOk);
}

/* ========= Rendering ========= */

function fmtDate(iso) {
  if (!iso) return '';
  // Expect ISO; show yyyy-mm-ddThh:mm:ss
  return String(iso).slice(0, 19);
}

function pickRepresentative(trades) {
  if (!trades || !trades.length) return {};
  const debit = trades.find(t => String(t.side || '').toLowerCase() === 'debit');
  return debit || trades[0];
}

function groupClientSide(rows) {
  // rows are flat trades from /ledger/search (not actually grouped by server)
  const groups = new Map();
  (rows || []).forEach(r => {
    const gid = r.group_id || r.trade_id || `row-${r.id}`;
    if (!groups.has(gid)) groups.set(gid, []);
    groups.get(gid).push(r);
  });

  const out = [];
  groups.forEach((list, gid) => {
    list.sort((a,b) => {
      const ta = (a.timestamp_utc || a.datetime_utc || a.created_at_utc || '').slice(0, 19);
      const tb = (b.timestamp_utc || b.datetime_utc || b.created_at_utc || '').slice(0, 19);
      if (ta === tb) return (a.id || 0) - (b.id || 0);
      return ta < tb ? -1 : 1;
    });
    const rep = pickRepresentative(list);
    const collapsed = !expandedSet.has(gid); // expandedSet overrides server collapsed state
    const row = {
      collapsed,
      group_id: gid,
      // top-row display
      timestamp_utc: rep.timestamp_utc || rep.datetime_utc || rep.created_at_utc || '',
      symbol: rep.symbol || '',
      account: rep.account || '',
      trntype: rep.trntype || rep.type || '',
      action: rep.action || '',
      quantity: rep.quantity,
      price: rep.price,
      fee: rep.fee,
      total_value: rep.total_value,
      status: rep.status || '',
      running_balance: rep.running_balance,
      // children
      sub_entries: list
    };
    out.push(row);
  });
  return out;
}

function renderBalances(bal) {
  // Optional enhancement: if a <tbody id="balances-tbody"> exists, replace its contents.
  const tbody = document.getElementById('balances-tbody');
  if (!tbody || !bal) return;
  const rows = Object.keys(bal).sort().map(acct => {
    const v = bal[acct] || {};
    const ob = v.opening_balance ?? (v['opening_balance'] ?? '');
    const db = v.debits ?? (v['debits'] ?? '');
    const cr = v.credits ?? (v['credits'] ?? '');
    const cb = v.closing_balance ?? (v['closing_balance'] ?? '');
    return `<tr>
      <td>${acct}</td>
      <td>${ob}</td>
      <td>${db}</td>
      <td>${cr}</td>
      <td>${cb}</td>
    </tr>`;
  }).join('');
  tbody.innerHTML = rows;
}

function renderLedgerRows(data) {
  const tbody = document.getElementById('ledger-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  (data || []).forEach(entry => {
    // Skip empty rows
    if (!(
      (entry.symbol && String(entry.symbol).trim()) ||
      (entry.timestamp_utc && String(entry.timestamp_utc).trim()) ||
      (entry.datetime_utc && String(entry.datetime_utc).trim()) ||
      (entry.action && String(entry.action).trim()) ||
      (entry.price !== null && entry.price !== "" && entry.price !== "None") ||
      (entry.quantity !== null && entry.quantity !== "" && entry.quantity !== "None") ||
      (entry.total_value !== null && entry.total_value !== "" && entry.total_value !== "None")
    )) return;

    const gid = entry.group_id || entry.trade_id || '';
    const top = document.createElement('tr');
    top.className = `row-top ${entry.status || ''}`;
    top.innerHTML = `
      <td>
        <button class="collapse-btn" type="button"
                onclick="toggleCollapse('${gid}', ${entry.collapsed ? 'true' : 'false'})"
                title="${entry.collapsed ? 'Expand' : 'Collapse'}">
          ${entry.collapsed ? "+" : "−"}
        </button>
        ${fmtDate(entry.timestamp_utc || entry.datetime_utc || entry.created_at_utc)}
      </td>
      <td>${entry.symbol || ""}</td>
      <td>${entry.account || ""}</td>
      <td>${entry.trntype || ""}</td>
      <td>${entry.action || ""}</td>
      <td>${entry.quantity ?? ""}</td>
      <td>${entry.price ?? ""}</td>
      <td>${entry.fee ?? ""}</td>
      <td>${entry.total_value ?? ""}</td>
      <td>${entry.status || "OK"}</td>
      <td>${entry.running_balance !== undefined ? entry.running_balance : ""}</td>
    `;
    tbody.appendChild(top);

    if (entry.collapsed && Array.isArray(entry.sub_entries)) {
      entry.sub_entries.forEach(sub => {
        const subTr = document.createElement('tr');
        subTr.className = `row-bottom ${sub.status || ''}`;
        subTr.innerHTML = `
          <td>${sub.trade_id || ""}</td>
          <td>${sub.account || ""}</td>
          <td>${sub.strategy || ""}</td>
          <td>${sub.tags || ""}</td>
          <td>${sub.notes || ""}</td>
          <td>${sub.side || ""}</td>
          <td colspan="5" class="subnote">
            DTPOSTED: ${fmtDate(sub.timestamp_utc || sub.datetime_utc || sub.created_at_utc)}
            &nbsp; • &nbsp; TRNTYPE: ${sub.trntype || sub.type || ""}
            &nbsp; • &nbsp; Amount: ${sub.total_value ?? ""}
          </td>
        `;
        tbody.appendChild(subTr);
      });
    }
  });

  // Re-apply chosen sort
  updateSortIndicators();
  sortLedgerTable(currentSort.col);
}

/* ========= Data loading (progressive enhancement) ========= */

async function tryFetchGrouped() {
  // Use the search endpoint (flat rows). We'll group on the client by group_id/trade_id.
  try {
    const rows = await fetchJSON('search?q=');
    if (!Array.isArray(rows)) throw new Error('Unexpected search payload');
    return groupClientSide(rows);
  } catch (e) {
    // Endpoint may not exist; return null to signal fallback to server-rendered HTML
    console.warn('Grouped fetch fallback:', e.message || e);
    return null;
  }
}

async function tryFetchBalances() {
  // Optional JSON balances endpoint; if missing, no-op.
  try {
    const bal = await fetchJSON('balances');
    if (!bal || typeof bal !== 'object') throw new Error('Unexpected balances payload');
    return bal;
  } catch {
    return null;
  }
}

async function reloadDataOrPage() {
  const grouped = await tryFetchGrouped();
  if (grouped) {
    renderLedgerRows(grouped);
    const bal = await tryFetchBalances();
    if (bal) renderBalances(bal);
  } else {
    // No JSON endpoints → hard reload to let server render new state
    location.reload();
  }
}

/* ========= Form helpers ========= */

function autoCalcTotal(rowPrefix) {
  const qEl = document.querySelector(rowPrefix + ' input[name="quantity"]');
  const pEl = document.querySelector(rowPrefix + ' input[name="price"]');
  const fEl = document.querySelector(rowPrefix + ' input[name="fee"]');
  const tEl = document.querySelector(rowPrefix + ' input[name="total_value"]');
  if (!qEl || !pEl || !fEl || !tEl) return;
  const qty = parseFloat(qEl.value) || 0;
  const price = parseFloat(pEl.value) || 0;
  const fee = parseFloat(fEl.value) || 0;
  const total = (qty * price) - fee;
  tEl.value = Number.isFinite(total) ? total.toFixed(2) : '';
}

/* ========= Boot ========= */

document.addEventListener("DOMContentLoaded", function() {
  // Hook add-entry auto calc
  const prefix = 'tr.row-top form[action$="add_ledger_entry_route"] ';
  ['quantity', 'price', 'fee'].forEach(field => {
    const el = document.querySelector(prefix + 'input[name="' + field + '"]');
    if (el) el.addEventListener('input', () => autoCalcTotal(prefix));
  });

  // Sortable headers
  document.querySelectorAll('.sortable').forEach(th => {
    th.addEventListener('click', () => sortLedgerTable(th.dataset.col));
  });
  updateSortIndicators();

  // Master collapse-all
  const collapseAllEl = document.getElementById('collapse-all');
  if (collapseAllEl) {
    collapseAllEl.checked = localStorage.getItem(LS_COLLAPSE_ALL_KEY) === '1';
    collapseAllEl.addEventListener('change', () => {
      const wantCollapse = collapseAllEl.checked;
      setAllCollapsed(wantCollapse)
        .then(() => {
          // If batch route missing, fallback per-group using current DOM IDs
          return reloadDataOrPage();
        })
        .catch(err => {
          console.warn('collapse_all route failed; per-group fallback:', err);
          // Fallback: apply to groups we currently know about (client-side only)
          const toggles = Array.from(document.querySelectorAll('.toggle-group'));
          const expanded = !wantCollapse;
          toggles.forEach(cb => {
            const gid = cb.dataset.groupId;
            if (expanded) expandedSet.add(gid); else expandedSet.delete(gid);
          });
          saveExpandedSet();
          // Best-effort: attempt per-group POSTs; ignore failures and just reload
          Promise.all(toggles.map(cb => postCollapseState(cb.dataset.groupId, expanded).catch(() => {})))
            .finally(() => reloadDataOrPage());
        });
    });
  }

  // Sync button → async POST then refresh data
  const syncForm = document.getElementById('syncLedgerForm');
  if (syncForm) {
    syncForm.addEventListener('submit', function(ev) {
      ev.preventDefault();
      const submitBtn = syncForm.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Syncing…';
      }
      fetch(syncForm.action, { method: 'POST' })
        .then(_checkOk)
        .then(() => reloadDataOrPage())
        .catch(err => {
          console.error('Sync failed', err);
          alert('Broker ledger sync failed. Check logs.');
          location.reload(); // last resort
        })
        .finally(() => {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Sync Broker Ledger';
          }
        });
    });
  }

  // Initial progressive enhancement: try fetching JSON; otherwise leave server-rendered HTML
  tryFetchGrouped().then(grouped => {
    if (grouped) {
      renderLedgerRows(grouped);
      tryFetchBalances().then(bal => bal && renderBalances(bal));
    }
  });
});
