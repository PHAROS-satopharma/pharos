import { Button } from '../../ui/Button';
import { Notice } from '../../ui/States';

/**
 * What the term proposal says it could not fetch, above the term editor. Wikidata is the only source of the
 * names in other languages, so a failed or timed-out answer leaves just the English group: the person sees
 * that, and can ask for the names again before saving (ingredient-lookup terms.ts).
 */
export function TermsWarning({
  warnings,
  busy = false,
  onReload,
}: {
  warnings: string[];
  busy?: boolean;
  onReload: () => void;
}) {
  if (warnings.length === 0) return null;
  return (
    <Notice tone="error">
      <div className="terms-warning">
        <p>Some of the suggested names did not load.</p>
        <ul>
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
        <Button size="sm" busy={busy} onClick={onReload}>
          Load the names again
        </Button>
      </div>
    </Notice>
  );
}
