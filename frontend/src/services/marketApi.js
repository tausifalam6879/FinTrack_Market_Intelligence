import bundledSnapshot from "../data/bundledMarketSnapshot.json";

const DEFAULT_API = "http://localhost:8081";
const API_BASE = String(import.meta.env.VITE_MARKET_API_BASE_URL || DEFAULT_API).replace(/\/$/, "");
const HOSTED_FALLBACK_API = String(
  import.meta.env.VITE_MARKET_FALLBACK_API_BASE_URL || "https://fintrack-market-gateway.onrender.com"
).replace(/\/$/, "");
const USING_LOCAL_API = /^(?:https?:\/\/)?(?:localhost|127\.0\.0\.1)(?::|\/|$)/i.test(API_BASE);
const CACHE_PREFIX = "fintrack.market.intelligence.v1";
const HOSTED_FAILOVER_ENABLED = import.meta.env.VITE_MARKET_FAILOVER_ENABLED === "true";
const READ_ONLY_POSTS = new Set(["/market/agent", "/market/compare", "/market/documents/ask"]);
let primaryUnavailableUntil = 0;
const pendingReads = new Map();

const cacheKey = (name) => `${CACHE_PREFIX}.${name}`;

const isPositiveNumber = (value) => {
  if (value === null || value === undefined || value === "") return false;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0;
};

const isUsableCurrencyData = (data) => (
  Array.isArray(data?.currencies)
  && data.currencies.some((item) => isPositiveNumber(item?.inrValue))
);

const isUsableData = (name, data) => {
  if (name === "currencies") return isUsableCurrencyData(data);
  if (name === "news-feed") return Array.isArray(data?.articles) && data.articles.some((article) => article?.title);
  return true;
};

const readCache = (name) => {
  try {
    const value = localStorage.getItem(cacheKey(name));
    const cached = value ? JSON.parse(value) : null;
    if (cached?.data && !isUsableData(name, cached.data)) {
      localStorage.removeItem(cacheKey(name));
      return null;
    }
    return cached;
  } catch {
    return null;
  }
};

const writeCache = (name, data) => {
  try {
    localStorage.setItem(cacheKey(name), JSON.stringify({ data, savedAt: new Date().toISOString() }));
  } catch {
    // Private browsing or full storage must not break the public dashboard.
  }
};

const bundledData = (name) => {
  if (name === "overview") return bundledSnapshot.overview;
  if (name === "currencies") return bundledSnapshot.currencies;
  if (name === "news-feed") return bundledSnapshot.newsFeed;
  if (name.startsWith("analysis.")) return bundledSnapshot.analysis?.[name.slice("analysis.".length)];
  return null;
};

const seedResult = (name) => {
  const cached = readCache(name);
  if (cached?.data) {
    return { data: cached.data, mode: "cache", savedAt: cached.savedAt, seedSource: "browser" };
  }

  const data = bundledData(name);
  if (!data || !isUsableData(name, data)) return null;
  return {
    data,
    mode: "snapshot",
    savedAt: data.generatedAt || data.dataAsOf || bundledSnapshot.packagedAt,
    seedSource: "bundled"
  };
};

