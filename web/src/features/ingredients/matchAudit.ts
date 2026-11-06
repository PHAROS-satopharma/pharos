// The weekly matching audit's latest row for one ingredient (match_audit, migration 0075; collectors/match_audit.py).
export interface MatchAuditRow {
  checked_at: string;
  notices_named: number;
  unlinked_found: number;
  linked_now: number;
  left_over: { document_id: string; title: string | null }[];
  flagged_names: { term_id: string; term: string; why: string }[];
  unchecked_names: number;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One line: how many notices name it, and whether any of them was not linked. */
export function auditLine(r: MatchAuditRow, day: string): string {
  const named = plural(r.notices_named, 'notice names it', 'notices name it');
  if (r.unlinked_found === 0) return `Audit ${day}: ${named}, all linked`;
  const left = r.unlinked_found - r.linked_now;
  return (
    `Audit ${day}: ${named}; ${plural(r.unlinked_found, 'was', 'were')} not linked, ${r.linked_now} linked now` +
    (left > 0 ? `, ${left} still to look at` : '')
  );
}

/** The names RxNorm gives only to another substance, for an admin to remove. */
export function flaggedLine(r: MatchAuditRow): string | null {
  const parts = r.flagged_names.map((f) => `“${f.term}” (${f.why})`);
  if (r.unchecked_names > 0) parts.push(`${plural(r.unchecked_names, 'name', 'names')} could not be checked`);
  return parts.length ? `Belongs to another substance: ${parts.join(', ')}` : null;
}
