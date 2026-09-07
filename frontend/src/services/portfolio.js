export const PORTFOLIO_KEY = 'fintrack.portfolio.v1';

export function validateHolding(input) {
  const quantity = Number(input.quantity);
  const buyPrice = Number(input.buyPrice);
  const symbol = String(input.symbol || '').trim().toUpperCase();
  const currency = String(input.currency || '').trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.&=-]{0,19}$/.test(symbol)) throw new Error('Select a company before saving a holding.');
  if (!/^[A-Z]{3}$/.test(currency)) throw new Error('A known quote currency is required.');
  if (!Number.isFinite(quantity) || quantity <= 0 || quantity > 1e9) throw new Error('Quantity must be greater than zero and at most one billion.');
  if (!Number.isFinite(buyPrice) || buyPrice <= 0 || buyPrice > 1e12) throw new Error('Average buy price must be greater than zero and at most one trillion.');
  return { symbol, currency, quantity, buyPrice, name: String(input.name || symbol).slice(0,200) };
}

export function portfolioSummary(holdings, quotes) {
  const groups = {};
  for (const holding of holdings) {
    const h = validateHolding(holding);
    const group = groups[h.currency] ||= { currency:h.currency, investment:0, value:0, missing:0, rows:[] };
    const quote = quotes[h.symbol];
    const price = Number(quote?.price);
    const available = quote?.price != null && Number.isFinite(price) && price > 0 && quote.currency === h.currency;
    const cost = h.quantity * h.buyPrice;
    const value = available ? h.quantity * price : null;
    group.investment += cost;
    if (available) group.value += value; else group.missing += 1;
    group.rows.push({...h, price:available ? price : null, cost, value, pnl:available ? value-cost : null, quote});
  }
  return Object.values(groups).map(g => ({...g, value:g.missing ? null : g.value,
    pnl:g.missing ? null : g.value-g.investment,
    returnPercent:g.missing ? null : (g.value/g.investment-1)*100}));
}
