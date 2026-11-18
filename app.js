const STORAGE_KEY = "pc_deal_tracker_watchlist_v1";
const ALL_GPUS = ["RTX 5060 Ti 16GB", "RTX 5070 12GB", "RTX 5070 Ti 16GB", "RTX 5080 16GB"];

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
    return `<span class="store-monogram" style="display:inline-flex">${initials}</span>`;
  }
  const url = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;
  return `<span class="store-logo-wrap"><img class="store-logo" src="${url}" alt="${escapeHtml(store)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='inline-flex'" /><span class="store-monogram" style="display:none">${initials}</span></span>`;
}

function displayTitle(p) {
  if (p.title && p.title.trim()) return p.title.trim();
  try {
    const u = new URL(p.url);
    const segs = u.pathname.split("/").filter(Boolean);
    const slug = segs.find((s) => s.length > 12 && !s.endsWith(".html")) || segs[segs.length - 1] || "";
    const cleaned = decodeURIComponent(slug)
      .replace(/\.html$/i, "")
      .replace(/[-_]+/g, " ")
      .replace(/\b(wqhd|uhd|fhd|am5|ddr5|rtx|gpu|pc|rgb|ssd)\b/gi, (m) => m.toUpperCase());
    if (cleaned.length > 6) {
      return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
    }
  } catch (_) {}
  return `${p.store} ${p.gpu} Gaming Desktop`;
}

let allProducts = [];
let storeStatuses = [];
let priceHistory = {};
let repoWatchlist = { watched_ids: [], rules: [], notify_on_any_watched_sale: true, min_price_drop_pct: 3.0 };
let activeGpus = new Set(ALL_GPUS);
let localWatchlist = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"));
let viewMode = "cards"; // "cards" | "table"

const fmtIsk = (n) => `${Math.round(n).toLocaleString("de-DE")} kr.`;

function updateCountdown() {
  const el = document.getElementById("bf-countdown");
  const bf = new Date("2026-11-27T00:00:00Z");
  const cm = new Date("2026-12-01T00:00:00Z");
  const now = new Date();
  if (now >= bf && now <= cm) {
    el.textContent = "BLACK FRIDAY LIVE";
  } else if (now < bf) {
    const days = Math.ceil((bf - now) / (1000 * 60 * 60 * 24));
    el.textContent = `BF-26 · T-${days}D`;
  } else {
    el.textContent = "CYBER WEEK";
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
    allProducts = (deals.products || []).map((p) => ({
      ...p,
      title: displayTitle(p),
    }));
    storeStatuses = deals.stores || [];

    if (histRes && histRes.ok) priceHistory = await histRes.json();
    if (watchRes && watchRes.ok) {
      repoWatchlist = await watchRes.json();
      for (const id of repoWatchlist.watched_ids || []) localWatchlist.add(id);
      saveLocalWatchlist();
    }

    const fx = deals.fx_rates || {};
    document.getElementById("fx-pill").textContent =
      `EUR ${fx.EUR || "?"} · USD ${fx.USD || "?"} · GBP ${fx.GBP || "?"}`;

    if (deals.updated_at) {
      const dt = new Date(deals.updated_at);
      document.getElementById("updated-pill").textContent =
        dt.toLocaleString("en-GB", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    }

    const activeStoreCount = new Set(allProducts.map((p) => p.store)).size;
    document.getElementById("active-stores-count").textContent = `${activeStoreCount}/${storeStatuses.length || activeStoreCount}`;

    populateStores();
    populateDynamicFilters();
    bindEvents();
    updateWatchlistCount();
    render();
  } catch (err) {
    document.getElementById("deals-grid").innerHTML =
      `<div class="empty-state">Failed to load <code>data/deals.json</code>: ${escapeHtml(err.message)}</div>`;
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

  const active = allStoreNames.filter((s) => (counts[s] || 0) > 0).sort((a, b) => counts[b] - counts[a]);
  const empty = allStoreNames.filter((s) => !counts[s]).sort();

  sel.innerHTML = `<option value="all">All Retailers (${allProducts.length})</option>`;
  if (active.length) {
    const grpActive = document.createElement("optgroup");
    grpActive.label = `With Matching Stock (${active.length})`;
    for (const s of active) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = `${s} (${counts[s]})`;
      grpActive.appendChild(opt);
    }
    sel.appendChild(grpActive);
  }
  if (empty.length) {
    const grpEmpty = document.createElement("optgroup");
    grpEmpty.label = `0 Current Matches (${empty.length})`;
    for (const s of empty) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = `${s} (0)`;
      grpEmpty.appendChild(opt);
    }
    sel.appendChild(grpEmpty);
  }
}

