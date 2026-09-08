// Keep provider dates separate from any claim about what caused a price move.
export function eventDates(catalysts, today = new Date().toISOString().slice(0, 10)) {
  const rows = [
    ...(Array.isArray(catalysts?.events) ? catalysts.events : []),
    ...(Array.isArray(catalysts?.earningsHistory) ? catalysts.earningsHistory : [])
      .filter(item => item.status === 'reported')
      .map(item => ({...item, type: 'earnings', label: 'Reported earnings'})),
  ];
  const seen = new Set();
  return rows.filter(item => {
    const date = item?.date;
    if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
    const parsed = new Date(`${date}T00:00:00Z`);
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) return false;
    const key = `${item.type}:${date}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map(item => ({...item, key: `${item.type}:${item.date}`, future: item.date > today}))
    .sort((a, b) => b.date.localeCompare(a.date));
}
