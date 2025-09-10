document.addEventListener("DOMContentLoaded", function () {
    function setSafe(el, html) {
        if (el) el.innerHTML = html;
    }
    let lastData = null;
    async function pollBotStatus() {
        try {
            const resp = await fetch('/status/api/full_status', {cache: "no-store"});
            if (!resp.ok) throw new Error("HTTP not OK");
            const data = await resp.json();
            if (!data || Object.keys(data).length === 0) throw new Error("Empty JSON");
            lastData = data;
            updateUI(data);
        } catch (e) {
            if (lastData) {
                updateUI(lastData);
            }
        }
    }
    function updateUI(data) {
        const grids = document.querySelectorAll('.status-grid');
        if (grids[0]) {

            setSafe(grids[0].children[0],
               `<strong>Bot State:</strong> ${
                    data.state === "running"
                        ? `<span style="color:green;font-weight:bold;">RUNNING</span>`
                    : data.state === "idle"
                        ? `<span style="color:orange;font-weight:bold;">IDLE</span>`
                    : data.state === "analyzing"
                        ? `<span style="color:orange;font-weight:bold;">ANALYZING</span>`
                    : data.state === "trading"
                        ? `<span style="color:green;font-weight:bold;">TRADING</span>`
                    : data.state === "monitoring"
                        ? `<span style="color:orange;font-weight:bold;">MONITORING</span>`
                    : data.state === "updating"
                        ? `<span style="color:orange;font-weight:bold;">UPDATING</span>`
                    : data.state === "graceful_closing_positions"
                        ? `<span style="color:orange;font-weight:bold;">GRACEFUL CLOSING</span>`
                    : data.state === "emergency_closing_positions"
                        ? `<span style="color:red;font-weight:bold;">EMERGENCY CLOSING</span>`
                    : data.state === "stopped"
                        ? `<span style="color:gray;">STOPPED</span>`
                    : data.state === "shutdown" || data.state === "shutdown_triggered"
                        ? `<span style="color:red;font-weight:bold;">SHUTDOWN</span>`
                    : data.state === "error"
                        ? `<span style="color:red;font-weight:bold;">ERROR</span>`
                    : `<span style="color:gray;">${data.state || ""}</span>`
                }`
            );
            
            setSafe(grids[0].children[1], `<strong>Timestamp:</strong> ${data.timestamp || ""}`);
            setSafe(grids[0].children[2], `<strong>Active Strategy:</strong> ${data.active_strategy || ""}`);
            setSafe(grids[0].children[3], `<strong>Trade Count:</strong> ${data.trade_count || ""}`);
            setSafe(grids[0].children[4], `<strong>Win Trades:</strong> ${data.win_trades || ""}`);
            setSafe(grids[0].children[5], `<strong>Loss Trades:</strong> ${data.loss_trades || ""}`);
            setSafe(grids[0].children[6], `<strong>Win Rate:</strong> ${data.win_rate || ""}%`);
            setSafe(grids[0].children[7], `<strong>PnL:</strong> ${data.pnl || ""}`);
            setSafe(grids[0].children[8], `<strong>Error Count:</strong> ${data.error_count || ""}`);
            setSafe(grids[0].children[9], `<strong>Version:</strong> ${data.version || ""}`);
            
        }
        if (grids[1] && data.enabled_strategies) {
            setSafe(grids[1].children[0], `<strong>Open:</strong> ${data.enabled_strategies.open}`);
            setSafe(grids[1].children[1], `<strong>Mid:</strong> ${data.enabled_strategies.mid}`);
            setSafe(grids[1].children[2], `<strong>Close:</strong> ${data.enabled_strategies.close}`);
        }
        if (grids[2]) {
            setSafe(grids[2].children[0], `<strong>Max Risk per Trade:</strong> ${data.max_risk_per_trade || ""}`);
            setSafe(grids[2].children[1], `<strong>Daily Loss Limit:</strong> ${data.daily_loss_limit || ""}`);
        }
    }
    setInterval(pollBotStatus, 60000);
    pollBotStatus();
});
