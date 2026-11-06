// Electronic sign-off on the Reports page: pure helpers, no I/O. The database decides (sign_record,
// record_fingerprint: 0030, 0047); these only say it on screen.

import type { PersonRole } from '../../lib/types';

/** What can be signed today. A pack (PSUR or inspection) is signed once packs are made. */
export type SignKind = 'weekly_report' | 'pack';

export type Meaning = 'reviewed' | 'approved';

/** A row of sign_off as the page reads it. */
export interface Signature {
  id: string;
  record_sha256: string;
  meaning: Meaning;
  signed_name: string;
  signed_role: PersonRole;
  comment: string | null;
  signed_at: string;
}

/** The two meanings, in the words of 0030: the label in the list, the statement the signer agrees to. */
export const MEANING: Record<Meaning, { label: string; statement: string }> = {
  reviewed: { label: 'Reviewed', statement: 'I have reviewed this report.' },
  approved: { label: 'Approved', statement: 'I approve this report.' },
};

/** "9f86d081…b0f00a08": the first and last eight characters of a SHA-256, enough to compare by eye. */
export function shortHash(hex: string | null | undefined): string {
  const h = (hex ?? '').trim().toLowerCase();
  if (!h) return '—';
  return h.length <= 20 ? h : `${h.slice(0, 8)}…${h.slice(-8)}`;
}

export type SignatureState = 'matches' | 'changed' | 'unknown';

/** Is the record still what was signed? `fingerprint` is record_fingerprint() now; null while unreadable. */
export function signatureState(signedSha: string, fingerprint: string | null | undefined): SignatureState {
  if (fingerprint == null) return 'unknown';
  return signedSha === fingerprint ? 'matches' : 'changed';
}

export const STATE_LABEL: Record<SignatureState, string> = {
  matches: 'Fingerprint matches',
  changed: 'File changed since signing',
  unknown: 'Fingerprint not checked',
};

/** The meaning offered first: an administrator approves, a reviewer reviews. Either may choose the other. */
export function defaultMeaning(role: PersonRole | null): Meaning {
  return role === 'admin' ? 'approved' : 'reviewed';
}
