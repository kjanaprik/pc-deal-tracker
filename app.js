const STORAGE_KEY = "pc_deal_tracker_watchlist_v1";

const STORE_DOMAINS = {
  "Tölvutek": "tolvutek.is",
  "Tölvutækni": "tolvutaekni.is",
  "Computer.is": "computer.is",
  "Elko": "elko.is",
  "Tölvulistinn": "tl.is",
  "Kísildalur": "kd.is",
  "Memory PC": "memorypc.de",
  "Overclockers UK": "overclockers.co.uk",
  "Caseking": "caseking.de",
  "Computeruniverse": "computeruniverse.net",
  "PCSpecialist": "pcspecialist.co.uk",
  "CSL Computer": "csl-computer.com",
  "Alternate.de": "alternate.de",
  "Cyberport.de": "cyberport.de",
  "Amazon.de": "amazon.de",
  "Amazon.co.uk": "amazon.co.uk",
  "Best Buy": "bestbuy.com",
  "Amazon.com": "amazon.com",
  "B&H Photo": "bhphotovideo.com",
  "Newegg": "newegg.com",
  "Costco": "costco.com",
  "ORIGIN PC": "originpc.com",
  "XOTIC PC": "xoticpc.com",
  "iBUYPOWER": "ibuypower.com",
  "CyberPowerPC": "cyberpowerpc.com",
};

function storeLogoHtml(store) {
  const domain = STORE_DOMAINS[store];
  const initials = store.replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "PC";
  if (!domain) {
    return `<span class="store-monogram">${initials}</span>`;
  }
  const url = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;
  return `<span class="store-logo-wrap"><img class="store-logo" src="${url}" alt="${escapeHtml(store)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='inline-flex'" /><span class="store-monogram" style="display:none">${initials}</span></span>`;
}

let allProducts = [];
let storeStatuses = [];
let priceHistory = {};
let repoWatchlist = { watched_ids: [], rules: [], notify_on_any_watched_sale: true, min_price_drop_pct: 3.0 };
let activeGpus = new Set(["RTX 5060 Ti 16GB", "RTX 5070 Ti 16GB", "RTX 5080 16GB"]);
let localWatchlist = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"));

const fmtIsk = (n) => `${Math.round(n).toLocaleString("de-DE")} ISK`;

function updateCountdown() {
  const el = document.getElementById("bf-countdown");
  const bf = new Date("2026-11-27T00:00:00Z");
  const cm = new Date("2026-12-01T00:00:00Z");
  const now = new Date();
  if (now >= bf && now <= cm) {
    el.textContent = "🔥 BLACK FRIDAY WEEKEND LIVE";
  } else if (now < bf) {
    const days = Math.ceil((bf - now) / (1000 * 60 * 60 * 24));
    el.textContent = `Black Friday in ${days}d`;
  } else {
    el.textContent = "Cyber Week / Holiday Deals";
  }
}

async function init() {
  updateCountdown();
  try {
    const [dealsRes, histRes, watchRes] = await Promise.all([
      fetch("data/deals.json?_=" + Date.now()),
      fetch("data/history.json?_=" + Date.now()).catch(() => null),
      fetch("watchlist.json?_=" + Date.now()).catch(() => null),
    ]);

    const deals = await dealsRes.json();
    allProducts = deals.products || [];
    storeStatuses = deals.stores || [];

    if (histRes && histRes.ok) priceHistory = await histRes.json();
    if (watchRes && watchRes.ok) {
      repoWatchlist = await watchRes.json();
      for (const id of repoWatchlist.watched_ids || []) localWatchlist.add(id);
      saveLocalWatchlist();
    }

    const fx = deals.fx_rates || {};
    document.getElementById("fx-pill").textContent =
      `FX: 1€=${fx.EUR || "?"} | 1$=${fx.USD || "?"} | 1£=${fx.GBP || "?"}`;
    document.getElementById("updated-pill").textContent =
      `Updated: ${deals.updated_at ? new Date(deals.updated_at).toLocaleString() : "—"}`;

    populateStores();
    populateDynamicFilters();
    bindEvents();
    updateWatchlistCount();
    render();
  } catch (err) {
    document.getElementById("deals-grid").innerHTML =
      `<div class="empty-state">Failed to load <code>data/deals.json</code>: ${err.message}</div>`;
  }
}

