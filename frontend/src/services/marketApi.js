const DEFAULT_API = "http://localhost:8002";
const API_BASE = String(import.meta.env.VITE_MARKET_API_BASE_URL || DEFAULT_API).replace(/\/$/, "");
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

const request = async (path, { method = "GET", body, timeout = 30000 } = {}) => {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || `Request failed with status ${response.status}`);
    }
    return await response.json();
  } finally {
    window.clearTimeout(timer);
  }
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
  overview: (refresh = false) => withCache("overview", () => request(`/market/overview${query({ refresh })}`, { timeout: 45000 })),
  newsFeed: (refresh = false, limit = 20) => withCache("news-feed", () => request(`/market/news-feed${query({ refresh, limit })}`, { timeout: 45000 })),
  currencies: (refresh = false) => withCache("currencies", () => request(`/market/currencies${query({ refresh })}`, { timeout: 45000 })),
  analysis: (symbol, refresh = false) => withCache(`analysis.${symbol}`, () => request(`/market/analysis${query({ symbol, refresh })}`, { timeout: 60000 })),
  company: (symbol, refresh = false) => withCache(`company.${symbol}`, () => request(`/market/company${query({ symbol, refresh })}`, { timeout: 60000 })),
  agent: (payload) => request("/market/agent", { method: "POST", body: payload, timeout: 90000 })
};
