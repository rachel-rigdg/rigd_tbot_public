// tbot_web/static/js/ledger.js

// -----------------------------
// Global sort state (single source of truth)
// -----------------------------
const SORT_STORAGE_KEY = 'ledger_sort_v1';
let currentSort = loadSortState() || { col: 'datetime_utc', dir: 'desc' };

// Utility: debounce
function debounce(fn, wait) {
  let t;
  return function (...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), wait);
  };
}

// Persist/Load sort state
function saveSortState() {
  try { localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(currentSort)); } catch {}
  // reflect in URL for bookmarking/sharing
  const url = new URL(window.location.href);
  url.searchParams.set('sort', currentSort.col);
  url.searchParams.set('dir', currentSort.dir);
  history.replaceState(null, '', url.toString());
}
function loadSortState() {
  try {
    const raw = localStorage.getItem(SORT_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {}
  // fallback to URL
  const url = new URL(window.location.href);
  const col = url.searchParams.get('sort');
  const dir = url.searchParams.get('dir');
  if (col && dir) return { col, dir };
  return null;
}

// -----------------------------
// Column index mapping for client-side sort (top row)
// Keep in sync with ledger.html columns
// Note: 'account' is a hidden column in the top header for sort alignment.
// -----------------------------
function getColIdx(col) {
  const mapping = {
    "datetime_utc": 1,
    "symbol": 2,
    "account": 3,         // hidden top-row column exists purely for sorting
    "action": 4,
    "quantity": 5,
    "price": 6,
    "fee": 7,
    "total_value": 8,
    "status": 9,
    "running_balance": 10,
    // secondary header canonical keys map to concrete sorters server-side;
    // client-side we still point to nearest visible column where possible
    "trade_id": 1,          // fallback: date as stable secondary
    "strategy": 4,          // fallback: action column
    "tags": 4,              // fallback
    "notes": 4,             // fallback
    "action_detail": 4
  };
  return mapping[col] || 1;
}

// Prefer data-sort attribute if present (clean sort key), otherwise text
function _cellSortValue(td) {
  if (!td) return '';
  const ds = td.getAttribute('data-sort');
  if (ds !== null && ds !== undefined) return ds;
  return (td.innerText || '').trim();
}

// -----------------------------
// Client-side sorting (for current DOM) with unified indicators
// -----------------------------
function sortLedgerTable(col, dirOpt) {
  const table = document.querySelector('.ledger-table');
  if (!table) return;

  // Determine direction
  let dir = dirOpt || (currentSort.col === col ? (currentSort.dir === 'asc' ? 'desc' : 'asc') : 'asc');
  currentSort = { col, dir };
  saveSortState();

  const tbody = table.querySelector('tbody');
  let rows = Array.from(tbody.querySelectorAll('tr.row-top')).filter(row => !row.querySelector('form'));

  const idx = getColIdx(col);
  const asc = dir === 'asc';

  rows.sort((a, b) => {
    const atd = a.querySelector(`td:nth-child(${idx})`);
    const btd = b.querySelector(`td:nth-child(${idx})`);
    let av = _cellSortValue(atd);
    let bv = _cellSortValue(btd);
    // numeric compare if both numbers
    const aNum = parseFloat(av); const bNum = parseFloat(bv);
    if (!isNaN(aNum) && !isNaN(bNum)) { av = aNum; bv = bNum; }
    if (av === bv) return 0;
    return asc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });

  rows.forEach(row => tbody.appendChild(row));
  updateSortIndicators();
}

function updateSortIndicators() {
  document.querySelectorAll('.sortable').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    th.setAttribute('aria-sort', 'none');
    if (th.dataset.col === currentSort.col) {
      const cls = currentSort.dir === 'asc' ? 'sort-asc' : 'sort-desc';
      th.classList.add(cls);
      th.setAttribute('aria-sort', currentSort.dir === 'asc' ? 'ascending' : 'descending');
    }
  });
}