function populateStores() {
  const sel = document.getElementById("store-filter");
  const counts = {};
  for (const p of allProducts) {
    counts[p.store] = (counts[p.store] || 0) + 1;
  }
  const allStoreNames = storeStatuses.length
    ? storeStatuses.map((s) => s.store)
    : [...new Set(allProducts.map((p) => p.store))];

  for (const s of allStoreNames) {
    const opt = document.createElement("option");
    opt.value = s;
    const c = counts[s] || 0;
    opt.textContent = `${s} (${c})`;
    sel.appendChild(opt);
  }
}

function populateDynamicFilters() {
  const cpuSel = document.getElementById("cpu-model-filter");
  const cpuCounts = {};
  const brandSel = document.getElementById("brand-filter");
  const brandCounts = {};

  for (const p of allProducts) {
    if (p.cpu && p.cpu !== "Unknown") {
      cpuCounts[p.cpu] = (cpuCounts[p.cpu] || 0) + 1;
    }
    const b = p.brand || "Custom / Prebuilt";
    brandCounts[b] = (brandCounts[b] || 0) + 1;
  }

  for (const cpu of Object.keys(cpuCounts).sort()) {
    const opt = document.createElement("option");
    opt.value = cpu;
    opt.textContent = `${cpu} (${cpuCounts[cpu]})`;
    cpuSel.appendChild(opt);
  }

  for (const brand of Object.keys(brandCounts).sort()) {
    const opt = document.createElement("option");
    opt.value = brand;
    opt.textContent = `${brand} (${brandCounts[brand]})`;
    brandSel.appendChild(opt);
  }
}

function saveLocalWatchlist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...localWatchlist]));
  updateWatchlistCount();
}

function updateWatchlistCount() {
  document.getElementById("watchlist-count").textContent = localWatchlist.size;
}

function toggleWatch(id) {
  if (localWatchlist.has(id)) localWatchlist.delete(id);
  else localWatchlist.add(id);
  saveLocalWatchlist();
  render();
}

