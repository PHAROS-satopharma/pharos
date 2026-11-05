import { useState } from 'react';
import { errorMessage } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { cairoToday } from '../../lib/format';
import { buildInspectionPack, daysBetween } from '../../lib/inspection';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Notice } from '../../ui/States';

/** The first day PHAROS screened (5 November 2026); a pack never starts before it. */
const FIRST_DAY = '2026-11-05';

function defaultFrom(today: string): string {
  const [y, m, d] = today.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d) - 89 * 86_400_000).toISOString().slice(0, 10);
  return t < FIRST_DAY ? FIRST_DAY : t;
}

export function InspectionPack() {
  const { person } = useAuth();
  const today = cairoToday();
  const [from, setFrom] = useState(defaultFrom(today));
  const [to, setTo] = useState(today);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const length = from && to && to >= from ? daysBetween(from, to).length : 0;
  const invalid = !from || !to || to < from || length > 366;

  async function build() {
    setBusy(true);
    setError(null);
    setStep(null);
    try {
      await buildInspectionPack(from, to, person?.full_name ?? 'an administrator', setStep);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inspection-pack">
      <p className="soft">
        One Excel workbook for an inspection or an audit: how PHAROS works, which source was read on which day, every
        notice found and every decision on it, the signals and their steps, the alerts sent, the audit trail, the
        archive checks, the sources, the watchlist and the people. It is built from the live records when you press the
        button.
      </p>
      <div className="button-row inspection-pack-form">
        <Field label="From (Cairo day)">
          <Input type="date" min={FIRST_DAY} max={to || today} value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To (Cairo day)">
          <Input type="date" min={from || FIRST_DAY} max={today} value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <Button variant="primary" busy={busy} disabled={invalid} onClick={() => void build()}>
          Download the inspection pack
        </Button>
      </div>
      {length > 366 ? <Notice tone="error">A pack covers at most 366 days. Choose a shorter period.</Notice> : null}
      {busy && step ? <Notice tone="info">{step}…</Notice> : null}
      {!busy && step && !error ? <Notice tone="ok">The pack for {length} days was saved to your downloads.</Notice> : null}
      {error ? <Notice tone="error">The pack could not be built: {error}</Notice> : null}
    </div>
  );
}