function populateDynamicFilters() {
  populateCpuModels();

  const brandSel = document.getElementById("brand-filter");
  const brandCounts = {};
  for (const p of allProducts) {
    const b = p.brand || "Custom / Prebuilt";
    brandCounts[b] = (brandCounts[b] || 0) + 1;
  }
  brandSel.innerHTML = `<option value="all">All Brands</option>`;
  for (const brand of Object.keys(brandCounts).sort((a, b) => brandCounts[b] - brandCounts[a])) {
    const opt = document.createElement("option");
    opt.value = brand;
    opt.textContent = `${brand} (${brandCounts[brand]})`;
    brandSel.appendChild(opt);
  }
}

function populateCpuModels() {
  const cpuBrand = document.getElementById("cpu-filter").value;
  const cpuSel = document.getElementById("cpu-model-filter");
  const prevValue = cpuSel.value;

  const cpuCounts = {};
  for (const p of allProducts) {
    if (cpuBrand !== "all" && p.cpu_brand !== cpuBrand) continue;
    if (p.cpu && p.cpu !== "Unknown") {
      cpuCounts[p.cpu] = (cpuCounts[p.cpu] || 0) + 1;
    }
  }

  cpuSel.innerHTML = `<option value="all">All Models</option>`;
  for (const cpu of Object.keys(cpuCounts).sort()) {
    const opt = document.createElement("option");
    opt.value = cpu;
    opt.textContent = `${cpu} (${cpuCounts[cpu]})`;
    cpuSel.appendChild(opt);
  }

  cpuSel.value = cpuCounts[prevValue] ? prevValue : "all";
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
    if (ship === "Quote / Forwarder" && !["Quote / Forwarder", "Quote Required"].includes(p.ships_to_iceland)) return false;
    if (ship === "region_Europe" && p.region !== "Europe") return false;
    if (ship === "region_USA/Canada" && p.region !== "USA/Canada") return false;
    if (ship === "Forwarder Required" && !["Forwarder Required", "Quote / Forwarder"].includes(p.ships_to_iceland)) return false;
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
    if (sortBy === "store_asc") return a.price_isk - b.price_isk;
    if (sortBy === "store_desc") return b.price_isk - a.price_isk;
    if (sortBy === "discount_desc") return (b.discount_pct || 0) - (a.discount_pct || 0);
    if (sortBy === "drop_desc") return (b.price_drop_pct || 0) - (a.price_drop_pct || 0);
    return 0;
  });

  return filtered;
}

function gpuBadgeClass(gpu) {
  if (gpu.includes("5080")) return "badge-gpu-5080";
  if (gpu.includes("5070 Ti")) return "badge-gpu-5070ti";
  if (gpu.includes("5070")) return "badge-gpu-5070";
  return "badge-gpu-5060ti";
}

function renderBenchmarks() {
  const wrap = document.getElementById("gpu-benchmarks");
  if (!wrap) return;

  wrap.innerHTML = ALL_GPUS.map((gpu) => {
    const matching = allProducts.filter((p) => p.gpu === gpu && p.in_stock);
    const best = matching.reduce((min, p) => (!min || p.estimated_landed_isk < min.estimated_landed_isk ? p : min), null);
    const isIsolated = activeGpus.size === 1 && activeGpus.has(gpu);
    return `
      <button type="button" class="bench-card ${isIsolated ? "active-tier" : ""}" data-bench-gpu="${gpu}">
        <div>
          <div class="bench-gpu">
            <span>${gpu.replace("RTX ", "")}</span>
            <span class="bench-count">${matching.length} rigs</span>
          </div>
          <div class="bench-price">${best ? fmtIsk(best.estimated_landed_isk) : "—"}</div>
        </div>
        <div class="bench-meta">
          <div>Lowest Landed</div>
          <div class="bench-store">${best ? escapeHtml(best.store) : "No stock"}</div>
        </div>
      </button>
    `;
  }).join("");

  wrap.querySelectorAll("[data-bench-gpu]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const g = btn.dataset.benchGpu;
      if (activeGpus.size === 1 && activeGpus.has(g)) {
        activeGpus = new Set(ALL_GPUS);
      } else {
        activeGpus = new Set([g]);
      }
      syncGpuChipUI();
      render();
    });
  });
}

