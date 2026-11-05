import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button } from './Button';
import { errorMessage } from '../lib/api';

interface Props {
  children: ReactNode;
  /** Wraps the message, e.g. `bare` when nothing else (no header) is on the screen. */
  className?: string;
}

interface State {
  error: unknown;
  failed: boolean;
}

/**
 * Catches a render error below it, so a broken page shows a plain message with a Reload button
 * instead of a blank white screen. Give it a `key` (e.g. the path) to start fresh on navigation.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, failed: false };

  static getDerivedStateFromError(error: unknown): State {
    return { error, failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('PHAROS page error', error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const message = (
      <div className="state state-error" role="alert">
        <h2 className="state-title">Something went wrong on this page.</h2>
        <div className="state-body">
          <p>Reload the page to try again. If it happens again, tell an administrator what you were doing.</p>
          <details className="error-details">
            <summary>Details</summary>
            <p className="mono">{errorMessage(this.state.error)}</p>
          </details>
        </div>
        <div className="state-action">
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      </div>
    );
    return this.props.className ? <div className={this.props.className}>{message}</div> : message;
  }
}
