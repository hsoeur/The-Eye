import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/card";

/** Une erreur dans une vue n'emporte pas toute l'application. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null; key?: string }> {
  state = { error: null as Error | null, key: this.props.resetKey };

  static getDerivedStateFromError(error: Error) { return { error }; }
  static getDerivedStateFromProps(p: { resetKey?: string }, s: { key?: string }) {
    return p.resetKey !== s.key ? { error: null, key: p.resetKey } : null;
  }
  componentDidCatch(e: Error, info: ErrorInfo) { console.error(e, info.componentStack); }

  render() {
    if (!this.state.error) return this.props.children;
    return <Empty title="Cette vue a rencontré une erreur" hint={this.state.error.message}
      action={<Button onClick={() => this.setState({ error: null })}>Réessayer</Button>} />;
  }
}