function syncGpuChipUI() {
  document.querySelectorAll("#gpu-chips .chip").forEach((c) => {
    c.classList.toggle("active", activeGpus.has(c.dataset.gpu));
  });
}

function renderActiveFilterPills() {
  const container = document.getElementById("active-filters");
  if (!container) return;
  const pills = [];

  if (activeGpus.size < ALL_GPUS.length) {
    pills.push({ label: `GPU: ${[...activeGpus].map((g) => g.replace("RTX ", "")).join(", ")}`, clear: () => { activeGpus = new Set(ALL_GPUS); syncGpuChipUI(); } });
  }
  const ship = document.getElementById("shipping-filter");
  if (ship.value !== "all") {
    pills.push({ label: ship.options[ship.selectedIndex].text, clear: () => { ship.value = "all"; } });
  }
  const store = document.getElementById("store-filter");
  if (store.value !== "all") {
    pills.push({ label: `Store: ${store.value}`, clear: () => { store.value = "all"; } });
  }
  const cpuBrand = document.getElementById("cpu-filter");
  if (cpuBrand.value !== "all") {
    pills.push({ label: `CPU: ${cpuBrand.value}`, clear: () => { cpuBrand.value = "all"; populateCpuModels(); } });
  }
  const cpuModel = document.getElementById("cpu-model-filter");
  if (cpuModel.value !== "all") {
    pills.push({ label: cpuModel.value, clear: () => { cpuModel.value = "all"; } });
  }
  const brand = document.getElementById("brand-filter");
  if (brand.value !== "all") {
    pills.push({ label: `Brand: ${brand.value}`, clear: () => { brand.value = "all"; } });
  }

  container.innerHTML = pills.map((p, idx) =>
    `<span class="filter-pill" data-pill="${idx}">${escapeHtml(p.label)} <span>✕</span></span>`
  ).join("");

  container.querySelectorAll("[data-pill]").forEach((el) => {
    el.addEventListener("click", () => {
      pills[parseInt(el.dataset.pill, 10)].clear();
      render();
    });
  });
}

