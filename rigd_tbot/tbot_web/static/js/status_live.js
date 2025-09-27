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
        schedule: null,             // object from logs/schedule.json (optional)

        // (surgical) new fields surfaced by backend for UI clarity
        test_mode_active: false,
        test_mode_banner: "",
        universe_size: null,
        universe_warning: "",
        screener_provider: { name: "NONE", enabled: false },

        // clocks
        market_tz: "America/New_York"
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
        const market_tz = payload.market_tz || status.market_tz || DEFAULTS.market_tz;

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
            },
            market_tz
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

    // (surgical) new UI: test mode badge, universe size warning, provider state
    function updateClarityBadges(d) {
        // TEST MODE badge
        const testEl = document.getElementById("badge-testmode");
        if (testEl) {
            if (d.test_mode_active) {
                testEl.textContent = d.test_mode_banner || "TEST MODE";
                testEl.style.display = "inline-block";
                testEl.style.padding = "2px 6px";
                testEl.style.borderRadius = "4px";
                testEl.style.background = "#8b0000";
                testEl.style.color = "#fff";
                testEl.title = "Global test flag detected";
            } else {
                testEl.textContent = "";
                testEl.style.display = "none";
            }
        }

        // Universe size + warning
        const uniEl = document.getElementById("universe-size");
        if (uniEl) {
            const size = (typeof d.universe_size === "number") ? d.universe_size : "—";
            uniEl.textContent = `Universe: ${size}`;
            if (d.universe_warning && typeof d.universe_size === "number") {
                uniEl.style.color = "red";
                uniEl.title = d.universe_warning;
            } else {
                uniEl.style.color = "";
                uniEl.title = "";
            }
        }

        // Provider state
        const provEl = document.getElementById("provider-state");
        if (provEl) {
            const prov = d.screener_provider || DEFAULTS.screener_provider;
            const name = prov.name || "NONE";
            const status = prov.enabled ? "enabled" : "disabled";
            provEl.textContent = `Provider: ${name} (${status})`;
            provEl.style.color = prov.enabled ? "green" : "#666";
            provEl.title = prov.enabled ? "Active data provider" : "Provider disabled or not configured";
        }
    }

    // ---- Clock formatting helpers ----
    function _pad2(n) { return String(n).padStart(2, '0'); }

    // "YYYY-MM-DD, HH:MM" in a given IANA tz
    function fmtYMDHM(dateObj, tz) {
        const parts = new Intl.DateTimeFormat(undefined, {
            timeZone: tz,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        }).formatToParts(dateObj);
        const get = (t) => parts.find(p => p.type === t)?.value;
        // Many locales output MM/DD/YYYY — assemble explicitly
        const y = get('year');
        const m = get('month');
        const d = get('day');
        const hh = get('hour');
        const mm = get('minute');
        return `${y}-${m}-${d}, ${hh}:${mm}`;
    }

    // "h:mm A" in a given tz (or local if tz undefined)
    function fmtHMAm(dateObj, tz) {
        const parts = new Intl.DateTimeFormat(undefined, {
            timeZone: tz,
            hour: 'numeric',
            minute: '2-digit',
            hour12: true
        }).formatToParts(dateObj);
        const h = parts.find(p => p.type === 'hour')?.value || '';
        const m = parts.find(p => p.type === 'minute')?.value || '';
        let dayPeriod = parts.find(p => p.type === 'dayPeriod')?.value || '';
        dayPeriod = dayPeriod.toUpperCase();
        return `${h}:${m} ${dayPeriod}`;
    }

    function updateClocks(d) {
        const now = new Date();
        const marketTz = d.market_tz || DEFAULTS.market_tz;

        // #clock-utc: absolute UTC, no DST adjustment on UTC
        const utcStr = fmtYMDHM(now, 'UTC');
        setText('clock-utc', utcStr);

        // #clock-market: "YYYY-MM-DD, HH:MM UTC, h:mm A"
        // First part: market time expressed in UTC (same instant formatted in UTC)
        const marketUtcStr = fmtYMDHM(now, 'UTC');
        const marketLocalStr = fmtHMAm(now, marketTz);
        setText('clock-market', `${marketUtcStr} UTC, ${marketLocalStr}`);

        // #clock-local: "YYYY-MM-DD, HH:MM UTC, h:mm A"
        // First part: your local machine time expressed in UTC; Second: pure local wall time
        const localUtcStr = fmtYMDHM(now, 'UTC');
        const localLocalStr = fmtHMAm(now, undefined);
        setText('clock-local', `${localUtcStr} UTC, ${localLocalStr}`);
    }

    function updateUI(payload) {
        const d = normalizePayload(payload);

        // --- Supervisor banners (new) ---
        updateSupervisorBanners(d);

        // --- Clarity badges (new) ---
        updateClarityBadges(d);

        // --- Clock bar (new) ---
        updateClocks(d);

        // --- Primary status grid (ID-based) ---
        const runtimeGrid = document.getElementById('grid-runtime');
        if (runtimeGrid && runtimeGrid.children && runtimeGrid.children.length >= 10) {
            setSafe(
                runtimeGrid.children[0],
                `<strong>Running State:</strong> ${
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

            setSafe(runtimeGrid.children[1], `<strong>Timestamp:</strong> ${d.timestamp || "—"}`);
            setSafe(runtimeGrid.children[2], `<strong>Active Strategy:</strong> ${d.active_strategy || "none"}`);
            setSafe(runtimeGrid.children[3], `<strong>Trade Count:</strong> ${Number.isFinite(d.trade_count) ? d.trade_count : 0}`);
            setSafe(runtimeGrid.children[4], `<strong>Win Trades:</strong> ${Number.isFinite(d.win_trades) ? d.win_trades : 0}`);
            setSafe(runtimeGrid.children[5], `<strong>Loss Trades:</strong> ${Number.isFinite(d.loss_trades) ? d.loss_trades : 0}`);
            setSafe(runtimeGrid.children[6], `<strong>Win Rate:</strong> ${(Number.isFinite(d.win_rate) ? d.win_rate : 0)}%`);
            setSafe(runtimeGrid.children[7], `<strong>PnL:</strong> ${Number.isFinite(d.pnl) ? d.pnl : 0}`);
            setSafe(runtimeGrid.children[8], `<strong>Error Count:</strong> ${Number.isFinite(d.error_count) ? d.error_count : 0}`);
            setSafe(runtimeGrid.children[9], `<strong>Version:</strong> ${d.version || "n/a"}`);
        }

        // --- Risk controls grid (ID-based) ---
        const riskGrid = document.getElementById('grid-risk');
        if (riskGrid && riskGrid.children && riskGrid.children.length >= 2) {
            setSafe(riskGrid.children[0], `<strong>Max Risk per Trade:</strong> ${Number.isFinite(d.max_risk_per_trade) ? d.max_risk_per_trade : 0}`);
            setSafe(riskGrid.children[1], `<strong>Daily Loss Limit:</strong> ${Number.isFinite(d.daily_loss_limit) ? d.daily_loss_limit : 0}`);
        }

        // Note: Strategy Toggles grid removed (no updates performed here).
    }

    // Poll every 30s
    setInterval(pollBotStatus, 30000);
    // Initial fetch
    pollBotStatus();
});
