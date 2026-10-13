export default function StatusBadge({ mode = "live", label }) {
  const text = label || (mode === "live" ? "Connected · latest available data" : mode === "snapshot" ? "Saved startup snapshot" : "Previously saved browser response");
  return <span title="Check the data timestamp. A recent fetch does not mean the market observation is current." className={`status-badge status-${mode}`}><span className="status-dot" />{text}</span>;
}