const request = async (path, { method = "GET", body, timeout = 30000, retry = method === "GET", allowFailover = true } = {}) => {
  const offline = window.navigator?.onLine === false;
  if (offline && !USING_LOCAL_API) throw new TypeError("Offline: showing stored research.");
  // Replay only research reads. Document preparation can write shared state
  // and must never be repeated on another host after an ambiguous failure.
  const canFailover = allowFailover && !offline && HOSTED_FALLBACK_API !== API_BASE && (
    (USING_LOCAL_API && method === "GET")
    || (!USING_LOCAL_API && HOSTED_FAILOVER_ENABLED
      && (method === "GET" || READ_ONLY_POSTS.has(path.split("?")[0])))
  );
  // A short circuit avoids making every click wait on a known failed primary.
  // The next request after one minute tries Google again before using Render.
  const apiBases = canFailover
    ? Date.now() < primaryUnavailableUntil ? [HOSTED_FALLBACK_API] : [API_BASE, HOSTED_FALLBACK_API]
    : [API_BASE];
  let lastError;
  for (let baseIndex = 0; baseIndex < apiBases.length; baseIndex += 1) {
    const apiBase = apiBases[baseIndex];
    const attempts = canFailover ? 1 : retry ? 2 : 1;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const controller = new AbortController();
      // Each endpoint already supplies a timeout that reflects its cost.
      // Do not silently turn a 15-second directory/status request into a
      // two-minute wait just because the fallback happens to be hosted.
      const effectiveTimeout = timeout;
      const timer = window.setTimeout(() => controller.abort(), effectiveTimeout);
      try {
        const response = await fetch(`${apiBase}${path}`, {
          method,
          headers: { "Content-Type": "application/json" },
          body: body ? JSON.stringify(body) : undefined,
          signal: controller.signal
        });
        if (!response.ok) {
          const detail = await response.text();
          let message = detail;
          try { const parsed = JSON.parse(detail); message = parsed.detail?.message || parsed.detail || detail; } catch { /* Non-JSON gateway error. */ }
          const error = new Error(typeof message === "string" ? message : `Request failed with status ${response.status}`);
          error.status = response.status;
          const retryAfter = response.headers.get("Retry-After");
          if (retryAfter) error.retryAfterMs = Math.min(300000, Math.max(0,
            /^\d+$/.test(retryAfter) ? Number(retryAfter)*1000 : Date.parse(retryAfter)-Date.now()));
          // Cloud Run can reject requests at Google's edge when the service
          // is unavailable. Do not confuse this HTML response with app JSON
          // permission/input errors, which must stay on the primary.
          error.platformUnavailable = response.status === 403
            && (response.headers.get("Content-Type") || "").includes("text/html")
            && /Your client does not have permission to get URL/i.test(detail);
          throw error;
        }
        const payload = await response.json();
        if (apiBase === API_BASE) primaryUnavailableUntil = 0;
        const gateway = response.headers.get("X-FinTrack-Gateway");
        if (payload && typeof payload === "object" && !Array.isArray(payload)) {
          return {
            ...payload,
            _delivery: {
              gateway: gateway || null,
              requestId: response.headers.get("X-Request-Id") || null,
              responseTimeMs: response.headers.get("X-Response-Time-Ms") || null,
              fallback: apiBase !== API_BASE
            }
          };
        }
        return payload;
      } catch (error) {
        lastError = error;
        const unavailable = error.name === "AbortError"
          || error instanceof TypeError
          || error.platformUnavailable === true
          || [500, 502, 503, 504].includes(error.status);
        if (canFailover && unavailable) {
          if (apiBase === API_BASE) primaryUnavailableUntil = Date.now() + 60000;
          break;
        }
        // Invalid inputs, rate limits, permissions and malformed responses
        // must not be turned into traffic on a different server.
        if (canFailover) throw error;
        const retryable = error.name !== "AbortError" && (!error.status || [502, 503, 504].includes(error.status));
        if (!retryable) throw error;
        const retryCurrentBase = attempt + 1 < attempts;
        if (retryCurrentBase) await new Promise((resolve) => window.setTimeout(resolve, 350 * (attempt + 1)));
        else break;
      } finally {
        window.clearTimeout(timer);
      }
    }
  }
  throw lastError;
};

const withCache = async (name, loader) => {
  if (pendingReads.has(name)) return pendingReads.get(name);
  const pending = loadWithCache(name, loader).finally(() => pendingReads.delete(name));
  pendingReads.set(name, pending);
  return pending;
};

