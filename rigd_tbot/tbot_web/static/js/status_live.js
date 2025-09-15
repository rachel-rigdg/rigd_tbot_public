// tbot_web/static/js/status_live.js
document.addEventListener("DOMContentLoaded", function () {
    function setSafe(el, html) {
        if (el) el.innerHTML = html;
    }
    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }
    function setBadge(id, ok, unknownText = "—") {
        const el = document.getElementById(id);
        if (!el) return;
        if (ok === true) {
            el.textContent = "✓";
            el.style.color = "green";
            el.title = "True";
        } else if (ok === false) {
            el.textContent = "✗";
            el.style.color = "red";
            el.title = "False";
        } else {
            el.textContent = unknownText;
            el.style.color = "#666";
            el.title = "Unknown";
        }
    }

    const DEFAULTS = {
        // status.json fields
        state: "idle",
        timestamp: "",
        active_strategy: "none",
        trade_count: 0,
        win_trades: 0,
        loss_trades: 0,
        win_rate: 0,
        pnl: 0,
        error_count: 0,
        version: "n/a",
        enabled_strategies: { open: false, mid: false, close: false },
        max_risk_per_trade: 0,
        daily_loss_limit: 0,
        // server-provided extras (optional)
        supervisor: {
            scheduled: null,         // boolean
            launched: null,          // boolean
            running: null,           // boolean
            failed: null,            // boolean
            scheduled_at: null,      // ISO string
            launched_at: null        // ISO string
        },
        schedule: null              // object from logs/schedule.json (optional)
    };

    let lastData = null;

    async function pollBotStatus() {
        try {
            const resp = await fetch('/status/api/full_status', { cache: "no-store" });
            if (!resp.ok) throw new Error("HTTP not OK");
            const payload = await resp.json();
            if (!payload || Object.keys(payload).length === 0) throw new Error("Empty JSON");
            lastData = payload;
            updateUI(payload);
        } catch (e) {
            updateUI(lastData || DEFAULTS);
        }
    }

    function normalizePayload(payload) {
        // Backend may return either a flat status object or {status, schedule, supervisor}
        const status = payload.status ? payload.status : payload;
        const schedule = payload.schedule || null;
        const supervisor = payload.supervisor || {};

        // Merge with DEFAULTS, keeping nested merges safe
        const merged = {
            ...DEFAULTS,
            ...status,
            enabled_strategies: {
                ...DEFAULTS.enabled_strategies,
                ...(status.enabled_strategies || {})
            },
            schedule: schedule || null,
            supervisor: {
                ...DEFAULTS.supervisor,
                ...supervisor
            }
        };

        // If supervisor.scheduled is unknown, infer from presence of schedule for today (UTC)
        if (merged.supervisor.scheduled === null) {
            const sch = merged.schedule;
            if (sch && sch.trading_date) {
                try {
                    const todayUtc = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
                    merged.supervisor.scheduled = (sch.trading_date === todayUtc);
                } catch {
                    merged.supervisor.scheduled = null;
                }
            }
        }
        // If scheduled_at unknown but schedule exists, expose created_at_utc
        if (!merged.supervisor.scheduled_at && merged.schedule && merged.schedule.created_at_utc) {
            merged.supervisor.scheduled_at = merged.schedule.created_at_utc;
        }

        return merged;
    }

    function updateSupervisorBanners(merged) {
        const sup = merged.supervisor || DEFAULTS.supervisor;

        setBadge("banner-scheduled", sup.scheduled);
        setBadge("banner-launched", sup.launched);
        setBadge("banner-running", sup.running);
        setBadge("banner-failed", sup.failed);

        // Optional timestamps (if you later add spans with these IDs in the template)
        // setText("banner-scheduled-at", sup.scheduled_at || "—");
        // setText("banner-launched-at", sup.launched_at || "—");
    }

    function updateUI(payload) {
        const d = normalizePayload(payload);
        const grids = document.querySelectorAll('.status-grid');

        // --- Supervisor banners (new) ---
        updateSupervisorBanners(d);

        // --- Primary status grid ---
        if (grids[0]) {
            setSafe(
                grids[0].children[0],
                `<strong>Bot State:</strong> ${
                    d.state === "running"
                        ? `<span style="color:green;font-weight:bold;">RUNNING</span>`
                    : d.state === "idle"
                        ? `<span style="color:orange;font-weight:bold;">IDLE</span>`
                    : d.state === "analyzing"
                        ? `<span style="color:orange;font-weight:bold;">ANALYZING</span>`
                    : d.state === "trading"
                        ? `<span style="color:green;font-weight:bold;">TRADING</span>`
                    : d.state === "monitoring"
                        ? `<span style="color:orange;font-weight:bold;">MONITORING</span>`
                    : d.state === "updating"
                        ? `<span style="color:orange;font-weight:bold;">UPDATING</span>`
                    : d.state === "graceful_closing_positions"
                        ? `<span style="color:orange;font-weight:bold;">GRACEFUL CLOSING</span>`
                    : d.state === "emergency_closing_positions"
                        ? `<span style="color:red;font-weight:bold;">EMERGENCY CLOSING</span>`
                    : d.state === "stopped"
                        ? `<span style="color:gray;">STOPPED</span>`
                    : d.state === "shutdown" || d.state === "shutdown_triggered"
                        ? `<span style="color:red;font-weight:bold;">SHUTDOWN</span>`
                    : d.state === "error"
                        ? `<span style="color:red;font-weight:bold;">ERROR</span>`
                    : `<span style="color:gray;">${d.state || "idle"}</span>`
                }`
            );

            setSafe(grids[0].children[1], `<strong>Timestamp:</strong> ${d.timestamp || "—"}`);
            setSafe(grids[0].children[2], `<strong>Active Strategy:</strong> ${d.active_strategy || "none"}`);
            setSafe(grids[0].children[3], `<strong>Trade Count:</strong> ${Number.isFinite(d.trade_count) ? d.trade_count : 0}`);
            setSafe(grids[0].children[4], `<strong>Win Trades:</strong> ${Number.isFinite(d.win_trades) ? d.win_trades : 0}`);
            setSafe(grids[0].children[5], `<strong>Loss Trades:</strong> ${Number.isFinite(d.loss_trades) ? d.loss_trades : 0}`);
            setSafe(grids[0].children[6], `<strong>Win Rate:</strong> ${(Number.isFinite(d.win_rate) ? d.win_rate : 0)}%`);
            setSafe(grids[0].children[7], `<strong>PnL:</strong> ${Number.isFinite(d.pnl) ? d.pnl : 0}`);
            setSafe(grids[0].children[8], `<strong>Error Count:</strong> ${Number.isFinite(d.error_count) ? d.error_count : 0}`);
            setSafe(grids[0].children[9], `<strong>Version:</strong> ${d.version || "n/a"}`);
        }

        // --- Strategy toggles grid ---
        if (grids[1]) {
            const es = d.enabled_strategies || DEFAULTS.enabled_strategies;
            setSafe(grids[1].children[0], `<strong>Open:</strong> ${String(es.open)}`);
            setSafe(grids[1].children[1], `<strong>Mid:</strong> ${String(es.mid)}`);
            setSafe(grids[1].children[2], `<strong>Close:</strong> ${String(es.close)}`);
        }

        // --- Risk controls grid ---
        if (grids[2]) {
            setSafe(grids[2].children[0], `<strong>Max Risk per Trade:</strong> ${Number.isFinite(d.max_risk_per_trade) ? d.max_risk_per_trade : 0}`);
            setSafe(grids[2].children[1], `<strong>Daily Loss Limit:</strong> ${Number.isFinite(d.daily_loss_limit) ? d.daily_loss_limit : 0}`);
        }
    }

    // Poll every 60s
    setInterval(pollBotStatus, 60000);
    // Initial fetch
    pollBotStatus();
});
