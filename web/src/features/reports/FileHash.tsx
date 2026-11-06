import { useEffect, useState } from 'react';
import { Button } from '../../ui/Button';
import { shortHash } from '../signoff/signoff';
import '../../styles/signoff.css';

/**
 * The SHA-256 of one archived file, shortened, with a button that copies the full value: the file kept in the SOP
 * or the system master file is checked against it with `sha256sum` (or `certutil -hashfile <file> SHA256`).
 * Where the browser refuses the clipboard, the full value is shown to select by hand.
 */
export function FileHash({ hash, what }: { hash: string; what: string }) {
  const [copied, setCopied] = useState<'no' | 'yes' | 'failed'>('no');

  useEffect(() => {
    if (copied !== 'yes') return;
    const t = window.setTimeout(() => setCopied('no'), 2500);
    return () => window.clearTimeout(t);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied('yes');
    } catch {
      setCopied('failed');
    }
  }

  return (
    <span className="evidence-hash">
      <span className="evidence-hash-label">SHA-256</span>
      <code className="evidence-hash-value" title={hash}>
        {shortHash(hash)}
      </code>
      <Button size="sm" className="evidence-copy" onClick={() => void copy()} aria-label={`Copy the full SHA-256 of the ${what}`}>
        {copied === 'yes' ? 'Copied' : 'Copy'}
      </Button>
      {copied === 'failed' ? (
        <code className="evidence-hash-full" aria-label={`The full SHA-256 of the ${what}`}>
          {hash}
        </code>
      ) : null}
    </span>
  );
}
