// SSMS Market — customer-facing Click & Collect.
// Strict separation of concerns: api / cart / state / render / events.
(() => {
    "use strict";

    const API_BASE = "";
    const TAX_RATE = 0.10;
    const STOCK_REFRESH_MS = 30000;

    const $ = (id) => document.getElementById(id);
    const fmt = (n) => "€" + Number(n || 0).toFixed(2);
    const debounce = (fn, ms) => {
        let t = null;
        return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
    };

    // ===================== API LAYER =====================
    const api = {
        async getStock() {
            const res = await fetch(API_BASE + "/stock/");
            if (!res.ok) throw new Error("stock fetch failed: " + res.status);
            return res.json();
        },
        async createOrder(items) {
            const res = await fetch(API_BASE + "/orders/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ items }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || ("order failed: " + res.status));
            return data;
        },
    };

    // ===================== CART (localStorage) =====================
    const CART_KEY = "ssms.shop.cart.v1";
    const cart = {
        items: {},
        load() {
            try { this.items = JSON.parse(localStorage.getItem(CART_KEY) || "{}") || {}; }
            catch { this.items = {}; }
        },
        save() { localStorage.setItem(CART_KEY, JSON.stringify(this.items)); },
        add(name, price, maxQty) {
            const it = this.items[name] || { quantity: 0, unit_price: price, max: maxQty };
            it.quantity = Math.min((it.quantity || 0) + 1, maxQty);
            it.unit_price = price;
            it.max = maxQty;
            this.items[name] = it;
            this.save();
        },
        setQty(name, qty) {
            const it = this.items[name];
            if (!it) return;
            const q = Math.max(0, Math.min(qty, it.max || 99));
            if (q === 0) delete this.items[name];
            else it.quantity = q;
            this.save();
        },
        remove(name) { delete this.items[name]; this.save(); },
        clear() { this.items = {}; this.save(); },
        list() {
            return Object.entries(this.items)
                .map(([name, v]) => ({ name, ...v }));
        },
        count() { return this.list().reduce((a, x) => a + x.quantity, 0); },
        subtotal() { return this.list().reduce((a, x) => a + x.quantity * x.unit_price, 0); },
        tax() { return this.subtotal() * TAX_RATE; },
        total() { return this.subtotal() + this.tax(); },
    };

    // ===================== STATE =====================
    const state = {
        allProducts: [],
        selectedCategory: null,
        searchQuery: "",
    };

    // ===================== I18N HELPERS =====================
    const CATEGORY_LABELS = {
        bakery: "Boulangerie",
        dairy: "Produits laitiers",
        produce: "Fruits & légumes",
        grocery: "Épicerie",
        butcher: "Boucherie",
        seafood: "Poissonnerie",
        beverage: "Boissons",
        snack: "Snacks",
        general: "Général",
    };
    const CATEGORY_ICONS = {
        bakery: "🥖",
        dairy: "🥛",
        produce: "🥬",
        grocery: "🛒",
        butcher: "🥩",
        seafood: "🐟",
        beverage: "🥤",
        snack: "🍫",
        general: "📦",
    };
    const PRODUCT_ICONS = {
        "Banana": "🍌", "Apple": "🍎", "Tomato": "🍅",
        "Baguette": "🥖", "Croissant": "🥐",
        "Milk 1L": "🥛", "Yogurt": "🥣", "Cheese": "🧀",
        "Pasta": "🍝", "Olive Oil": "🫒", "Cereal": "🥣",
        "Chicken Breast": "🍗", "Beef Steak": "🥩",
        "Salmon": "🐟",
        "Soda 1.5L": "🥤", "Water 1.5L": "💧",
        "Coffee": "☕", "Tea": "🍵",
        "Chocolate Bar": "🍫", "Chips": "🍟",
    };
    const labelOf = (cat) => CATEGORY_LABELS[cat] || cat;
    const iconOf = (p) => PRODUCT_ICONS[p.name] || CATEGORY_ICONS[p.category] || "📦";

    // ===================== RENDER =====================
    const render = {
        categories(products) {
            const counts = {};
            products.forEach((p) => { counts[p.category] = (counts[p.category] || 0) + 1; });
            const grid = $("category-grid");
            grid.innerHTML = "";
            const all = `
                <button class="category-card ${!state.selectedCategory ? "active" : ""}" data-cat="">
                    <div class="category-icon">🛒</div>
                    <div class="category-name">Tous</div>
                    <div class="category-count">${products.length} produits</div>
                </button>`;
            grid.insertAdjacentHTML("beforeend", all);
            Object.entries(counts).sort().forEach(([cat, count]) => {
                grid.insertAdjacentHTML("beforeend", `
                    <button class="category-card ${state.selectedCategory === cat ? "active" : ""}" data-cat="${cat}">
                        <div class="category-icon">${CATEGORY_ICONS[cat] || "📦"}</div>
                        <div class="category-name">${labelOf(cat)}</div>
                        <div class="category-count">${count} produits</div>
                    </button>`);
            });
            grid.querySelectorAll(".category-card").forEach((el) => {
                el.addEventListener("click", () => {
                    state.selectedCategory = el.dataset.cat || null;
                    render.categories(state.allProducts);
                    render.products();
                });
            });
        },

        products() {
            const q = state.searchQuery.toLowerCase().trim();
            const filtered = state.allProducts
                .filter((p) => p.quantity > 0)
                .filter((p) => !state.selectedCategory || p.category === state.selectedCategory)
                .filter((p) => !q
                    || p.name.toLowerCase().includes(q)
                    || (p.category && (p.category.toLowerCase().includes(q) || labelOf(p.category).toLowerCase().includes(q))));

            const grid = $("product-grid");
            grid.innerHTML = "";
            $("products-title").textContent = state.selectedCategory
                ? labelOf(state.selectedCategory)
                : "Tous les produits";
            $("products-meta").textContent =
                `${filtered.length} article${filtered.length > 1 ? "s" : ""} disponibles`;

            if (!filtered.length) {
                grid.innerHTML = '<div class="empty">Aucun produit ne correspond à votre recherche.</div>';
                return;
            }

            filtered.forEach((p) => {
                let flag = "";
                if (p.is_near_expiry) flag = '<span class="badge near">DLC courte</span>';
                else if (p.is_low_stock) flag = '<span class="badge low">Stock limité</span>';

                const stockText = `${p.quantity} en stock`;

                const card = document.createElement("article");
                card.className = "product-card";
                card.innerHTML = `
                    <div class="product-image cat-${p.category}">
                        <span class="product-emoji">${iconOf(p)}</span>
                        ${flag}
                    </div>
                    <div class="product-body">
                        <div class="product-name">${p.name}</div>
                        <div class="product-meta">${labelOf(p.category)} · ${stockText}</div>
                        <div class="product-bottom">
                            <span class="product-price">${fmt(p.unit_price)}</span>
                            <button class="add-btn" data-name="${p.name}" aria-label="Ajouter ${p.name}">+</button>
                        </div>
                    </div>`;
                grid.appendChild(card);
            });

            grid.querySelectorAll(".add-btn").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const name = btn.dataset.name;
                    const p = state.allProducts.find((x) => x.name === name);
                    if (!p) return;
                    cart.add(name, p.unit_price, p.quantity);
                    render.cartBadge();
                    render.cart();
                    btn.classList.add("pulse");
                    setTimeout(() => btn.classList.remove("pulse"), 350);
                    showToast(`${name} ajouté au panier`);
                });
            });
        },

        cartBadge() {
            const c = cart.count();
            const badge = $("cart-badge");
            badge.textContent = c;
            badge.classList.toggle("hidden", c === 0);
            $("cart-count").textContent = c;
        },

        cart() {
            const items = cart.list();
            const list = $("cart-items");
            list.innerHTML = "";
            if (!items.length) {
                list.innerHTML = '<div class="cart-empty">Votre panier est vide.</div>';
            } else {
                items.forEach((it) => {
                    const line = it.quantity * it.unit_price;
                    const div = document.createElement("div");
                    div.className = "cart-item";
                    div.innerHTML = `
                        <div class="cart-item-name">${it.name}</div>
                        <div class="cart-item-controls">
                            <button class="qty-btn" data-act="dec" data-name="${it.name}">−</button>
                            <input class="qty-input" type="number" min="0" max="${it.max || 99}"
                                   data-name="${it.name}" value="${it.quantity}">
                            <button class="qty-btn" data-act="inc" data-name="${it.name}">+</button>
                        </div>
                        <div class="cart-item-line">${fmt(line)}</div>
                        <button class="cart-remove" data-name="${it.name}" aria-label="Retirer">×</button>`;
                    list.appendChild(div);
                });
            }
            $("cart-subtotal").textContent = fmt(cart.subtotal());
            $("cart-tax").textContent = fmt(cart.tax());
            $("cart-total").textContent = fmt(cart.total());
            $("checkout-btn").disabled = items.length === 0;

            list.querySelectorAll(".qty-btn").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const name = btn.dataset.name;
                    const it = cart.items[name];
                    if (!it) return;
                    const delta = btn.dataset.act === "inc" ? 1 : -1;
                    cart.setQty(name, it.quantity + delta);
                    render.cart();
                    render.cartBadge();
                });
            });
            list.querySelectorAll(".qty-input").forEach((input) => {
                input.addEventListener("change", () => {
                    cart.setQty(input.dataset.name, parseInt(input.value, 10) || 0);
                    render.cart();
                    render.cartBadge();
                });
            });
            list.querySelectorAll(".cart-remove").forEach((btn) => {
                btn.addEventListener("click", () => {
                    cart.remove(btn.dataset.name);
                    render.cart();
                    render.cartBadge();
                });
            });
        },
    };

    // ===================== UI HELPERS =====================
    function openCart()  { $("cart-drawer").classList.add("open"); $("cart-drawer").setAttribute("aria-hidden", "false"); }
    function closeCart() { $("cart-drawer").classList.remove("open"); $("cart-drawer").setAttribute("aria-hidden", "true"); }

    let toastTimer = null;
    function showToast(msg, ms = 1800) {
        const t = $("toast");
        t.textContent = msg;
        t.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { t.hidden = true; }, ms);
    }

    // ===================== CONTROLLERS =====================
    async function loadProducts() {
        try {
            const products = await api.getStock();
            state.allProducts = products;
            render.categories(products);
            render.products();
            cart.list().forEach((it) => {
                const p = state.allProducts.find((x) => x.name === it.name);
                if (!p || p.quantity <= 0) cart.remove(it.name);
                else if (it.quantity > p.quantity) cart.setQty(it.name, p.quantity);
            });
            render.cart();
            render.cartBadge();
        } catch (e) {
            $("product-grid").innerHTML =
                `<div class="empty">Impossible de charger les produits : ${e.message}</div>`;
        }
    }

    async function checkout() {
        const items = cart.list().map((x) => ({
            product_name: x.name, quantity: x.quantity,
        }));
        if (!items.length) return;
        const btn = $("checkout-btn");
        const originalLabel = btn.textContent;
        btn.disabled = true;
        btn.textContent = "Paiement en cours…";
        try {
            const order = await api.createOrder(items);
            await new Promise((r) => setTimeout(r, 600));
            cart.clear();
            render.cartBadge();
            render.cart();
            closeCart();
            $("order-id-display").textContent = order.public_id;
            $("order-total-display").textContent = fmt(order.total);
            $("success-modal").hidden = false;
            await loadProducts();
        } catch (e) {
            showToast("Erreur : " + e.message, 3000);
        } finally {
            btn.disabled = false;
            btn.textContent = originalLabel;
        }
    }

    // ===================== EVENT WIRING =====================
    function wire() {
        $("search").addEventListener("input", debounce((e) => {
            state.searchQuery = e.target.value;
            render.products();
        }, 200));
        $("open-cart").addEventListener("click", openCart);
        $("close-cart").addEventListener("click", closeCart);
        $("cart-overlay").addEventListener("click", closeCart);
        $("checkout-btn").addEventListener("click", checkout);
        $("modal-close").addEventListener("click", () => { $("success-modal").hidden = true; });
        $("modal-overlay").addEventListener("click", () => { $("success-modal").hidden = true; });
        $("hero-shop-now").addEventListener("click", () => {
            $("products").scrollIntoView({ behavior: "smooth", block: "start" });
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                closeCart();
                $("success-modal").hidden = true;
            }
        });
    }

    // ===================== INIT =====================
    document.addEventListener("DOMContentLoaded", () => {
        cart.load();
        wire();
        render.cartBadge();
        render.cart();
        loadProducts();
        setInterval(loadProducts, STOCK_REFRESH_MS);
    });
})();