function getFilteredProducts() {
  const q = document.getElementById("search-input").value.trim().toLowerCase();
  const ship = document.getElementById("shipping-filter").value;
  const store = document.getElementById("store-filter").value;
  const cpuBrand = document.getElementById("cpu-filter").value;
  const cpuModel = document.getElementById("cpu-model-filter").value;
  const pcBrand = document.getElementById("brand-filter").value;
  const minRam = parseInt(document.getElementById("ram-filter").value, 10) || 0;
  const minStorage = parseInt(document.getElementById("storage-filter").value, 10) || 0;
  const maxPrice = parseInt(document.getElementById("max-price").value, 10);
  const saleOnly = document.getElementById("sale-only").checked;
  const stockOnly = document.getElementById("stock-only").checked;
  const watchedOnly = document.getElementById("watched-only").checked;
  const sortBy = document.getElementById("sort-select").value;

  const filtered = allProducts.filter((p) => {
    if (!activeGpus.has(p.gpu)) return false;
    if (ship === "Local" && p.ships_to_iceland !== "Local") return false;
    if (ship === "Direct" && !["Local", "Direct", "Direct (Amazon Global)"].includes(p.ships_to_iceland)) return false;
    if (ship === "Forwarder Required" && p.ships_to_iceland !== "Forwarder Required") return false;
    if (store !== "all" && p.store !== store) return false;
    if (cpuBrand !== "all" && p.cpu_brand !== cpuBrand) return false;
    if (cpuModel !== "all" && p.cpu !== cpuModel) return false;
    if (pcBrand !== "all" && (p.brand || "Custom / Prebuilt") !== pcBrand) return false;
    if (minRam > 0 && (!p.ram_gb || p.ram_gb < minRam)) return false;
    if (minStorage > 0 && (!p.storage_gb || p.storage_gb < minStorage)) return false;
    if (maxPrice < 1200000 && p.estimated_landed_isk > maxPrice) return false;
    if (saleOnly && !p.on_sale && !(p.price_drop_pct > 0)) return false;
    if (stockOnly && !p.in_stock) return false;
    if (watchedOnly && !localWatchlist.has(p.id)) return false;
    if (q) {
      const hay = `${p.title} ${p.store} ${p.gpu} ${p.cpu} ${p.brand}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  filtered.sort((a, b) => {
    if (sortBy === "landed_asc") return a.estimated_landed_isk - b.estimated_landed_isk;
    if (sortBy === "landed_desc") return b.estimated_landed_isk - a.estimated_landed_isk;
    if (sortBy === "discount_desc") return (b.discount_pct || 0) - (a.discount_pct || 0);
    if (sortBy === "drop_desc") return (b.price_drop_pct || 0) - (a.price_drop_pct || 0);
    return 0;
  });

  return filtered;
}

function gpuBadgeClass(gpu) {
  if (gpu.includes("5080")) return "badge-gpu-5080";
  if (gpu.includes("5070")) return "badge-gpu-5070ti";
  return "badge-gpu-5060ti";
}

function render() {
  const list = getFilteredProducts();
  document.getElementById("results-count").textContent =
    `Showing ${list.length} of ${allProducts.length} Gaming Desktop PCs`;

  const grid = document.getElementById("deals-grid");
  if (!list.length) {
    grid.innerHTML = `<div class="empty-state">No Gaming Desktop PCs match your current filters. Try widening your search or resetting filters.</div>`;
    return;
  }

  grid.innerHTML = list.map((p) => {
    const watching = localWatchlist.has(p.id);
    const saleBadge = p.on_sale ? `<span class="badge badge-sale">-${p.discount_pct}% SALE</span>` : "";
    const dropBadge = p.price_drop_pct > 0 ? `<span class="badge badge-drop">▼ -${p.price_drop_pct}%</span>` : "";
    const oldPrice = p.original_price_isk ? `<span class="price-old">${fmtIsk(p.original_price_isk)}</span>` : "";
    const stickerNote = p.region === "Iceland"
      ? "Local Icelandic price (incl. 24% VAT)"
      : `Sticker: ${p.price_original} ${p.currency} (Est. landed incl. 24% VAT + shipping)`;

    const logoHtml = storeLogoHtml(p.store);

    return `
      <article class="card">
        <div>
          <div class="card-store-bar">
            <div class="store-identity">
              ${logoHtml}
              <span class="store-name">${escapeHtml(p.store)}</span>
              <span class="store-region">• ${escapeHtml(p.region)}</span>
            </div>
            <span class="badge badge-ship">${escapeHtml(p.ships_to_iceland)}</span>
          </div>
          <div class="card-badges">
            <span class="badge ${gpuBadgeClass(p.gpu)}">${p.gpu}</span>
            ${saleBadge}
            ${dropBadge}
          </div>
          <h3 class="card-title">${escapeHtml(p.title)}</h3>
          <div class="specs-row">
            <span class="spec-pill">CPU: ${escapeHtml(p.cpu)}</span>
            <span class="spec-pill">RAM: ${p.ram_gb ? p.ram_gb + "GB" : "?"}</span>
            <span class="spec-pill">SSD: ${escapeHtml(p.storage_label)}</span>
          </div>
        </div>

        <div>
          <div class="price-box">
            <div class="price-landed">${fmtIsk(p.estimated_landed_isk)} ${oldPrice}</div>
            <div class="price-sub">${stickerNote}</div>
          </div>
          <div class="card-actions" style="margin-top:10px;">
            <button class="btn btn-watch ${watching ? "watching" : ""}" data-watch="${p.id}">
              ${watching ? "★ Watching" : "☆ Watch"}
            </button>
            <button class="btn btn-ghost" data-history="${p.id}">History</button>
            <a class="btn btn-primary" href="${escapeHtml(p.url)}" target="_blank" rel="noopener">Deal →</a>
          </div>
        </div>
      </article>
    `;
  }).join("");

  grid.querySelectorAll("[data-watch]").forEach((btn) =>
    btn.addEventListener("click", () => toggleWatch(btn.dataset.watch))
  );
  grid.querySelectorAll("[data-history]").forEach((btn) =>
    btn.addEventListener("click", () => openHistoryModal(btn.dataset.history))
  );
}

function openWatchlistModal() {
  const modal = document.getElementById("watchlist-modal");
  const container = document.getElementById("watchlist-items");
  const ids = [...localWatchlist];

  if (!ids.length) {
    container.innerHTML = `<p style="color:var(--muted);font-size:13px;">No PCs watched yet. Click "☆ Watch" on any PC card.</p>`;
  } else {
    container.innerHTML = ids.map((id) => {
      const p = allProducts.find((x) => x.id === id);
      return `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;">
        <span>${p ? escapeHtml(p.title) + " (" + escapeHtml(p.store) + ")" : id}</span>
        <button class="btn-link" onclick="toggleWatch('${id}');openWatchlistModal();">Remove</button>
      </div>`;
    }).join("");
  }

  const updatedJson = {
    ...repoWatchlist,
    watched_ids: ids,
  };
  document.getElementById("watchlist-json-preview").textContent = JSON.stringify(updatedJson, null, 2);

  // Detect GitHub Pages owner/repo if hosted on *.github.io
  const host = window.location.hostname;
  if (host.endsWith(".github.io")) {
    const owner = host.split(".")[0];
    const repo = window.location.pathname.split("/").filter(Boolean)[0] || "";
    if (repo) {
      document.getElementById("edit-github-watchlist").href =
        `https://github.com/${owner}/${repo}/edit/main/watchlist.json`;
    }
  }
  modal.classList.remove("hidden");
}

function openStatusModal() {
  const el = document.getElementById("store-status-table");
  el.innerHTML = `
    <table class="status-table">
      <thead>
        <tr>
          <th>Store</th>
          <th>Region</th>
          <th>Ships to Iceland</th>
          <th>Status</th>
          <th>PCs Found</th>
          <th>Notes</th>
        </tr>
      </thead>
      <tbody>
        ${storeStatuses.map((s) => `
          <tr>
            <td><strong>${escapeHtml(s.store)}</strong></td>
            <td>${escapeHtml(s.region)}</td>
            <td>${escapeHtml(s.ships_to_iceland)}</td>
            <td class="status-${s.status}">${s.status.toUpperCase()}</td>
            <td>${s.count}</td>
            <td style="color:var(--muted);font-size:12px;">${escapeHtml(s.error || "OK")}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  document.getElementById("status-modal").classList.remove("hidden");
}

function openHistoryModal(id) {
  const p = allProducts.find((x) => x.id === id);
  const pts = priceHistory[id] || [];
  document.getElementById("history-title").textContent = p ? p.title : "Price History";
  const chart = document.getElementById("history-chart");

  if (!pts.length) {
    chart.innerHTML = `<p style="color:var(--muted);">No price history recorded yet.</p>`;
  } else {
    chart.innerHTML = pts.map((pt) => `
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px;">
        <span style="color:var(--muted);">${new Date(pt.ts).toLocaleString()}</span>
        <span><strong>${fmtIsk(pt.landed_isk || pt.price_isk)}</strong></span>
      </div>
    `).join("");
  }
  document.getElementById("history-modal").classList.remove("hidden");
}

function bindEvents() {
  document.querySelectorAll("#gpu-chips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const gpu = chip.dataset.gpu;
      if (activeGpus.has(gpu)) {
        if (activeGpus.size > 1) {
          activeGpus.delete(gpu);
          chip.classList.remove("active");
        }
      } else {
        activeGpus.add(gpu);
        chip.classList.add("active");
      }
      render();
    });
  });

  ["search-input", "shipping-filter", "store-filter", "cpu-filter", "cpu-model-filter", "brand-filter",
   "ram-filter", "storage-filter", "sale-only", "stock-only", "watched-only", "sort-select"].forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
    document.getElementById(id).addEventListener("change", render);
  });

  const maxPriceEl = document.getElementById("max-price");
  maxPriceEl.addEventListener("input", () => {
    const v = parseInt(maxPriceEl.value, 10);
    document.getElementById("max-price-label").textContent = v >= 1200000 ? "No limit" : fmtIsk(v);
    render();
  });

  document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("shipping-filter").value = "all";
    document.getElementById("store-filter").value = "all";
    document.getElementById("cpu-filter").value = "all";
    document.getElementById("cpu-model-filter").value = "all";
    document.getElementById("brand-filter").value = "all";
    document.getElementById("ram-filter").value = "0";
    document.getElementById("storage-filter").value = "0";
    maxPriceEl.value = "1200000";
    document.getElementById("max-price-label").textContent = "No limit";
    document.getElementById("sale-only").checked = false;
    document.getElementById("stock-only").checked = true;
    document.getElementById("watched-only").checked = false;
    activeGpus = new Set(["RTX 5060 Ti 16GB", "RTX 5070 Ti 16GB", "RTX 5080 16GB"]);
    document.querySelectorAll("#gpu-chips .chip").forEach((c) => c.classList.add("active"));
    render();
  });

  document.getElementById("watchlist-btn").addEventListener("click", openWatchlistModal);
  document.getElementById("status-btn").addEventListener("click", openStatusModal);
  document.getElementById("copy-watchlist").addEventListener("click", async () => {
    const txt = document.getElementById("watchlist-json-preview").textContent;
    await navigator.clipboard.writeText(txt);
    document.getElementById("copy-watchlist").textContent = "Copied!";
    setTimeout(() => { document.getElementById("copy-watchlist").textContent = "Copy watchlist.json"; }, 1800);
  });

  document.querySelectorAll("[data-close]").forEach((btn) =>
    btn.addEventListener("click", () => document.getElementById(btn.dataset.close).classList.add("hidden"))
  );
  document.querySelectorAll(".modal").forEach((m) =>
    m.addEventListener("click", (e) => { if (e.target === m) m.classList.add("hidden"); })
  );
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

init();
