// tbot_web/static/js/coa_mapping.js
// Client controller for COA Mapping UI:
// - List (filter/highlight), Create/Update (upsert), Delete (best-effort), Versions, Rollback, Import/Export hooks
// - Surfaces audit-style toasts with UTC timestamps
// NOTE: Works progressively with the markup in coa_mapping.html; absent elements are safely ignored.

(function () {
    "use strict";
  
    // --------------------------
    // Utilities
    // --------------------------
    const $ = (sel, root) => (root || document).querySelector(sel);
    const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  
    function utcNow() {
      return new Date().toISOString();
    }
  
    function toast(msg, type = "info") {
      // Minimal ephemeral banner
      let host = $("#toast-host");
      if (!host) {
        host = document.createElement("div");
        host.id = "toast-host";
        host.style.position = "fixed";
        host.style.right = "12px";
        host.style.top = "12px";
        host.style.zIndex = "9999";
        document.body.appendChild(host);
      }
      const el = document.createElement("div");
      el.textContent = `[${utcNow()}] ${msg}`;
      el.style.margin = "6px 0";
      el.style.padding = "8px 10px";
      el.style.borderRadius = "4px";
      el.style.fontSize = "12px";
      el.style.background = type === "error" ? "#4a0f12" : type === "success" ? "#0e3b26" : "#1f2633";
      el.style.color = type === "error" ? "#ffd2d6" : type === "success" ? "#c7ffe5" : "#e6eefc";
      el.style.border = "1px solid rgba(255,255,255,.15)";
      host.appendChild(el);
      setTimeout(() => el.remove(), 3500);
    }
  
    function formToJSON(form) {
      const fd = new FormData(form);
      const o = {};
      for (const [k, v] of fd.entries()) {
        o[k] = v;
      }
      return o;
    }
  
    // --------------------------
    // Context deep-link (from ledger)
    // --------------------------
    function highlightByContext() {
      const qs = new URLSearchParams(location.search);
      const ctx = {
        broker: qs.get("broker"),
        type: qs.get("type"),
        subtype: qs.get("subtype"),
        description: qs.get("description"),
        entry_id: qs.get("entry_id"),
        from: qs.get("from"),
      };
      const banner = $("#context-banner");
      if (banner && ctx.from === "ledger") {
        let msg = "Opened from Ledger";
        if (ctx.entry_id) msg += ` — entry #${ctx.entry_id}`;
        banner.textContent = msg + ". If keys match, the corresponding rule is highlighted below.";
        banner.style.display = "block";
      }
      const rows = $$(".mapping-row");
      for (const r of rows) {
        const ok =
          (!ctx.broker || r.dataset.broker === ctx.broker) &&
          (!ctx.type || r.dataset.type === ctx.type) &&
          (!ctx.subtype || r.dataset.subtype === ctx.subtype) &&
          (!ctx.description || r.dataset.description === ctx.description);
        if (ok) {
          r.classList.add("row-highlight");
          r.scrollIntoView({ behavior: "smooth", block: "center" });
          break;
        }
      }
    }
  
    // --------------------------
    // Filters
    // --------------------------
    function bindFilters() {
      const ids = ["flt-broker", "flt-type", "flt-subtype", "flt-desc"];
      function apply() {
        const fb = ($("#flt-broker")?.value || "").toLowerCase();
        const ft = ($("#flt-type")?.value || "").toLowerCase();
        const fs = ($("#flt-subtype")?.value || "").toLowerCase();
        const fd = ($("#flt-desc")?.value || "").toLowerCase();
        $$(".mapping-row").forEach((r) => {
          const v =
            (r.dataset.broker || "").toLowerCase().includes(fb) &&
            (r.dataset.type || "").toLowerCase().includes(ft) &&
            (r.dataset.subtype || "").toLowerCase().includes(fs) &&
            (r.dataset.description || "").toLowerCase().includes(fd);
          r.style.display = v ? "" : "none";
        });
      }
      ids.forEach((id) => $("#" + id)?.addEventListener("input", apply));
      $("#btn-clear-filters")?.addEventListener("click", () => {
        ids.forEach((id) => {
          const el = $("#" + id);
          if (el) el.value = "";
        });
        apply();
      });
      // Initial
      (function init() {
        if (ids.some((id) => $("#" + id))) apply();
      })();
    }
  
    // --------------------------
    // CRUD Upsert / Prefill / Delete
    // --------------------------
    function bindRowPrefill() {
      const tbody = $("#mapping-tbody");
      if (!tbody) return;
      const f = {
        broker: $("#f-broker"),
        type: $("#f-type"),
        subtype: $("#f-subtype"),
        desc: $("#f-desc"),
        debit: $("#f-debit"),
        credit: $("#f-credit"),
      };
      tbody.addEventListener("click", (ev) => {
        const tr = ev.target.closest(".mapping-row");
        if (!tr) return;
        const cells = tr.querySelectorAll("td input");
        if (cells.length >= 6) {
          if (f.broker) f.broker.value = cells[0].value || "";
          if (f.type) f.type.value = cells[1].value || "";
          if (f.subtype) f.subtype.value = cells[2].value || "";
          if (f.desc) f.desc.value = cells[3].value || "";
          if (f.debit) f.debit.value = cells[4].value || "";
          if (f.credit) f.credit.value = cells[5].value || "";
          f.debit?.focus();
        }
      });
    }
  
    function bindUpsert() {
      const form = $("#coa-mapping-form");
      if (!form) return;
      form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const body = formToJSON(form);
        fetch("/coa_mapping/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
          .then((r) => (r.ok ? r.json() : Promise.reject(r)))
          .then(() => {
            toast("Mapping upserted.", "success");
            // simple refresh to reflect updates
            location.reload();
          })
          .catch(async (err) => {
            let msg = "Upsert failed.";
            try {
              msg += " " + (await err.text());
            } catch {}
            toast(msg, "error");
          });
      });
    }
  
    // Best-effort delete: tries dedicated delete endpoint; falls back to assign with delete flag.
    function bindDelete() {
      const tbody = $("#mapping-tbody");
      if (!tbody) return;
  
      // Inject Delete buttons if a dedicated actions column is not present
      (function injectButtons() {
        const rows = $$(".mapping-row", tbody);
        rows.forEach((tr) => {
          const lastTd = tr.lastElementChild;
          if (!lastTd) return;
          if (lastTd.querySelector(".btn-delete")) return; // already injected
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "btn btn-danger btn-sm btn-delete";
          btn.textContent = "Delete";
          btn.style.marginLeft = "6px";
          lastTd.appendChild(btn);
        });
      })();
  
      tbody.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".btn-delete");
        if (!btn) return;
        const tr = ev.target.closest(".mapping-row");
        if (!tr) return;
        const cells = tr.querySelectorAll("td input");
        if (cells.length < 4) return;
  
        const payload = {
          broker: cells[0].value || "",
          type: cells[1].value || "",
          subtype: cells[2].value || "",
          description: cells[3].value || "",
          reason: "delete",
          deleted: true,
        };
        if (!confirm(`Delete mapping for ${payload.broker} / ${payload.type} / ${payload.subtype}?`)) return;
  
        // Try dedicated endpoint first
        fetch("/coa_mapping/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
          .then((r) => {
            if (r.status === 404) throw new Error("fallback");
            if (!r.ok) throw r;
            return r.json();
          })
          .then(() => {
            toast("Mapping deleted.", "success");
            location.reload();
          })
          .catch(() => {
            // Fallback: some servers accept delete signal via assign route
            fetch("/coa_mapping/assign", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            })
              .then((r) => (r.ok ? r.json() : Promise.reject(r)))
              .then(() => {
                toast("Mapping deleted (fallback).", "success");
                location.reload();
              })
              .catch(() => toast("Delete failed.", "error"));
          });
      });
    }
  
    // --------------------------
    // Versions & Rollback
    // --------------------------
    function loadVersions() {
      const list = $("#versions-list");
      if (!list) return;
      fetch("/coa_mapping/versions")
        .then((r) => (r.ok ? r.json() : Promise.reject(r)))
        .then((history) => {
          list.innerHTML = "";
          (history || []).forEach((v) => {
            const li = document.createElement("li");
            const left = document.createElement("div");
            left.innerHTML = `<strong>v${v.version || ""}</strong><br><small>${v.timestamp_utc || ""}</small>`;
            const btn = document.createElement("button");
            btn.className = "btn btn-warning btn-sm";
            btn.textContent = "Rollback";
            btn.addEventListener("click", () => doRollback(v.version));
            li.appendChild(left);
            li.appendChild(btn);
            list.appendChild(li);
          });
        })
        .catch(() => {
          list.innerHTML = '<li><small>Failed to load versions.</small></li>';
        });
    }
  
    function doRollback(version) {
      const fd = new FormData();
      fd.append("version", version);
      fetch("/coa_mapping/rollback", { method: "POST", body: fd })
        .then((r) => (r.ok ? r.json() : Promise.reject(r)))
        .then(() => {
          toast(`Rolled back to v${version}.`, "success");
          location.reload();
        })
        .catch(() => toast("Rollback failed.", "error"));
    }
  
    // --------------------------
    // Import / Export helpers
    // --------------------------
    function bindImport() {
      const form = document.querySelector('form[action$="/coa_mapping/import"]');
      if (!form) return;
      form.addEventListener("submit", () => {
        toast("Importing mapping table…");
      });
    }
    function bindExport() {
      const form = document.querySelector('form[action$="/coa_mapping/export"]');
      if (!form) return;
      form.addEventListener("submit", () => {
        toast("Exporting mapping table…");
      });
    }
  
    // --------------------------
    // Wire up
    // --------------------------
    document.addEventListener("DOMContentLoaded", function () {
      highlightByContext();
      bindFilters();
      bindRowPrefill();
      bindUpsert();
      bindDelete();
      loadVersions();
      bindImport();
      bindExport();
    });
  })();
  