// -----------------------------
// Collapse/Expand handling
// -----------------------------
const COLLAPSE_ENDPOINT_BASE = "collapse_expand/";
const COLLAPSE_ALL_ENDPOINT  = "collapse_all";

function _checkOk(res) {
  if (!res.ok) throw res;
  return res;
}

function postCollapseState(groupId, expanded) {
  const collapsed_state = expanded ? 0 : 1;
  return fetch(COLLAPSE_ENDPOINT_BASE + encodeURIComponent(groupId), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ collapsed_state })
  }).then(_checkOk);
}

function toggleCollapse(groupId, wantExpanded = null) {
  const url = COLLAPSE_ENDPOINT_BASE + encodeURIComponent(groupId);
  let p;
  if (wantExpanded === null) {
    p = fetch(url, { method: "POST" });
  } else {
    const collapsed_state = wantExpanded ? 0 : 1;
    p = fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ collapsed_state })
    });
  }
  return p.then(_checkOk)
          .then(() => location.reload())
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
  postCollapseState(gid, expanded)
    .then(() => location.reload())
    .catch(err => {
      console.error('collapse/expand failed', err);
      alert('Failed to toggle group view. Check logs.');
    });
});

// Optional: Collapse/Expand all
function setAllCollapsed(collapse) {
  return fetch(COLLAPSE_ALL_ENDPOINT, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ collapse: !!collapse })
  }).then(_checkOk).then(() => location.reload());
}

// -----------------------------
// Rendering helpers (AJAX refresh)
// -----------------------------
function _td(val, extra = '', sortVal = null) {
  const sAttr = sortVal !== null && sortVal !== undefined ? ` data-sort="${String(sortVal)}"` : '';
  return `<td${sAttr}${extra ? ' ' + extra : ''}>${val ?? ''}</td>`;
}

function renderLedgerRows(data) {
  const tbody = document.getElementById('ledger-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  data.forEach(function(entry) {
    const hasContent =
      (entry.symbol && String(entry.symbol).trim()) ||
      (entry.datetime_utc && String(entry.datetime_utc).trim()) ||
      (entry.action && String(entry.action).trim()) ||
      (entry.price !== null && entry.price !== "" && entry.price !== "None") ||
      (entry.quantity !== null && entry.quantity !== "" && entry.quantity !== "None") ||
      (entry.total_value !== null && entry.total_value !== "" && entry.total_value !== "None");

    if (!hasContent) return;

    const gid = entry.group_id || entry.trade_id || '';
    const dateOnly = entry.datetime_utc ? entry.datetime_utc.split('T')[0] : "";

    // ---- Top row (10 columns; add data-sort for clean sorting) ----
    const trTop = document.createElement('tr');
    trTop.className = "row-top " + (entry.status || "");
    trTop.innerHTML =
      _td(
        `<button class="collapse-btn" onclick="toggleCollapse('${gid}', ${entry.collapsed ? 'true' : 'false'})" title="${entry.collapsed ? 'Expand' : 'Collapse'}">
          ${entry.collapsed ? "+" : "-"}
        </button> ${dateOnly}`,
        '',
        dateOnly
      ) +
      _td(entry.symbol || "", '', entry.symbol || '') +
      `<td class="hidden-account" data-sort="${entry.account || ''}">${entry.account || ""}</td>` +
      _td(entry.action || "", '', entry.action || '') +
      _td(entry.quantity || "", '', entry.quantity ?? '') +
      _td(entry.price || "", '', entry.price ?? '') +
      _td(entry.fee || "", '', entry.fee ?? '') +
      _td(entry.total_value || "", '', entry.total_value ?? '') +
      _td(entry.status || "", '', entry.status || '') +
      _td(entry.running_balance !== undefined ? entry.running_balance : "", '', entry.running_balance ?? '');

    tbody.appendChild(trTop);

    // ---- Bottom row(s): ALWAYS show at least one when collapsed ----
    const subs = Array.isArray(entry.sub_entries) ? entry.sub_entries : [];
    const toRender = entry.collapsed ? subs.slice(0, 1) : subs;

    toRender.forEach(function(sub) {
      const trSub = document.createElement('tr');
      trSub.className = "row-bottom " + (sub.status || "");
      // Keep 10 columns alignment: 5 data cols + 1 action cell + (colspan=3) + 1 trailing blank = 10
      trSub.innerHTML =
        _td(sub.trade_id || "", '', sub.trade_id || '') +
        _td(sub.account || "", '', sub.account || '') +
        _td(sub.strategy || "", '', sub.strategy || '') +
        _td(sub.tags || "", '', sub.tags || '') +
        _td(sub.notes || "", '', sub.notes || '') +
        _td('', 'class="action-cell"') +
        `<td colspan="3"></td>` +
        _td('');
      tbody.appendChild(trSub);
    });
  });

  // Re-apply sort indicators to match state; sorting is client-side for current DOM
  updateSortIndicators();
}

