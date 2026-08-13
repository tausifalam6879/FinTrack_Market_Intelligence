import React from "react";

export default class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, details) {
    console.error("FinTrack interface render failed", error, details);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <main className="app-recovery" role="alert">
      <div className="brand-mark">F</div>
      <p className="eyebrow">INTERFACE RECOVERY</p>
      <h1>Market data could not be displayed safely.</h1>
      <p>The page stopped one unsupported provider value from breaking silently. Reload to return to the public dashboard.</p>
      <button type="button" onClick={() => window.location.reload()}>Reload FinTrack</button>
    </main>;
  }
}
