export default function StatusBadge({ mode = "live", label }) {
  const text = label || (mode === "live" ? "Latest available feed" : "Last verified browser cache");
  return <span className={`status-badge status-${mode}`}><span className="status-dot" />{text}</span>;
}

