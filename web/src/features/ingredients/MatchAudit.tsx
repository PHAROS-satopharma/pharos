// The weekly matching audit under an ingredient's name on the Ingredients page (match_audit, migration 0075).
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';
import { formatCairoDate } from '../../lib/format';
import { auditLine, flaggedLine, type MatchAuditRow } from './matchAudit';

export function MatchAudit({ ingredientId, active }: { ingredientId: string; active: boolean }) {
  const q = useQuery({
    queryKey: ['match-audit', ingredientId],
    enabled: active,
    staleTime: 60_000,
    queryFn: async () =>
      (
        unwrap<MatchAuditRow[] | null>(
          await supabase
            .from('match_audit')
            .select('checked_at,notices_named,unlinked_found,linked_now,left_over,flagged_names,unchecked_names')
            .eq('ingredient_id', ingredientId)
            .order('checked_at', { ascending: false })
            .limit(1),
        ) ?? []
      )[0] ?? null,
  });
  if (!active || !q.data) return null;
  const flagged = flaggedLine(q.data);
  return (
    <span className="readiness-notes">
      {auditLine(q.data, formatCairoDate(q.data.checked_at))}
      {flagged ? <strong> · {flagged}</strong> : null}
    </span>
  );
}