const loadWithCache = async (name, loader) => {
  try {
    const data = await loader();
    if (!isUsableData(name, data)) {
      throw new Error(name === "news-feed" ? "The headline provider returned no usable headlines." : "The currency provider returned no usable positive INR rates.");
    }
    writeCache(name, data);
    return { data, mode: data.deliveryMode === "stored" ? "stored" : "live", savedAt: data.generatedAt || new Date().toISOString(),
      freshness: { fetchedAt: new Date().toISOString(), dataAsOf: data.dataAsOf || data.generatedAt || null,
        notice: "Latest available provider response; quotes may be delayed. Fetch time is not market observation time." } };
  } catch (error) {
    const cached = seedResult(name);
    if (cached?.data) {
      return { ...cached, error: error.message, retryAfterMs: error.retryAfterMs || 0 };
    }
    throw error;
  }
};

const storedCompanies = (search = "", limit = 20) => {
  const found = new Map();
  const candidates = [...(readCache("stored-companies")?.data?.items || []),
    ...Object.values(bundledSnapshot.analysis || {})];
  // Browser responses retain dynamic companies even if MySQL is temporarily unreachable.
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key?.startsWith(cacheKey("analysis."))) {
        const value = readCache(key.slice(CACHE_PREFIX.length + 1));
        if (value?.data) candidates.push(value.data);
      }
    }
  } catch { /* Stored server directory and bundled data still work. */ }
  const needle = search.trim().toUpperCase();
  for (const item of candidates) {
    if (!item?.symbol || found.has(item.symbol)) continue;
    if (needle && !`${item.symbol} ${item.name || ""}`.toUpperCase().includes(needle)) continue;
    found.set(item.symbol, { ...item, name: item.name || item.symbol, exchange: item.exchange || "Stored", source: "Stored research" });
  }
  return [...found.values()].sort((a, b) => Number(b.symbol === needle) - Number(a.symbol === needle)).slice(0, limit);
};

const query = (params) => {
  const value = new URLSearchParams(params);
  return value.toString() ? `?${value}` : "";
};

const offlineResearch = async (symbol, kind, cacheName) => {
  const seed = seedResult(`${cacheName}.${symbol}`);
  if (seed) return seed;
  const response = await marketApi.storedResearch(symbol);
  const saved = response.data?.[kind];
  if (!saved?.data) throw new Error("No previously stored evidence is available for this panel.");
  return { ...saved, mode: "stored" };
};

const dashboardRead = (name, loader) => {
  const seed = window.navigator?.onLine === false ? seedResult(name) : null;
  return seed ? Promise.resolve(seed) : withCache(name, loader);
};

