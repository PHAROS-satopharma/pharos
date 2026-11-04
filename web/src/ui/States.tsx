import type { ReactNode } from 'react';
import { Button } from './Button';
import { errorMessage } from '../lib/api';

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="loading-rule" aria-hidden />
      <span className="soft">{label}…</span>
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state">
      <h2 className="state-title">{title}</h2>
      {children ? <div className="state-body">{children}</div> : null}
      {action ? <div className="state-action">{action}</div> : null}
    </div>
  );
}

export function ErrorNote({
  title = 'This could not be loaded.',
  error,
  onRetry,
}: {
  title?: string;
  error: unknown;
  onRetry?: () => void;
}) {
  return (
    <div className="state state-error" role="alert">
      <h2 className="state-title">{title}</h2>
      <p className="state-body">
        The server said: <span className="mono">{errorMessage(error)}</span>
      </p>
      {onRetry ? (
        <div className="state-action">
          <Button onClick={onRetry}>Try again</Button>
        </div>
      ) : null}
    </div>
  );
}

/** A one-line message inside a panel: ok, error or plain information. */
export function Notice({ tone = 'info', children }: { tone?: 'info' | 'ok' | 'error'; children: ReactNode }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}
