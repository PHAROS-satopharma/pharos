import { useState } from 'react';
import { downloadArchived, errorMessage } from '../../lib/api';
import { Button } from '../../ui/Button';
import { Loading, Notice } from '../../ui/States';
import { useInboundEmail, type InboundEmail } from './queries';

/** Plain text of a message: its text part, else its HTML part read as text (never rendered as HTML). */
function emailText(m: InboundEmail): string {
  if (m.text_body && m.text_body.trim()) return m.text_body.trim();
  if (!m.html_body) return '';
  const doc = new DOMParser().parseFromString(m.html_body, 'text/html');
  doc.querySelectorAll('script,style').forEach((n) => n.remove());
  doc.querySelectorAll('br').forEach((n) => n.replaceWith('\n'));
  doc.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,table').forEach((n) => n.append('\n'));
  return (doc.body.textContent ?? '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** A notice that came by e-mail with no web page: read it here, or save the original message. */
export function ReadEmail({
  emailId,
  r2Key,
  title,
  lang,
}: {
  emailId: string | null;
  r2Key: string | null;
  title: string;
  lang: string | null;
}) {
  const [open, setOpen] = useState(false);
  // null = idle, '' = saving, text = why it failed
  const [saving, setSaving] = useState<string | null>(null);
  const mail = useInboundEmail(emailId, open);
  const save = async () => {
    if (!r2Key) return;
    setSaving('');
    try {
      const name = (title || 'e-mail').slice(0, 80).replace(/[\\/:*?"<>|]+/g, ' ').trim();
      await downloadArchived(r2Key, `${name || 'e-mail'}.eml`);
      setSaving(null);
    } catch (e) {
      setSaving(errorMessage(e));
    }
  };
  return (
    <div className="scr-mail">
      <div className="scr-mail-actions">
        {emailId ? (
          <Button size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Close the e-mail' : 'Read the e-mail'}
          </Button>
        ) : null}
        {r2Key ? (
          <Button size="sm" variant="quiet" busy={saving === ''} onClick={() => void save()}>
            Save the original e-mail
          </Button>
        ) : null}
      </div>
      {saving ? <Notice tone="error">Not saved: {saving}</Notice> : null}
      {open ? (
        mail.isPending ? (
          <Loading label="Opening the e-mail" />
        ) : mail.isError ? (
          <Notice tone="error">The e-mail could not be read: {errorMessage(mail.error)}</Notice>
        ) : mail.data ? (
          <div className="scr-mail-body" lang={lang ?? undefined}>
            {emailText(mail.data) || 'This e-mail has no text.'}
          </div>
        ) : (
          <Notice tone="error">The e-mail is no longer in the mailbox.</Notice>
        )
      ) : null}
    </div>
  );
}
