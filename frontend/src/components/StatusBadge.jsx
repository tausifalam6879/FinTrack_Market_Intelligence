export default function StatusBadge({ mode = "live", label }) {
  const text = label || (mode === "live" ? "Latest available feed" : mode === "snapshot" ? "Verified startup snapshot" : "Last verified browser cache");
  return <span className={`status-badge status-${mode}`}><span className="status-dot" />{text}</span>;
}
