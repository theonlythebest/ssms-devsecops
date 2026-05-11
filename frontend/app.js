// SSMS dashboard frontend.
(() => {
    const API = "";
    const REFRESH_MS = 15000;
    let token = null;
    let role = null;

    const $ = (id) => document.getElementById(id);
    const fmt = (n) => "€" + Number(n || 0).toFixed(2);
    const pct = (n) => (Number(n || 0) * 100).toFixed(1) + "%";

    async function get(path) {
        const headers = {};
        if (token) headers.Authorization = "Bearer " + token;
        const res = await fetch(API + path, { headers });
        if (!res.ok) throw new Error(res.status + " " + path);
        return res.json();
    }

    async function post(path, body) {
        const headers = { "Content-Type": "application/json" };
        const res = await fetch(API + path, { method: "POST", headers, body: JSON.stringify(body) });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || (res.status + " " + path));
        return data;
    }

    function setLastUpdate() {
        $("last-update").textContent = "updated " + new Date().toLocaleTimeString();
    }

    $("btn-login").addEventListener("click", async () => {
        const u = $("auth-username").value.trim();
        const p = $("auth-password").value;
        try {
            const body = new URLSearchParams();
            body.append("username", u);
            body.append("password", p);
            const res = await fetch(API + "/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: body.toString(),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Login failed");
            token = data.access_token;
            role = data.role;
            $("auth-status").textContent = "Logged in as " + data.username + " (" + data.role + ")";
            $("auth-status").className = "badge ok";
        } catch (e) {
            $("auth-status").textContent = "Error: " + e.message;
            $("auth-status").className = "badge crit";
        }
    });

    function renderSummary(s) {
        $("kpi-revenue").textContent = fmt(s.total_revenue);
        $("kpi-sales").textContent = s.total_sales + " sales";
        $("kpi-expired").textContent = s.expired_products;
        $("kpi-near").textContent = s.near_expiry_products + " near-expiry";
        $("kpi-lowstock").textContent = s.low_stock_alerts;
        $("kpi-orders").textContent = s.web_orders;
        $("kpi-web-revenue").textContent = fmt(s.web_revenue);
        $("kpi-anomalies").textContent = s.anomaly_count;
        $("kpi-open-alerts").textContent = s.open_alerts + " open alerts";
        const sec = $("security-status");
        sec.textContent = "SECURITY: " + s.security_status;
        sec.className = "badge " + (s.security_status === "OK" ? "ok" : "crit");
    }

    function renderSOC(events, counts) {
        if (counts) {
            $("soc-count-critical").textContent = counts.critical || 0;
            $("soc-count-warning").textContent = counts.warning || 0;
            $("soc-count-info").textContent = counts.info || 0;
        }
        const tbody = $("soc-events").querySelector("tbody");
        tbody.innerHTML = "";
        if (!events.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="muted">No SOC events. System nominal.</td></tr>';
            return;
        }
        events.forEach((a) => {
            const tr = document.createElement("tr");
            tr.className = "sev-" + a.severity;
            const ts = new Date(a.created_at).toLocaleTimeString();
            const date = new Date(a.created_at).toLocaleDateString();
            tr.innerHTML =
                '<td title="' + date + " " + ts + '">' + ts + '</td>' +
                '<td class="cat"><span class="soc-cat-pill soc-cat-' + a.category + '">' + a.category + '</span></td>' +
                '<td class="sev">' + a.severity + '</td>' +
                '<td>' + a.message + '</td>';
            tbody.appendChild(tr);
        });
    }

    function renderOrders(orders) {
        const tbody = $("orders-table").querySelector("tbody");
        tbody.innerHTML = "";
        orders.slice(0, 8).forEach((o) => {
            tbody.insertAdjacentHTML("beforeend",
                '<tr><td>' + o.public_id + '</td><td>' + o.status + '</td><td>' + fmt(o.total) +
                '</td><td>' + new Date(o.created_at).toLocaleString() + '</td></tr>');
        });
    }

    function renderStock(items) {
        const tbody = $("stock-table").querySelector("tbody");
        tbody.innerHTML = "";
        const filtered = items.filter((i) => i.is_expired || i.is_near_expiry || i.is_low_stock);
        const sorted = filtered.sort((a, b) => (a.days_remaining ?? 999) - (b.days_remaining ?? 999));
        sorted.slice(0, 12).forEach((i) => {
            let flag = '<span class="flag-ok">ok</span>';
            if (i.is_expired) flag = '<span class="flag-expired">EXPIRED</span>';
            else if (i.is_near_expiry) flag = '<span class="flag-near">near-expiry</span>';
            else if (i.is_low_stock) flag = '<span class="flag-low">low stock</span>';
            tbody.insertAdjacentHTML("beforeend",
                '<tr><td>' + i.name + '</td><td>' + i.quantity + '</td><td>' + (i.expiry_date || "-") +
                '</td><td>' + (i.days_remaining ?? "-") + '</td><td>' + flag + '</td></tr>');
        });
        if (!sorted.length) tbody.innerHTML = '<tr><td colspan="5" class="muted">No critical items.</td></tr>';
    }

    function renderActivity(logs) {
        const tbody = $("activity-table").querySelector("tbody");
        tbody.innerHTML = "";
        if (!logs.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="muted">No activity yet.</td></tr>';
            return;
        }
        logs.forEach((l) => {
            const ts = new Date(l.timestamp).toLocaleTimeString();
            const cls = l.action === "sell" ? "flag-near" : "flag-ok";
            const sign = l.quantity_change > 0 ? "+" + l.quantity_change : l.quantity_change;
            tbody.insertAdjacentHTML("beforeend",
                '<tr><td>' + ts + '</td><td>' + l.product_name + '</td>' +
                '<td class="' + cls + '">' + l.action.toUpperCase() + " (" + sign + ')</td>' +
                '<td>' + l.quantity_after + '</td>' +
                '<td>' + (l.username || "-") + '</td>' +
                '<td class="muted">' + (l.barcode || "-") + '</td></tr>');
        });
    }

    async function refreshActivity() {
        try { renderActivity(await get("/inventory/logs?limit=15")); }
        catch (e) { console.error("activity refresh failed", e); }
    }

    let lastRtSnapshot = null;
    let lastFeedIds = new Set();

    function pulse(id) {
        const el = $(id); if (!el) return;
        el.classList.add("pulse");
        setTimeout(() => el.classList.remove("pulse"), 700);
    }

    function flashCard(id) {
        const wrap = document.getElementById(id) && document.getElementById(id).closest(".card");
        if (!wrap) return;
        wrap.classList.remove("flash"); void wrap.offsetWidth;
        wrap.classList.add("flash");
    }

    function popDelta(id, delta, formatter) {
        if (!delta || Math.abs(delta) < 1e-9) return;
        const el = $(id); if (!el) return;
        const sign = delta > 0 ? "+" : "-";
        el.textContent = sign + formatter(Math.abs(delta));
        el.style.color = delta > 0 ? "#22c55e" : "#ef4444";
        el.style.background = delta > 0 ? "rgba(34,197,94,.15)" : "rgba(239,68,68,.15)";
        el.style.borderColor = delta > 0 ? "rgba(34,197,94,.45)" : "rgba(239,68,68,.45)";
        el.classList.remove("show"); void el.offsetWidth;
        el.classList.add("show");
    }

    function renderRealtime(rt) {
        let dMin = 0, dHour = 0, dRev = 0, dRate = 0;
        if (lastRtSnapshot) {
            dMin = rt.sales_last_minute - lastRtSnapshot.min;
            dHour = rt.sales_last_hour - lastRtSnapshot.hour;
            dRev = rt.revenue_last_hour - lastRtSnapshot.rev;
            dRate = rt.scans_per_minute - lastRtSnapshot.rate;
        }
        if (dMin !== 0) { pulse("live-card-min"); popDelta("delta-min", dMin, (v) => v.toFixed(0)); }
        if (dHour !== 0) { pulse("live-card-hour"); popDelta("delta-hour", dHour, (v) => v.toFixed(0)); }
        if (Math.abs(dRev) > 1e-9) { pulse("live-card-rev"); popDelta("delta-rev", dRev, (v) => "€" + v.toFixed(2)); }
        if (Math.abs(dRate) > 1e-9) { pulse("live-card-rate"); popDelta("delta-rate", dRate, (v) => v.toFixed(2)); }

        $("rt-last-min").textContent = rt.sales_last_minute;
        $("rt-last-hour").textContent = rt.sales_last_hour;
        $("rt-rev-hour").textContent = fmt(rt.revenue_last_hour);
        $("rt-rate").textContent = rt.scans_per_minute.toFixed(2);

        lastRtSnapshot = { min: rt.sales_last_minute, hour: rt.sales_last_hour,
                           rev: rt.revenue_last_hour, rate: rt.scans_per_minute };

        const feed = $("live-feed");
        feed.innerHTML = "";
        const seen = new Set();
        let hasFresh = false;
        rt.latest_sales.forEach((s) => {
            seen.add(s.id);
            const isFresh = lastFeedIds.size > 0 && !lastFeedIds.has(s.id);
            if (isFresh) hasFresh = true;
            const ts = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : "-";
            const extras = s.item_count > 1 ? " (+" + (s.item_count - 1) + ")" : "";
            const div = document.createElement("div");
            div.className = "feed-item" + (isFresh ? " fresh" : "");
            div.innerHTML =
                '<div class="ts">' + ts + '</div>' +
                '<div><strong>' + s.products + '</strong>' + extras +
                ' <span style="color:var(--muted);">' + s.cashier + '</span></div>' +
                '<div class="total">' + fmt(s.total) + '</div>';
            feed.appendChild(div);
        });
        if (!rt.latest_sales.length) {
            feed.innerHTML = '<div class="muted" style="padding:10px 0;">No sales yet.</div>';
        }
        if (hasFresh) flashCard("live-feed");
        lastFeedIds = seen;
    }

    async function refreshAnalytics() {
        try { renderRealtime(await get("/analytics/realtime")); }
        catch (e) { console.error("analytics refresh failed", e); }
    }

    // ===== Promotions: analytics-style cards =====
    function discountSeverity(pct) {
        if (pct >= 50) return "crit";
        if (pct >= 30) return "warn";
        return "info";
    }
    function daysSeverity(days) {
        if (days <= 1) return "urgent";
        if (days <= 3) return "soon";
        return "calm";
    }
    function escapeHTML(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[c]));
    }

    function renderPromotions(d) {
        // ----- Near-expiry discounts -----
        const discounts = d.discounts || [];
        $("promo-count-discounts").textContent = discounts.length;
        const dGrid = $("promo-discounts");
        dGrid.innerHTML = "";
        if (!discounts.length) {
            dGrid.innerHTML = '<div class="promo-empty">No near-expiry products. Inventory is healthy.</div>';
        } else {
            discounts.forEach((x) => {
                const dSev = discountSeverity(x.suggested_discount_pct);
                const dayCls = daysSeverity(x.days_left);
                const dayLabel = x.days_left <= 0 ? "expires today" :
                                 x.days_left === 1 ? "1 day left" :
                                 x.days_left + " days left";
                const card = document.createElement("article");
                card.className = "promo-card";
                card.innerHTML =
                    '<div class="promo-card-head">' +
                        '<div class="promo-product">' + escapeHTML(x.product) + '</div>' +
                        '<div class="promo-discount ' + dSev + '">' + x.suggested_discount_pct + '% OFF</div>' +
                    '</div>' +
                    '<div class="promo-meta">' +
                        '<span class="promo-chip ' + dayCls + '">⏱ ' + dayLabel + '</span>' +
                        '<span class="promo-chip stock">📦 ' + x.stock + ' in stock</span>' +
                    '</div>';
                dGrid.appendChild(card);
            });
        }

        // ----- Bundle recommendations -----
        const bundles = d.bundles || [];
        $("promo-count-bundles").textContent = bundles.length;
        const bGrid = $("promo-bundles");
        bGrid.innerHTML = "";
        if (!bundles.length) {
            bGrid.innerHTML = '<div class="promo-empty">Not enough basket data yet to suggest bundles.</div>';
        } else {
            bundles.forEach((b) => {
                const items = b.bundle.map(escapeHTML)
                    .join('<span class="bundle-plus">+</span>');
                const card = document.createElement("article");
                card.className = "promo-card promo-bundle";
                card.innerHTML =
                    '<div class="promo-card-head">' +
                        '<div class="promo-product">' + items + '</div>' +
                        '<div class="promo-bundle-frequency">' + b.frequency + 'x</div>' +
                    '</div>' +
                    '<div class="promo-meta">' +
                        '<span class="promo-chip calm">🎁 ' + escapeHTML(b.suggestion) + '</span>' +
                        '<span class="promo-chip stock">Co-occurrence ' + b.frequency + ' baskets</span>' +
                    '</div>';
                bGrid.appendChild(card);
            });
        }
    }

    async function refreshAll() {
        try {
            const r = await Promise.all([
                get("/dashboard/summary"),
                get("/soc/events?limit=20"),
                get("/soc/severity-counts"),
                get("/orders/"),
                get("/stock/"),
                get("/promotions/discounts"),
                get("/promotions/bundles"),
                get("/health"),
                get("/inventory/logs?limit=15"),
            ]);
            renderSummary(r[0]);
            renderSOC(r[1], r[2]);
            renderOrders(r[3]);
            renderStock(r[4]);
            renderPromotions({ discounts: r[5], bundles: r[6] });
            renderActivity(r[8]);
            $("db-backend").textContent = "DB: " + (r[7].database || "?");
            setLastUpdate();
        } catch (e) {
            console.error("refresh failed", e);
            $("last-update").textContent = "refresh failed: " + e.message;
        }
    }

    refreshAll();
    refreshAnalytics();
    setInterval(refreshAll, REFRESH_MS);
    setInterval(refreshActivity, 5000);
    setInterval(refreshAnalytics, 3000);
})();