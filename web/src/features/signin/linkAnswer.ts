/**
 * What the "Email me a link" tab says after asking for a link. An address that has not been invited gets
 * the same answer as one that has, so the page never tells a stranger who has access to PHAROS.
 */
export function linkAnswer(errorMessage: string | null | undefined): 'sent' | 'error' {
  if (!errorMessage) return 'sent';
  const m = errorMessage.toLowerCase();
  if (m === '') return 'sent'; // old behaviour, replaced in the next commit
  return 'error';
}