function render() {
  renderBenchmarks();
  renderActiveFilterPills();

  const list = getFilteredProducts();
  document.getElementById("results-count").textContent =
    `${list.length} OF ${allProducts.length} SYSTEMS`;

  const grid = document.getElementById("deals-grid");
  if (!list.length) {
    grid.innerHTML = `<div class="empty-state">No systems match your active filter criteria. Click "Reset all" to broaden your search.</div>`;
    return;
  }

  if (viewMode === "table") {
    renderTableView(list, grid);
    return;
  }

  grid.innerHTML = list.map((p) => {
    const watching = localWatchlist.has(p.id);
    const saleBadge = p.on_sale ? `<span class="badge badge-sale">-${p.discount_pct}%</span>` : "";
    const dropBadge = p.price_drop_pct > 0 ? `<span class="badge badge-drop">▼ -${p.price_drop_pct}%</span>` : "";
    const oldPrice = p.original_price_isk ? `<span class="price-old">${fmtIsk(p.original_price_isk)}</span>` : "";

    const storePriceIsk = fmtIsk(p.price_isk);
    const storeOrig = p.region === "Iceland"
      ? "Incl. 24% IS VAT"
      : `${p.price_original.toLocaleString("en-US")} ${p.currency} @ MC`;

    const logoHtml = storeLogoHtml(p.store);
    const shipClass = p.ships_to_iceland === "Local" ? "ship-local" : "";
    const thumbHtml = p.image_url
      ? `<img class="pc-thumb" src="${escapeHtml(p.image_url)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
      : "";

    return `
      <article class="card">
        <div>
          <div class="card-store-bar">
            <div class="store-identity">
              ${logoHtml}
              <span class="store-name">${escapeHtml(p.store)}</span>
              <span class="store-region">· ${escapeHtml(p.region)}</span>
            </div>
            <span class="badge badge-ship ${shipClass}">${escapeHtml(p.ships_to_iceland)}</span>
          </div>

          <div class="card-badges">
            <span class="badge ${gpuBadgeClass(p.gpu)}">${escapeHtml(p.gpu)}</span>
            <span class="badge badge-ship">${escapeHtml(p.brand || "Custom")}</span>
            ${saleBadge}
            ${dropBadge}
          </div>

          <div class="card-body-head">
            ${thumbHtml}
            <h3 class="card-title" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</h3>
          </div>

          <div class="spec-grid">
            <div class="spec-cell">
              <span class="spec-k">Processor</span>
              <span class="spec-v" title="${escapeHtml(p.cpu)}">${escapeHtml(p.cpu)}</span>
            </div>
            <div class="spec-cell">
              <span class="spec-k">Memory</span>
              <span class="spec-v">${p.ram_gb ? p.ram_gb + " GB" : "—"}</span>
            </div>
            <div class="spec-cell">
              <span class="spec-k">Storage</span>
              <span class="spec-v">${escapeHtml(p.storage_label !== "Unknown" ? p.storage_label : "—")}</span>
            </div>
          </div>
        </div>

        <div>
          <div class="price-box">
            <div>
              <span class="price-col-label">Est. Landed (IS)</span>
              <div class="price-landed">${fmtIsk(p.estimated_landed_isk)}${oldPrice}</div>
            </div>
            <div class="price-store-col">
              <span class="price-col-label">Store Price</span>
              <div class="price-store-isk">${storePriceIsk}</div>
              <div class="price-store-orig">${escapeHtml(storeOrig)}</div>
            </div>
          </div>
          <div class="card-actions">
            <a class="btn btn-primary" href="${escapeHtml(p.url)}" target="_blank" rel="noopener">View System ↗</a>
            <button class="btn btn-watch ${watching ? "watching" : ""}" data-watch="${p.id}" type="button" title="Watch for price drops">
              ${watching ? "★ Watched" : "☆ Watch"}
            </button>
            <button class="btn" data-history="${p.id}" type="button" title="Price history">History</button>
          </div>
        </div>
      </article>
    `;
  }).join("");

  bindCardActions(grid);
}

function renderTableView(list, container) {
  container.innerHTML = `
    <div class="deals-table-wrap">
      <table class="deals-table">
        <thead>
          <tr>
            <th>Retailer</th>
            <th>System</th>
            <th>GPU</th>
            <th>Processor</th>
            <th>RAM</th>
            <th>Storage</th>
            <th>Store Price</th>
            <th>Est. Landed (IS)</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${list.map((p) => {
            const watching = localWatchlist.has(p.id);
            const origLabel = p.region === "Iceland" ? "Local ISK" : `${p.price_original} ${p.currency}`;
            return `
              <tr>
                <td>
                  <div class="store-identity">
                    ${storeLogoHtml(p.store)}
                    <div>
                      <div class="store-name">${escapeHtml(p.store)}</div>
                      <div class="store-region">${escapeHtml(p.ships_to_iceland)}</div>
                    </div>
                  </div>
                </td>
                <td style="max-width:300px;">
                  <a class="table-title-link" href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${escapeHtml(p.title)}</a>
                </td>
                <td><span class="badge ${gpuBadgeClass(p.gpu)}">${escapeHtml(p.gpu.replace("RTX ", ""))}</span></td>
                <td class="mono">${escapeHtml(p.cpu)}</td>
                <td class="mono">${p.ram_gb ? p.ram_gb + " GB" : "—"}</td>
                <td class="mono">${escapeHtml(p.storage_label !== "Unknown" ? p.storage_label : "—")}</td>
                <td class="mono">
                  <div>${fmtIsk(p.price_isk)}</div>
                  <div style="font-size:10px;color:var(--text-muted);">${escapeHtml(origLabel)}</div>
                </td>
                <td class="mono" style="font-weight:700;color:var(--text);">${fmtIsk(p.estimated_landed_isk)}</td>
                <td>
                  <div style="display:flex;gap:6px;">
                    <button class="btn btn-watch ${watching ? "watching" : ""}" data-watch="${p.id}" type="button">${watching ? "★" : "☆"}</button>
                    <a class="btn btn-primary" href="${escapeHtml(p.url)}" target="_blank" rel="noopener">↗</a>
                  </div>
                </td>
              </tr>
            `;
          }).join("")}
        </tbody>
      </table>
    </div>
  `;
  bindCardActions(container);
}

function bindCardActions(root) {
  root.querySelectorAll("[data-watch]").forEach((btn) =>
    btn.addEventListener("click", () => toggleWatch(btn.dataset.watch))
  );
  root.querySelectorAll("[data-history]").forEach((btn) =>
    btn.addEventListener("click", () => openHistoryModal(btn.dataset.history))
  );
}

function openWatchlistModal() {
  const modal = document.getElementById("watchlist-modal");
  const container = document.getElementById("watchlist-items");
  const ids = [...localWatchlist];

  if (!ids.length) {
    container.innerHTML = `<p style="color:var(--text-muted);font-size:12px;">No systems watched yet. Click "☆ Watch" on any rig to track it.</p>`;
  } else {
    container.innerHTML = ids.map((id) => {
      const p = allProducts.find((x) => x.id === id);
      return `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:12px;">
        <span>${p ? escapeHtml(p.title) + " (" + escapeHtml(p.store) + ")" : id}</span>
        <button class="btn-link" data-remove-watch="${id}" type="button">Remove</button>
      </div>`;
    }).join("");
    container.querySelectorAll("[data-remove-watch]").forEach((btn) =>
      btn.addEventListener("click", () => {
        toggleWatch(btn.dataset.removeWatch);
        openWatchlistModal();
      })
    );
  }

  const updatedJson = {
    ...repoWatchlist,
    watched_ids: ids,
  };
  document.getElementById("watchlist-json-preview").textContent = JSON.stringify(updatedJson, null, 2);

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
          <th>Retailer</th>
          <th>Region</th>
          <th>Iceland Delivery</th>
          <th>Status</th>
          <th>Rigs</th>
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
            <td class="mono">${s.count}</td>
            <td style="color:var(--text-muted);font-size:11px;">${escapeHtml(s.error || "Active")}</td>
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
    chart.innerHTML = `<p style="color:var(--text-muted);font-size:12px;">No historical price points recorded yet.</p>`;
  } else {
    chart.innerHTML = pts.map((pt) => `
      <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border);font-size:12px;">
        <span class="mono" style="color:var(--text-muted);">${new Date(pt.ts).toLocaleString("en-GB")}</span>
        <span class="mono"><strong>${fmtIsk(pt.landed_isk || pt.price_isk)}</strong> (Store: ${fmtIsk(pt.price_isk)})</span>
      </div>
    `).join("");
  }
  document.getElementById("history-modal").classList.remove("hidden");
}

function bindEvents() {
  document.querySelectorAll("#gpu-chips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const gpu = chip.dataset.gpu;
      // 1-click isolate when all GPUs are currently selected
      if (activeGpus.size === ALL_GPUS.length) {
        activeGpus = new Set([gpu]);
      } else if (activeGpus.has(gpu)) {
        if (activeGpus.size > 1) activeGpus.delete(gpu);
        else activeGpus = new Set(ALL_GPUS);
      } else {
        activeGpus.add(gpu);
      }
      syncGpuChipUI();
      render();
    });
  });

  document.getElementById("gpu-select-all").addEventListener("click", () => {
    activeGpus = new Set(ALL_GPUS);
    syncGpuChipUI();
    render();
  });

  document.getElementById("cpu-filter").addEventListener("change", () => {
    populateCpuModels();
    render();
  });

  ["search-input", "shipping-filter", "store-filter", "cpu-model-filter", "brand-filter",
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

  document.getElementById("view-cards").addEventListener("click", () => {
    viewMode = "cards";
    document.getElementById("view-cards").classList.add("active");
    document.getElementById("view-table").classList.remove("active");
    render();
  });

  document.getElementById("view-table").addEventListener("click", () => {
    viewMode = "table";
    document.getElementById("view-table").classList.add("active");
    document.getElementById("view-cards").classList.remove("active");
    render();
  });

  document.getElementById("reset-filters").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("shipping-filter").value = "all";
    document.getElementById("store-filter").value = "all";
    document.getElementById("cpu-filter").value = "all";
    populateCpuModels();
    document.getElementById("cpu-model-filter").value = "all";
    document.getElementById("brand-filter").value = "all";
    document.getElementById("ram-filter").value = "0";
    document.getElementById("storage-filter").value = "0";
    maxPriceEl.value = "1200000";
    document.getElementById("max-price-label").textContent = "No limit";
    document.getElementById("sale-only").checked = false;
    document.getElementById("stock-only").checked = true;
    document.getElementById("watched-only").checked = false;
    document.getElementById("sort-select").value = "landed_asc";
    activeGpus = new Set(ALL_GPUS);
    syncGpuChipUI();
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
