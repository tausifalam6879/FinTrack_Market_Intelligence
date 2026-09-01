import bundledSnapshot from "../data/bundledMarketSnapshot.json";

const DEFAULT_API = "http://localhost:8081";
const API_BASE = String(import.meta.env.VITE_MARKET_API_BASE_URL || DEFAULT_API).replace(/\/$/, "");
const HOSTED_FALLBACK_API = String(
  import.meta.env.VITE_MARKET_FALLBACK_API_BASE_URL || "https://fintrack-market-gateway.onrender.com"
).replace(/\/$/, "");
const USING_LOCAL_API = /^(?:https?:\/\/)?(?:localhost|127\.0\.0\.1)(?::|\/|$)/i.test(API_BASE);
const CACHE_PREFIX = "fintrack.market.intelligence.v1";

const cacheKey = (name) => `${CACHE_PREFIX}.${name}`;

const readCache = (name) => {
  try {
    const value = localStorage.getItem(cacheKey(name));
    return value ? JSON.parse(value) : null;
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
  if (!data) return null;
  return {
    data,
    mode: "snapshot",
    savedAt: data.generatedAt || data.dataAsOf || bundledSnapshot.packagedAt,
    seedSource: "bundled"
  };
};

const request = async (path, { method = "GET", body, timeout = 30000, retry = method === "GET" } = {}) => {
  // A developer may open the Vite app before starting the local Java/Spring
  // services. Public read-only data should still work in that state, while
  // POST requests (AI questions, document preparation, comparisons) remain on
  // the explicitly configured local backend.
  const apiBases = method === "GET" && USING_LOCAL_API && HOSTED_FALLBACK_API !== API_BASE
    ? [API_BASE, HOSTED_FALLBACK_API]
    : [API_BASE];
  let lastError;
  for (let baseIndex = 0; baseIndex < apiBases.length; baseIndex += 1) {
    const apiBase = apiBases[baseIndex];
    const localFallbackAvailable = apiBase === API_BASE && USING_LOCAL_API && apiBases.length > 1;
    const attempts = localFallbackAvailable ? 1 : retry ? 2 : 1;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const controller = new AbortController();
      // Render may need extra time to wake and compute an unseen company's
      // first analysis. Keep the shorter timeout for a genuinely local service.
      const effectiveTimeout = apiBase !== API_BASE ? Math.max(timeout, 120000) : timeout;
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
          const error = new Error(detail || `Request failed with status ${response.status}`);
          error.status = response.status;
          throw error;
        }
        const payload = await response.json();
        const gateway = response.headers.get("X-FinTrack-Gateway");
        if (gateway && payload && typeof payload === "object" && !Array.isArray(payload)) {
          return {
            ...payload,
            _delivery: {
              gateway,
              requestId: response.headers.get("X-Request-Id") || null,
              responseTimeMs: response.headers.get("X-Response-Time-Ms") || null,
              fallback: apiBase !== API_BASE
            }
          };
        }
        return payload;
      } catch (error) {
        lastError = error;
        const retryable = error.name === "AbortError" || !error.status || [502, 503, 504].includes(error.status);
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
  try {
    const data = await loader();
    writeCache(name, data);
    return { data, mode: "live", savedAt: data.generatedAt || new Date().toISOString() };
  } catch (error) {
    const cached = readCache(name);
    if (cached?.data) {
      return { data: cached.data, mode: "cache", savedAt: cached.savedAt, error: error.message };
    }
    throw error;
  }
};

const query = (params) => {
  const value = new URLSearchParams(params);
  return value.toString() ? `?${value}` : "";
};

export const marketApi = {
  baseUrl: API_BASE,
  seed: {
    overview: () => seedResult("overview"),
    newsFeed: () => seedResult("news-feed"),
    currencies: () => seedResult("currencies"),
    analysis: (symbol) => seedResult(`analysis.${String(symbol || "").trim().toUpperCase()}`)
  },
  overview: (refresh = false) => withCache("overview", () => request(`/market/overview${query({ refresh })}`, { timeout: 45000 })),
  newsFeed: (refresh = false, limit = 20) => withCache("news-feed", () => request(`/market/news-feed${query({ refresh, limit })}`, { timeout: 45000 })),
  currencies: (refresh = false) => withCache("currencies", () => request(`/market/currencies${query({ refresh })}`, { timeout: 45000 })),
  analysis: (symbol, refresh = false) => withCache(`analysis.${symbol}`, () => request(`/market/analysis${query({ symbol, refresh })}`, { timeout: 60000 })),
  compare: (symbols, refresh = false) => request("/market/compare", { method: "POST", body: { symbols, refresh }, timeout: 90000, retry: true }),
  modelStatus: (symbol) => request(`/market/model-status${query({ symbol })}`, { timeout: 15000 }),
  dataOperations: (symbol) => request(`/market/data-operations${query({ symbol })}`, { timeout: 15000 }),
  databaseStatus: () => request("/market/database-status", { timeout: 15000 }),
  operationsStatus: () => request("/market/operations-status", { timeout: 15000 }),
  experiments: (symbol, limit = 8) => request(`/market/experiments${query({ symbol, limit })}`, { timeout: 15000 }),
  documents: (symbol) => request(`/market/documents${query({ symbol })}`, { timeout: 15000 }),
  discoverDocuments: (symbol) => request(`/market/documents/discover${query({ symbol })}`, { timeout: 45000 }),
  prepareDocuments: (symbol) => request("/market/documents/prepare", { method: "POST", body: { symbol }, timeout: 300000 }),
  askDocuments: (payload) => request("/market/documents/ask", { method: "POST", body: payload, timeout: 90000 }),
  predictions: (symbol, limit = 12) => request(`/market/predictions${query({ symbol, limit })}`, { timeout: 15000 }),
  company: (symbol, refresh = false) => withCache(`company.${symbol}`, () => request(`/market/company${query({ symbol, refresh })}`, { timeout: 60000 })),
  peerComparison: (symbol, refresh = false) => withCache(`peer-comparison.${symbol}`, () => request(`/market/peer-comparison${query({ symbol, refresh })}`, { timeout: 60000 })),
  companies: (search, limit = 8) => request(`/market/companies${query({ q: search, limit })}`, { timeout: 15000 }),
  agent: (payload) => request("/market/agent", { method: "POST", body: payload, timeout: 90000 })
};
