import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { errorMessage, invoke, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/States';
import { CASES_KEY } from './CasesPage';

/**
 * On a paper that looks like a case report: its case when one is open, else (for a reviewer or an administrator)
 * a button that opens one. PHAROS then fetches the paper from PubMed and fills in the form; day zero is the day
 * PHAROS found the paper.
 */
export function OpenCase({ documentId }: { documentId: string }) {
  const { canReview } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const existing = useQuery({
    queryKey: [...CASES_KEY, 'paper', documentId],
    queryFn: async () =>
      unwrap<{ id: string; ref: string }[]>(
        await supabase.from('safety_case').select('id, ref').eq('document_id', documentId).limit(1),
      )[0] ?? null,
  });
  const open = useMutation({
    mutationFn: () => invoke<{ case_id: string }>('case-intake', { action: 'paper', document_id: documentId }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: CASES_KEY });
      navigate(`/cases/${r.case_id}`);
    },
  });

  if (existing.data) {
    return (
      <p className="scr-paper-links">
        <Link to={`/cases/${existing.data.id}`}>Case {existing.data.ref}</Link>
      </p>
    );
  }
  if (!canReview || existing.isPending) return null;
  return (
    <div className="scr-open-case">
      <Button size="sm" busy={open.isPending} onClick={() => open.mutate()}>
        Open a case
      </Button>
      {open.isError ? <Notice tone="error">{errorMessage(open.error)}</Notice> : null}
    </div>
  );
}