// Refresh balances (fallback to full reload if target element unknown)
function renderBalances(data) {
  // Expecting { accounts: [{name, balance}], totals: {...} } OR key-value map
  const panel = document.querySelector('.ledger-balance-summary .balance-table tbody');
  if (!panel) { location.reload(); return; }
  let html = '';
  if (Array.isArray(data?.accounts)) {
    data.accounts.forEach(a => {
      html += `<tr><td>${a.name}</td><td>${a.balance}</td></tr>`;
    });
  } else if (data && typeof data === 'object') {
    Object.entries(data).forEach(([k,v]) => {
      html += `<tr><td>${k}</td><td>${v}</td></tr>`;
    });
  }
  panel.innerHTML = html;
}

// Fetch groups & balances with current sort (server-side canonical keys)
function fetchGroupsAndRender() {
  const params = new URLSearchParams({ sort: currentSort.col, dir: currentSort.dir });
  return fetch(`groups?${params.toString()}`, { method: 'GET' })
    .then(r => {
      if (r.status === 403) throw r;
      return _checkOk(r);
    })
    .then(r => r.json())
    .then(json => renderLedgerRows(json))
    .catch(err => {
      if (err && err.status === 403) {
        alert('Permission denied (viewer role).');
      } else {
        console.warn('Groups fetch failed, falling back to reload.', err);
        location.reload();
      }
    });
}
function fetchBalancesAndRender() {
  return fetch('balances', { method: 'GET' })
    .then(r => {
      if (r.status === 403) throw r;
      return _checkOk(r);
    })
    .then(r => r.json())
    .then(json => renderBalances(json))
    .catch(err => {
      if (err && err.status === 403) {
        alert('Permission denied (viewer role).');
      } else {
        console.warn('Balances fetch failed, falling back to reload.', err);
        location.reload();
      }
    });
}
const refreshLedgerAndBalancesDebounced = debounce(() => {
  Promise.all([fetchGroupsAndRender(), fetchBalancesAndRender()]).catch(() => {});
}, 250);

