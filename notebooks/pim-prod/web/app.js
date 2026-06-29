/* Light PIM — Vue 3 single-page app (no build step; uses the vendored global build).
   One root component: a catalog grid + detail drawer, an insights view, and a
   data-quality view, all reading the FastAPI backend. */
const { createApp } = Vue;

/* --- helpers ----------------------------------------------------------------- */
const api = async (url, opts) => {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
};

// Deterministic, muted color per category — the taxonomy supplies the palette.
const hueOf = (s) => {
  let h = 0;
  for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
};
const catVars = (cat) => {
  const h = hueOf(cat);
  return {
    "--cat": `hsl(${h} 52% 50%)`,
    "--cat-soft": `hsl(${h} 48% 96%)`,
    "--cat-ink": `hsl(${h} 42% 33%)`,
    "--cat-line": `hsl(${h} 38% 86%)`,
  };
};

const money = (v) =>
  typeof v === "number"
    ? new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(v)
    : "—";

// pull a unit hint out of a schema label like "number (hours)"
const unitOf = (label) => {
  if (!label) return "";
  const m = String(label).match(/\(([^)]+)\)/);
  return m ? m[1] : "";
};

createApp({
  data() {
    return {
      view: "catalog",
      // data
      products: [],
      stats: null,
      quality: null,
      schema: {},
      // ui state
      loading: true,
      error: null,
      // index picker
      index: { path: "", count: 0 },
      indexInput: "",
      discovered: [],
      switching: false,
      // filters
      filters: { categories: [], brand: "", minPrice: null, maxPrice: null },
      sort: "name",
      // search
      search: { text: "", mode: "filter", results: [], busy: false, ran: "" },
      // drawer
      selected: null,
      similar: [],
      detailLoading: false,
      confirming: false,
      deleting: false,
      // toasts
      toasts: [],
      toastId: 0,
    };
  },

  computed: {
    semanticActive() {
      return this.search.mode === "semantic" && this.search.results.length > 0;
    },
    // category list with counts (for the filter rail)
    categories() {
      const counts = {};
      for (const p of this.products) counts[p.category] = (counts[p.category] || 0) + 1;
      return Object.keys(counts).sort().map((name) => ({ name, count: counts[name] }));
    },
    brands() {
      return [...new Set(this.products.map((p) => p.brand).filter(Boolean))].sort();
    },
    priceBounds() {
      const ps = this.products.map((p) => p.price).filter((v) => typeof v === "number");
      return ps.length ? { lo: Math.min(...ps), hi: Math.max(...ps) } : { lo: 0, hi: 0 };
    },
    // the working list, after semantic ranking (if any) + rail filters
    filtered() {
      let list = this.semanticActive ? this.search.results : this.products.slice();
      const f = this.filters;
      if (f.categories.length) list = list.filter((p) => f.categories.includes(p.category));
      if (f.brand) list = list.filter((p) => p.brand === f.brand);
      if (f.minPrice != null) list = list.filter((p) => (p.price ?? Infinity) >= f.minPrice);
      if (f.maxPrice != null) list = list.filter((p) => (p.price ?? -Infinity) <= f.maxPrice);
      // text substring filter only in "filter" mode (semantic does its own ranking)
      if (!this.semanticActive && this.search.mode === "filter" && this.search.text.trim()) {
        const q = this.search.text.trim().toLowerCase();
        list = list.filter((p) =>
          [p.name, p.brand, p.category, p.short_description, p.sku]
            .some((x) => (x || "").toLowerCase().includes(q))
        );
      }
      // sort (semantic keeps relevance order)
      if (!this.semanticActive) {
        const s = this.sort;
        list.sort((a, b) => {
          if (s === "price-asc") return (a.price ?? 0) - (b.price ?? 0);
          if (s === "price-desc") return (b.price ?? 0) - (a.price ?? 0);
          if (s === "category") return a.category.localeCompare(b.category) || a.name.localeCompare(b.name);
          return (a.name || "").localeCompare(b.name || "");
        });
      }
      return list;
    },
    hasFilters() {
      const f = this.filters;
      return f.categories.length || f.brand || f.minPrice != null || f.maxPrice != null;
    },
    maxCatCount() {
      return Math.max(1, ...(this.stats?.by_category || []).map((c) => c.count));
    },
    maxBrandCount() {
      return Math.max(1, ...(this.stats?.top_brands || []).map((c) => c.count));
    },
    maxHisto() {
      return Math.max(1, ...(this.stats?.histogram || []).map((h) => h.count));
    },
  },

  methods: {
    catVars, money, unitOf,
    fmtScore(s) { return s == null ? "" : s.toFixed(2); },
    // first few attributes shown as pills on a card
    miniAttrs(p) {
      return Object.entries(p.attributes || {}).slice(0, 3).map(([k, v]) => ({ k, v }));
    },

    async loadAll() {
      this.loading = true;
      this.error = null;
      try {
        const [prod, stats, quality, cats, idx, disc] = await Promise.all([
          api("/api/products"),
          api("/api/stats"),
          api("/api/quality"),
          api("/api/categories"),
          api("/api/index"),
          api("/api/index/discover"),
        ]);
        this.products = prod.products;
        this.stats = stats;
        this.quality = quality;
        this.schema = cats.schema;
        this.index = idx;
        this.indexInput = idx.path;
        this.discovered = disc.indexes;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    async refreshData() {
      // after a delete: refresh products + stats + quality without the full spinner
      const [prod, stats, quality, idx] = await Promise.all([
        api("/api/products"), api("/api/stats"), api("/api/quality"), api("/api/index"),
      ]);
      this.products = prod.products;
      this.stats = stats;
      this.quality = quality;
      this.index = idx;
    },

    async switchIndex() {
      const path = this.indexInput.trim();
      if (!path || path === this.index.path) return;
      this.switching = true;
      this.error = null;
      try {
        this.index = await api("/api/index", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        this.resetFilters();
        this.search.results = [];
        this.search.text = "";
        await this.loadAll();
        this.toast("Loaded " + this.index.count + " products", "ok");
      } catch (e) {
        this.toast(e.message, "err");
        this.indexInput = this.index.path; // revert the field
      } finally {
        this.switching = false;
      }
    },

    // filters --------------------------------------------------------------
    toggleCat(name) {
      const i = this.filters.categories.indexOf(name);
      if (i === -1) this.filters.categories.push(name);
      else this.filters.categories.splice(i, 1);
    },
    resetFilters() {
      this.filters = { categories: [], brand: "", minPrice: null, maxPrice: null };
    },

    // search ---------------------------------------------------------------
    async runSearch() {
      const q = this.search.text.trim();
      if (this.search.mode !== "semantic") return;
      if (!q) { this.search.results = []; this.search.ran = ""; return; }
      this.search.busy = true;
      try {
        const res = await api("/api/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: q, k: 24 }),
        });
        this.search.results = res.results;
        this.search.ran = q;
      } catch (e) {
        this.toast(e.message, "err");
      } finally {
        this.search.busy = false;
      }
    },
    setMode(mode) {
      this.search.mode = mode;
      if (mode === "filter") { this.search.results = []; this.search.ran = ""; }
      else if (this.search.text.trim()) this.runSearch();
    },
    onSearchEnter() {
      if (this.search.mode === "semantic") this.runSearch();
    },

    // drawer ---------------------------------------------------------------
    async openProduct(sku) {
      this.confirming = false;
      this.detailLoading = true;
      this.selected = { sku }; // open immediately with a skeleton
      this.similar = [];
      try {
        const [detail, sim] = await Promise.all([
          api("/api/products/" + encodeURIComponent(sku)),
          api("/api/products/" + encodeURIComponent(sku) + "/similar?k=5"),
        ]);
        this.selected = detail;
        this.similar = sim.similar;
      } catch (e) {
        this.toast(e.message, "err");
        this.selected = null;
      } finally {
        this.detailLoading = false;
      }
    },
    closeDrawer() { this.selected = null; this.confirming = false; },

    // build the full attribute table: every expected attr + any extras present
    attrRows(p) {
      const expected = p.expected_attributes || {};
      const present = p.attributes || {};
      const keys = [...new Set([...Object.keys(expected), ...Object.keys(present)])];
      return keys.map((k) => ({
        key: k,
        value: present[k],
        unit: unitOf(expected[k]),
        missing: !(k in present),
        // present on the product but not declared in the category's PIM schema
        extra: (k in present) && !(k in expected),
      }));
    },

    // record-level metadata that isn't part of the PIM model at all
    extraMeta(p) {
      return Object.entries((p && p.extra) || {});
    },

    async confirmDelete() { this.confirming = true; },
    async doDelete() {
      const sku = this.selected.sku;
      this.deleting = true;
      try {
        await api("/api/products/" + encodeURIComponent(sku), { method: "DELETE" });
        this.toast("Deleted " + sku, "ok");
        this.closeDrawer();
        await this.refreshData();
      } catch (e) {
        this.toast(e.message, "err");
      } finally {
        this.deleting = false;
      }
    },

    // toasts ---------------------------------------------------------------
    toast(msg, type) {
      const id = ++this.toastId;
      this.toasts.push({ id, msg, type });
      setTimeout(() => {
        this.toasts = this.toasts.filter((t) => t.id !== id);
      }, 2600);
    },
  },

  mounted() { this.loadAll(); },

  template: `
<div class="app">
  <!-- ====================== HEADER ====================== -->
  <header class="app-header">
    <div class="header-row">
      <div class="brand">
        <span class="mark"></span>
        <span class="word">Light&nbsp;<b>PIM</b></span>
        <span class="tag">catalog console</span>
      </div>
      <div class="spacer"></div>

      <div class="index-picker">
        <span class="label">Index</span>
        <select v-if="discovered.length" v-model="indexInput" :title="indexInput">
          <option v-for="d in discovered" :key="d.path" :value="d.path">{{ d.label }}</option>
        </select>
        <input v-model="indexInput" @keyup.enter="switchIndex" placeholder="path to chroma_index" :title="indexInput" />
        <button class="btn sm" :disabled="switching || indexInput.trim()===index.path" @click="switchIndex">
          {{ switching ? '…' : 'Load' }}
        </button>
      </div>

      <div class="stat-chip" v-if="stats">
        <span class="dot"></span>
        <span><b>{{ stats.total }}</b> products</span>
        <span style="color:var(--line-2)">·</span>
        <span><b>{{ stats.categories }}</b> categories</span>
      </div>
    </div>

    <div class="header-row bottom">
      <nav class="tabs">
        <button class="tab" :class="{active: view==='catalog'}" @click="view='catalog'">Catalog</button>
        <button class="tab" :class="{active: view==='insights'}" @click="view='insights'">Insights</button>
        <button class="tab" :class="{active: view==='quality'}" @click="view='quality'">Data quality</button>
      </nav>
      <div class="spacer"></div>
      <div class="search" v-if="view==='catalog'">
        <div class="field">
          <span class="ic">⌕</span>
          <input :placeholder="search.mode==='semantic' ? 'Describe a product…' : 'Filter by name, brand…'"
                 v-model="search.text" @keyup.enter="onSearchEnter" />
        </div>
        <div class="seg">
          <button :class="{on: search.mode==='filter'}" @click="setMode('filter')">Filter</button>
          <button :class="{on: search.mode==='semantic'}" @click="setMode('semantic')">Semantic</button>
        </div>
      </div>
    </div>
  </header>

  <main>
    <!-- global error -->
    <div class="banner error" v-if="error">⚠ {{ error }}</div>

    <!-- loading -->
    <div v-if="loading" class="skeleton-grid">
      <div class="skeleton" v-for="n in 8" :key="n"></div>
    </div>

    <!-- ====================== CATALOG ====================== -->
    <div v-else-if="view==='catalog'" class="catalog-layout">
      <!-- filter rail -->
      <aside class="rail">
        <div class="group">
          <div class="eyebrow">
            <span>Category</span>
            <span class="clear" v-if="hasFilters" @click="resetFilters">Clear all</span>
          </div>
          <div class="check-list">
            <label class="check" v-for="c in categories" :key="c.name" :style="catVars(c.name)">
              <input type="checkbox" :checked="filters.categories.includes(c.name)" @change="toggleCat(c.name)" />
              <span class="cat-dot" style="background:var(--cat)"></span>
              <span class="nm">{{ c.name }}</span>
              <span class="ct">{{ c.count }}</span>
            </label>
          </div>
        </div>

        <div class="group">
          <div class="eyebrow">Brand</div>
          <select v-model="filters.brand">
            <option value="">All brands</option>
            <option v-for="b in brands" :key="b" :value="b">{{ b }}</option>
          </select>
        </div>

        <div class="group">
          <div class="eyebrow">Price (€)</div>
          <div class="price-row">
            <input type="number" v-model.number="filters.minPrice" :placeholder="'min '+Math.floor(priceBounds.lo)" />
            <span>—</span>
            <input type="number" v-model.number="filters.maxPrice" :placeholder="'max '+Math.ceil(priceBounds.hi)" />
          </div>
        </div>
      </aside>

      <!-- results -->
      <section>
        <div class="results-bar">
          <span class="count"><b>{{ filtered.length }}</b> {{ filtered.length===1?'product':'products' }}</span>
          <span class="score" v-if="semanticActive">semantic · "{{ search.ran }}"</span>
          <span class="count" v-if="search.busy">searching…</span>
          <div class="sortwrap" v-if="!semanticActive">
            <span class="eyebrow">Sort</span>
            <select v-model="sort">
              <option value="name">Name A–Z</option>
              <option value="price-asc">Price ↑</option>
              <option value="price-desc">Price ↓</option>
              <option value="category">Category</option>
            </select>
          </div>
        </div>

        <div v-if="filtered.length===0" class="center-state">
          <div class="big">No products match</div>
          <div>Try clearing a filter or switching search mode.</div>
        </div>

        <div v-else class="grid">
          <button class="card" v-for="p in filtered" :key="p.sku" :style="catVars(p.category)"
                  @click="openProduct(p.sku)">
            <div class="card-top">
              <span class="sku">{{ p.sku }}</span>
              <span class="score" v-if="semanticActive && p.score != null">{{ fmtScore(p.score) }}</span>
              <span class="cat-badge" v-else><span class="cat-dot"></span>{{ p.category }}</span>
            </div>
            <div class="name">{{ p.name }}</div>
            <div class="brand">{{ p.brand }}</div>
            <div class="desc">{{ p.short_description }}</div>
            <div class="attr-mini">
              <span class="pill" v-for="a in miniAttrs(p)" :key="a.k">{{ a.k }}: {{ a.v }}</span>
            </div>
            <div class="card-foot">
              <span class="price">{{ money(p.price) }} <span class="cur">€</span></span>
              <span class="cat-badge" v-if="semanticActive"><span class="cat-dot"></span>{{ p.category }}</span>
            </div>
          </button>
        </div>
      </section>
    </div>

    <!-- ====================== INSIGHTS ====================== -->
    <div v-else-if="view==='insights' && stats" class="insights">
      <div class="stat-cards">
        <div class="kpi accent"><span class="n">{{ stats.total }}</span><span class="l">Products</span></div>
        <div class="kpi"><span class="n">{{ stats.categories }}</span><span class="l">Categories</span></div>
        <div class="kpi"><span class="n">{{ stats.brands }}</span><span class="l">Brands</span></div>
        <div class="kpi" v-if="stats.price"><span class="n">{{ money(stats.price.avg) }}</span><span class="l">Avg price €</span></div>
        <div class="kpi" v-if="stats.price"><span class="n">{{ money(stats.price.max) }}</span><span class="l">Max price €</span></div>
      </div>

      <div class="panel">
        <h3>Products per category</h3>
        <div class="bars">
          <div class="bar-row" v-for="c in stats.by_category" :key="c.name" :style="catVars(c.name)">
            <span class="lab">{{ c.name }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{width: (100*c.count/maxCatCount)+'%'}"></div></div>
            <span class="val">{{ c.count }}</span>
          </div>
        </div>
      </div>

      <div class="panel" v-if="stats.histogram.length">
        <h3>Price distribution</h3>
        <div class="sub">{{ money(stats.price.min) }} € – {{ money(stats.price.max) }} €</div>
        <div class="histo">
          <div class="col" v-for="(h,i) in stats.histogram" :key="i">
            <span class="cv">{{ h.count }}</span>
            <div class="h" :style="{height: (100*h.count/maxHisto)+'%'}" :title="h.from+' – '+h.to+' €'"></div>
            <span class="cl">{{ Math.round(h.from) }}</span>
          </div>
        </div>
      </div>

      <div class="panel">
        <h3>Top brands</h3>
        <div class="bars">
          <div class="bar-row" v-for="b in stats.top_brands" :key="b.name">
            <span class="lab">{{ b.name }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{width:(100*b.count/maxBrandCount)+'%', background:'var(--ink-2)'}"></div></div>
            <span class="val">{{ b.count }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ====================== QUALITY ====================== -->
    <div v-else-if="view==='quality' && quality" class="quality">
      <div class="panel" style="gap:6px">
        <h3>Attribute completeness</h3>
        <div class="sub">Products are checked against their category's expected attribute schema.</div>
      </div>
      <div class="q-summary">
        <div class="q-row head">
          <span>Category</span><span>Complete</span><span></span><span style="text-align:right">%</span>
        </div>
        <div class="q-row" v-for="r in quality.summary" :key="r.category" :style="catVars(r.category)">
          <span class="cat"><span class="cat-dot" style="background:var(--cat);width:9px;height:9px;border-radius:2px"></span>{{ r.category }}</span>
          <span class="frac">{{ r.complete }}/{{ r.products }}</span>
          <div class="q-track"><div class="q-fill" :style="{width:r.completeness+'%', background: r.completeness===100 ? 'var(--cat)' : 'var(--danger)'}"></div></div>
          <span class="pct" :style="{color: r.completeness===100 ? 'var(--ink-2)' : 'var(--danger)'}">{{ r.completeness }}</span>
        </div>
      </div>

      <div class="panel" style="gap:6px" v-if="quality.issues.length">
        <h3>{{ quality.issues.length }} products with missing attributes</h3>
        <div class="sub">Click a row to inspect and fix.</div>
      </div>
      <div class="issues" v-if="quality.issues.length">
        <div class="issue" v-for="it in quality.issues" :key="it.sku" @click="openProduct(it.sku)">
          <span class="sku">{{ it.sku }}</span>
          <span class="nm">{{ it.name }}</span>
          <span class="miss">
            <span class="miss-tag" v-for="m in it.missing" :key="m">{{ m }}</span>
          </span>
        </div>
      </div>
      <div v-else class="center-state">
        <div class="big">All products complete ✓</div>
        <div>Every product has the attributes its category expects.</div>
      </div>
    </div>
  </main>

  <!-- ====================== DRAWER ====================== -->
  <transition name="fade">
    <div class="scrim" v-if="selected" @click="closeDrawer"></div>
  </transition>
  <transition name="slide">
    <aside class="drawer" v-if="selected">
      <div v-if="detailLoading && !selected.name" class="center-state" style="flex:1">
        <div class="spinner"></div>
      </div>
      <template v-else>
        <div class="drawer-head" :style="catVars(selected.category)">
          <button class="close" @click="closeDrawer" aria-label="Close">✕</button>
          <span class="sku">{{ selected.sku }}</span>
          <h2>{{ selected.name }}</h2>
          <div class="meta-line">
            <span class="cat-badge"><span class="cat-dot"></span>{{ selected.category }}</span>
            <span class="brand" style="color:var(--ink-2)">{{ selected.brand }}</span>
            <span class="spacer"></span>
            <span class="price">{{ money(selected.price) }} <span class="cur">€</span></span>
          </div>
        </div>

        <div class="drawer-body">
          <div class="section" v-if="selected.document">
            <span class="eyebrow">Description</span>
            <p class="blurb">{{ selected.document }}</p>
          </div>

          <div class="section">
            <span class="eyebrow">Attributes</span>
            <div class="attr-table">
              <div class="attr-row" v-for="a in attrRows(selected)" :key="a.key" :class="{missing:a.missing, extra:a.extra}">
                <span class="k">
                  <span class="warn" v-if="a.missing">⚠</span>{{ a.key }}
                  <span class="extra-tag" v-if="a.extra" title="Present on the product but not part of the category's PIM schema">not in schema</span>
                </span>
                <span class="v" v-if="!a.missing">{{ a.value }} <span class="unit" v-if="a.unit">{{ a.unit }}</span></span>
                <span class="v" v-else>missing</span>
              </div>
            </div>
          </div>

          <div class="section" v-if="extraMeta(selected).length">
            <span class="eyebrow">Extra metadata</span>
            <p class="sub" style="margin:-2px 0 8px">Off-model fields on the record — not part of the PIM structure, but available to enrich the product later.</p>
            <div class="attr-table">
              <div class="attr-row extra" v-for="[k, v] in extraMeta(selected)" :key="k">
                <span class="k">{{ k }}</span>
                <span class="v">{{ v }}</span>
              </div>
            </div>
          </div>

          <div class="section" v-if="similar.length">
            <span class="eyebrow">Similar products</span>
            <div class="sim-strip">
              <button class="sim-card" v-for="s in similar" :key="s.sku" :style="catVars(s.category)" @click="openProduct(s.sku)">
                <span class="sku">{{ s.sku }}</span>
                <span class="nm">{{ s.name }}</span>
                <div class="row">
                  <span class="price" style="font-size:12.5px">{{ money(s.price) }} <span class="cur">€</span></span>
                  <span class="score" v-if="s.score!=null">{{ fmtScore(s.score) }}</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        <div class="drawer-foot">
          <transition name="pop" mode="out-in">
            <div class="confirm" v-if="confirming" key="confirm" style="flex:1">
              <p>Delete <b>{{ selected.name }}</b> ({{ selected.sku }})? This removes it from the vector index permanently.</p>
              <div class="row">
                <button class="btn ghost" @click="confirming=false" :disabled="deleting">Cancel</button>
                <button class="btn danger" @click="doDelete" :disabled="deleting">{{ deleting ? 'Deleting…' : 'Delete' }}</button>
              </div>
            </div>
            <button class="btn danger" v-else key="btn" @click="confirmDelete">🗑 Delete product</button>
          </transition>
        </div>
      </template>
    </aside>
  </transition>

  <!-- ====================== TOASTS ====================== -->
  <div class="toasts">
    <transition-group name="pop">
      <div class="toast" :class="{err: t.type==='err'}" v-for="t in toasts" :key="t.id">
        <span class="ok" v-if="t.type==='ok'">✓</span>
        <span v-if="t.type==='err'">⚠</span>
        {{ t.msg }}
      </div>
    </transition-group>
  </div>
</div>
  `,
}).mount("#app");
