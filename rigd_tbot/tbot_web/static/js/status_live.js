// tbot_web/static/js/status_live.js
// Polls /status/api/bot_state and refreshes all status fields on status.html

document.addEventListener("DOMContentLoaded", function () {
    const grid = document.querySelectorAll('.status-grid')[0];
    const runningDiv = document.querySelectorAll('.status-grid div')[10];

    async function pollBotStatus() {
        try {
            const resp = await fetch('/status/api/bot_state', {cache: "no-store"});
            if (!resp.ok) return;
            const data = await resp.json();

            // Defensive checks in case template changes
            if (grid && data) {
                grid.children[0].innerHTML  = `<strong>Timestamp:</strong> ${data.timestamp || ""}`;
                grid.children[1].innerHTML  = `<strong>Bot State:</strong> ${data.state || ""}`;
                grid.children[2].innerHTML  = `<strong>Active Strategy:</strong> ${data.active_strategy || ""}`;
                grid.children[3].innerHTML  = `<strong>Trade Count:</strong> ${data.trade_count || ""}`;
                grid.children[4].innerHTML  = `<strong>Win Trades:</strong> ${data.win_trades || ""}`;
                grid.children[5].innerHTML  = `<strong>Loss Trades:</strong> ${data.loss_trades || ""}`;
                grid.children[6].innerHTML  = `<strong>Win Rate:</strong> ${data.win_rate || ""}%`;
                grid.children[7].innerHTML  = `<strong>PnL:</strong> ${data.pnl || ""}`;
                grid.children[8].innerHTML  = `<strong>Error Count:</strong> ${data.error_count || ""}`;
                grid.children[9].innerHTML  = `<strong>Version:</strong> ${data.version || ""}`;
                grid.children[10].innerHTML = `<strong>Running State:</strong> ${
                    data.state === "running" ? `<span style="color:green;font-weight:bold;">RUNNING</span>` :
                    data.state === "idle" ? `<span style="color:orange;font-weight:bold;">IDLE</span>` :
                    `<span style="color:gray;">${data.state || ""}</span>`
                }`;
            }

            // Strategy toggles
            const strategyGrid = document.querySelectorAll('.status-grid')[1];
            if (strategyGrid && data.enabled_strategies) {
                strategyGrid.children[0].innerHTML = `<strong>Open:</strong> ${data.enabled_strategies.open}`;
                strategyGrid.children[1].innerHTML = `<strong>Mid:</strong> ${data.enabled_strategies.mid}`;
                strategyGrid.children[2].innerHTML = `<strong>Close:</strong> ${data.enabled_strategies.close}`;
            }

            // Risk controls
            const riskGrid = document.querySelectorAll('.status-grid')[2];
            if (riskGrid) {
                riskGrid.children[0].innerHTML = `<strong>Max Risk per Trade:</strong> ${data.max_risk_per_trade || ""}`;
                riskGrid.children[1].innerHTML = `<strong>Daily Loss Limit:</strong> ${data.daily_loss_limit || ""}`;
            }
        } catch (e) {
            // silent
        }
    }

    setInterval(pollBotStatus, 2000);
    pollBotStatus();
});