// -----------------------------
// Inline COA mapping (event delegation)
// -----------------------------
document.addEventListener('change', async function(ev) {
    const el = ev.target;
    if (!el.matches('.coa-select')) return;
  
    const entryId = el.dataset.entryId || el.getAttribute('data-entry-id');
    const accountCode = el.value;
    if (!entryId || !accountCode) return;
  
    // Keep previous selection to allow revert on failure
    const prev = el.getAttribute('data-prev') ?? '';
    if (!prev) el.setAttribute('data-prev', el.value);
  
    el.classList.add('saving');
    el.disabled = true;
    try {
      const res = await fetch(`edit/${encodeURIComponent(entryId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_code: accountCode, reason: 'inline reassignment' })
      });
  
      // Parse JSON if available (even on non-2xx)
      let data = {};
      try { data = await res.json(); } catch {}
  
      if (res.status === 403) {
        throw new Error('Permission denied: only admins can reassign accounts.');
      }
      if (!res.ok || data.ok === false) {
        const msg = (data && data.error) ? data.error : `HTTP ${res.status}`;
        throw new Error(msg);
      }
  
      // Non-blocking heads-up if mapping didn’t persist (server still logged it)
      if (data.mapping_ok === false) {
        console.warn('COA mapping upsert failed or was skipped.');
      }
  
      el.classList.remove('saving');
      el.classList.add('saved');
      setTimeout(() => el.classList.remove('saved'), 1200);
  
      // If server returned updated groups/balances, refresh via AJAX; else fall back to reload
      if (data.groups || data.balances) {
        refreshLedgerAndBalancesDebounced();
      } else {
        refreshLedgerAndBalancesDebounced();
      }
    } catch (err) {
      el.classList.remove('saving');
      console.error('COA update failed', err);
      alert(`Account update failed: ${err && err.message ? err.message : err}`);
      // Revert UI selection if we have a prior value
      const prevVal = el.getAttribute('data-prev');
      if (prevVal) el.value = prevVal;
    } finally {
      el.disabled = false;
    }
  });

// -----------------------------
// Misc helpers
// -----------------------------
function autoCalcTotal(rowPrefix) {
  const qEl = document.querySelector(rowPrefix + ' input[name="quantity"]');
  const pEl = document.querySelector(rowPrefix + ' input[name="price"]');
  const fEl = document.querySelector(rowPrefix + ' input[name="fee"]');
  if (!qEl || !pEl || !fEl) return;
  const qty = parseFloat(qEl.value) || 0;
  const price = parseFloat(pEl.value) || 0;
  const fee = parseFloat(fEl.value) || 0;
  const total = (qty * price) - fee;
  const tEl = document.querySelector(rowPrefix + ' input[name="total_value"]');
  if (tEl) tEl.value = isNaN(total) ? '' : total.toFixed(2);
}

// -----------------------------
// DOMContentLoaded wiring
// -----------------------------
document.addEventListener("DOMContentLoaded", function() {
  // Initialize sort indicators to stored/URL state
  updateSortIndicators();

  // Bind BOTH header rows (all .sortable)
  document.querySelectorAll('.sortable').forEach(function(th) {
    th.addEventListener('click', function() {
      const col = th.dataset.col;
      // Update state and perform client-side sort immediately for responsiveness
      sortLedgerTable(col);
      // Optionally prompt server to return canonically sorted groups for consistency
      refreshLedgerAndBalancesDebounced();
    });
  });

  // Master "Collapse all" checkbox (if present)
  const collapseAllEl = document.getElementById('collapse-all');
  if (collapseAllEl) {
    collapseAllEl.addEventListener('change', () => {
      setAllCollapsed(collapseAllEl.checked).catch(err => {
        console.warn('collapse_all route failed; falling back per-group:', err);
        const expanded = !collapseAllEl.checked;
        const toggles = Array.from(document.querySelectorAll('.toggle-group'));
        Promise.all(toggles.map(cb => postCollapseState(cb.dataset.groupId, expanded)))
              .then(() => location.reload())
              .catch(e => {
                console.error('Fallback per-group toggle failed', e);
                alert('Failed to apply collapse/expand to all rows.');
              });
      });
    });
  }

  // Auto-calc on add-entry form (if present)
  const topForm = document.querySelector('tr.row-top form[action$="add_ledger_entry_route"]');
  if (topForm) {
    ['quantity', 'price', 'fee'].forEach(function(field) {
      const el = topForm.querySelector('input[name="' + field + '"]');
      if (el) el.addEventListener('input', function() { autoCalcTotal('tr.row-top form[action$="add_ledger_entry_route"] '); });
    });
  }

  // COA Mapping button safety (HTML already has onclick)
  const btnMap = document.getElementById('btn-coa-mapping');
  if (btnMap) {
    btnMap.addEventListener('click', () => {
      // fallback if inline onclick missing
      window.location.href = '/coa_mapping';
    });
  }
});