export const marketApi = {
  baseUrl: API_BASE,
  backtest: (symbol) => request(`/market/backtest${query({symbol})}`, {timeout:90000,retry:false}),
  eventImpact: (symbol,event_date) => request(`/market/event-impact${query({symbol,event_date})}`, {timeout:90000,retry:false}),
  seed: {
    overview: () => seedResult("overview"),
    newsFeed: () => seedResult("news-feed"),
    currencies: () => seedResult("currencies"),
    companies: storedCompanies,
    company: (symbol) => seedResult(`company.${symbol}`),
    peers: (symbol) => seedResult(`peer-comparison.${symbol}`),
    modelStatus: (symbol) => seedResult(`model-status.${symbol}`),
    experiments: (symbol) => seedResult(`experiments.${symbol}`),
    analysis: (symbol) => seedResult(`analysis.${String(symbol || "").trim().toUpperCase()}`)
  },
  offlineReadiness: () => withCache('offline-readiness', () => request('/market/offline-readiness', {timeout:5000,retry:false,allowFailover:false})),
  refreshStored: (symbol) => withCache(`analysis.${symbol}`, () => request(`/market/analysis${query({symbol,refresh:true})}`, {timeout:30000,retry:false,allowFailover:false})),
  storedResearch: (symbol = "") => withCache(`stored-research.${symbol}`, async () => {
    const payload = await request(`/market/stored-research${query(symbol ? { symbol } : {})}`, { timeout: 5000, retry: false, allowFailover: false });
    if (!symbol) writeCache("stored-companies", payload);
    for (const [key, name] of [["analysis", "analysis"], ["company", "company"], ["peers", "peer-comparison"]]) {
      const saved = payload[key];
      if (!saved?.data) continue;
      const existing = readCache(`${name}.${symbol}`);
      const observedAt = (data) => Date.parse(data?.dataAsOf || data?.generatedAt || "") || 0;
      if (!existing?.data || observedAt(saved.data) >= observedAt(existing.data)) {
        try { localStorage.setItem(cacheKey(`${name}.${symbol}`), JSON.stringify(saved)); } catch { /* Optional storage. */ }
      }
    }
    return payload;
  }),
  overview: (refresh = false) => dashboardRead("overview", () => request(`/market/overview${query({ refresh })}`, { timeout: 45000 })),
  newsFeed: (refresh = false, limit = 20) => dashboardRead("news-feed", () => request(`/market/news-feed${query({ refresh, limit })}`, { timeout: 45000 })),
  currencies: (refresh = false) => dashboardRead("currencies", () => request(`/market/currencies${query({ refresh })}`, { timeout: 45000 })),
  analysis: (symbol, refresh = false) => window.navigator?.onLine === false
    ? offlineResearch(symbol, "analysis", "analysis")
    : withCache(`analysis.${symbol}`, () => request(`/market/analysis${query({ symbol, refresh })}`, { timeout: 60000 })),
  compare: (symbols, refresh = false) => request("/market/compare", { method: "POST", body: { symbols, refresh }, timeout: 90000, retry: true }),
  modelStatus: (symbol) => withCache(`model-status.${symbol}`, () => request(`/market/model-status${query({ symbol })}`, { timeout: 15000 })).then(result => result.data),
  dataOperations: (symbol) => request(`/market/data-operations${query({ symbol })}`, { timeout: 15000 }),
  databaseStatus: () => request("/market/database-status", { timeout: 15000 }),
  operationsStatus: () => request("/market/operations-status", { timeout: 15000 }),
  experiments: (symbol, limit = 8) => withCache(`experiments.${symbol}`, () => request(`/market/experiments${query({ symbol, limit })}`, { timeout: 15000 })).then(result => result.data),
  documents: (symbol) => request(`/market/documents${query({ symbol })}`, { timeout: 15000 }),
  discoverDocuments: (symbol) => request(`/market/documents/discover${query({ symbol })}`, { timeout: 45000 }),
  prepareDocuments: (symbol) => request("/market/documents/prepare", { method: "POST", body: { symbol }, timeout: 300000 }),
  askDocuments: (payload) => request("/market/documents/ask", { method: "POST", body: payload, timeout: 90000 }),
  predictions: (symbol, limit = 12) => request(`/market/predictions${query({ symbol, limit })}`, { timeout: 15000 }),
  company: (symbol, refresh = false) => window.navigator?.onLine === false
    ? offlineResearch(symbol, "company", "company")
    : withCache(`company.${symbol}`, () => request(`/market/company${query({ symbol, refresh })}`, { timeout: 60000 })),
  peerComparison: (symbol, refresh = false) => window.navigator?.onLine === false
    ? offlineResearch(symbol, "peers", "peer-comparison")
    : withCache(`peer-comparison.${symbol}`, () => request(`/market/peer-comparison${query({ symbol, refresh })}`, { timeout: 60000 })),
  companies: (search, limit = 8) => {
    const items = storedCompanies(search, limit);
    if (items.length) return Promise.resolve({ items, mode: "stored" });
    if (window.navigator?.onLine === false) return Promise.resolve({ items: [], mode: "stored" });
    return request(`/market/companies${query({ q: search, limit })}`, { timeout: 15000, retry: false });
  },
  agent: (payload) => request("/market/agent", { method: "POST", body: payload, timeout: 90000 })
};
