import { Component, ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-canvas">
        <div className="card p-6 max-w-md w-full">
          <h1 className="text-lg font-semibold">Something went wrong on this page</h1>
          <p className="text-sm text-ink-muted mt-2">Your saved work is safe on the server. Reload the page or go back to
            your dashboard.</p>
          <div className="flex gap-2 mt-4">
            <button className="h-10 px-4 rounded-md bg-brand-700 text-white text-sm font-medium" onClick={() => window.location.reload()}>Reload</button>
            <a className="h-10 px-4 rounded-md border border-line text-sm font-medium inline-flex items-center" href="/app/dashboard">Go to dashboard</a>
          </div>
        </div>
      </div>
    );
  }
}
