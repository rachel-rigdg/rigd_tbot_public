document.addEventListener("DOMContentLoaded", function () {
    function setSafe(el, html) {
        if (el) el.innerHTML = html;
    }
    let lastData = null;
    async function pollBotStatus() {
        try {
            const resp = await fetch('/status/api/bot_state', {cache: "no-store"});
            if (!resp.ok) return;
            const data = await resp.json();
            lastData = data;
            const grids = document.querySelectorAll('.status-grid');
            if (grids[0]) {
                setSafe(grids[0].children[0], `<strong>Timestamp:</strong> ${data.timestamp || ""}`);
                setSafe(grids[0].children[1], `<strong>Bot State:</strong> ${data.state || ""}`);
                setSafe(grids[0].children[2], `<strong>Active Strategy:</strong> ${data.active_strategy || ""}`);
                setSafe(grids[0].children[3], `<strong>Trade Count:</strong> ${data.trade_count || ""}`);
                setSafe(grids[0].children[4], `<strong>Win Trades:</strong> ${data.win_trades || ""}`);
                setSafe(grids[0].children[5], `<strong>Loss Trades:</strong> ${data.loss_trades || ""}`);
                setSafe(grids[0].children[6], `<strong>Win Rate:</strong> ${data.win_rate || ""}%`);
                setSafe(grids[0].children[7], `<strong>PnL:</strong> ${data.pnl || ""}`);
                setSafe(grids[0].children[8], `<strong>Error Count:</strong> ${data.error_count || ""}`);
                setSafe(grids[0].children[9], `<strong>Version:</strong> ${data.version || ""}`);
                setSafe(grids[0].children[10],
                    `<strong>Running State:</strong> ${
                        data.state === "running"
                        ? `<span style="color:green;font-weight:bold;">RUNNING</span>`
                        : data.state === "idle"
                            ? `<span style="color:orange;font-weight:bold;">IDLE</span>`
                            : `<span style="color:gray;">${data.state || ""}</span>`
                    }`
                );
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
        } catch (e) {
            if (lastData) {
                const grids = document.querySelectorAll('.status-grid');
                if (grids[0]) {
                    setSafe(grids[0].children[0], `<strong>Timestamp:</strong> ${lastData.timestamp || ""}`);
                    setSafe(grids[0].children[1], `<strong>Bot State:</strong> ${lastData.state || ""}`);
                    setSafe(grids[0].children[2], `<strong>Active Strategy:</strong> ${lastData.active_strategy || ""}`);
                    setSafe(grids[0].children[3], `<strong>Trade Count:</strong> ${lastData.trade_count || ""}`);
                    setSafe(grids[0].children[4], `<strong>Win Trades:</strong> ${lastData.win_trades || ""}`);
                    setSafe(grids[0].children[5], `<strong>Loss Trades:</strong> ${lastData.loss_trades || ""}`);
                    setSafe(grids[0].children[6], `<strong>Win Rate:</strong> ${lastData.win_rate || ""}%`);
                    setSafe(grids[0].children[7], `<strong>PnL:</strong> ${lastData.pnl || ""}`);
                    setSafe(grids[0].children[8], `<strong>Error Count:</strong> ${lastData.error_count || ""}`);
                    setSafe(grids[0].children[9], `<strong>Version:</strong> ${lastData.version || ""}`);
                    setSafe(grids[0].children[10],
                        `<strong>Running State:</strong> ${
                            lastData.state === "running"
                            ? `<span style="color:green;font-weight:bold;">RUNNING</span>`
                            : lastData.state === "idle"
                                ? `<span style="color:orange;font-weight:bold;">IDLE</span>`
                                : `<span style="color:gray;">${lastData.state || ""}</span>`
                        }`
                    );
                }
                if (grids[1] && lastData.enabled_strategies) {
                    setSafe(grids[1].children[0], `<strong>Open:</strong> ${lastData.enabled_strategies.open}`);
                    setSafe(grids[1].children[1], `<strong>Mid:</strong> ${lastData.enabled_strategies.mid}`);
                    setSafe(grids[1].children[2], `<strong>Close:</strong> ${lastData.enabled_strategies.close}`);
                }
                if (grids[2]) {
                    setSafe(grids[2].children[0], `<strong>Max Risk per Trade:</strong> ${lastData.max_risk_per_trade || ""}`);
                    setSafe(grids[2].children[1], `<strong>Daily Loss Limit:</strong> ${lastData.daily_loss_limit || ""}`);
                }
            }
        }
    }
    setInterval(pollBotStatus, 2000);
    pollBotStatus();
});
