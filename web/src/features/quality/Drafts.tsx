import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { invoke, unwrap } from '../../lib/api';
import { formatDateTime } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/States';
import { Fact, QUALITY_KEY } from './parts';
import { type DraftKind, type QualityDraft, draftOf, draftWaiting } from './quality';

const DRAFTS_KEY = [...QUALITY_KEY, 'drafts'] as const;

/**
 * The latest draft of every record (quality_drafts(), 0109). Read again every 5 seconds while one is being
 * drafted. Before 0109 is applied the read fails: the tab then offers no draft, never an error.
 */
export function useDrafts() {
  return useQuery({
    queryKey: DRAFTS_KEY,
    retry: false,
    queryFn: async () => unwrap<QualityDraft[] | null>(await supabase.rpc('quality_drafts')) ?? [],
    refetchInterval: (q) => ((q.state.data ?? []).some(draftWaiting) ? 5000 : false),
  });
}

export interface DraftUse {
  rootCause: string;
  corrective: string;
  preventive: string;
}

/**
 * Ask the reader for a draft of the root cause and the CAPA of one deviation or audit observation, and show it.
 * The draft is only text: "Use as the root cause" and "Use in a new CAPA" open the usual forms filled in with it,
 * and nothing is recorded until she saves the form.
 */
export function DraftPanel({
  kind,
  recordId,
  canAsk,
  onUseRootCause,
  onUseCapa,
}: {
  kind: DraftKind;
  recordId: string;
  canAsk: boolean;
  onUseRootCause: (text: string) => void;
  onUseCapa: (use: DraftUse) => void;
}) {
  const qc = useQueryClient();
  const drafts = useDrafts();
  const ask = useMutation({
    mutationFn: () => invoke<{ draft_id: string; dispatched: boolean }>('quality-draft', { kind, id: recordId }),
    onSettled: () => qc.invalidateQueries({ queryKey: DRAFTS_KEY }),
  });
  if (drafts.isError) return null;
  const d = draftOf(drafts.data ?? [], kind, recordId);
  const waiting = d ? draftWaiting(d) : false;
  const askButton = canAsk ? (
    <Button variant={d ? 'quiet' : 'primary'} busy={ask.isPending} disabled={waiting} onClick={() => ask.mutate()}>
      {d ? 'Draft again' : 'Draft the root cause and CAPA'}
    </Button>
  ) : null;

  return (
    <div className="q-draft-area">
      {d?.status === 'ready' ? (
        <div className="q-draft">
          <p className="q-draft-label">Draft, not recorded</p>
          <p className="small muted">
            Written by the reader (Claude) from what is recorded here, {formatDateTime(d.finished_at)}
            {d.asked_by ? `, asked for by ${d.asked_by}` : ''}. Check every word: nothing changes until you save it in
            a form.
          </p>
          <dl className="q-facts">
            <Fact label="Root cause" wide>
              <span className="q-pre">{d.root_cause}</span>
            </Fact>
            {d.corrective_action ? (
              <Fact label="Corrective action" wide>
                <span className="q-pre">{d.corrective_action}</span>
              </Fact>
            ) : null}
            {d.preventive_action ? (
              <Fact label="Preventive action" wide>
                <span className="q-pre">{d.preventive_action}</span>
              </Fact>
            ) : null}
            {d.to_check ? (
              <Fact label="Check before you use it" wide>
                <span className="q-pre">{d.to_check}</span>
              </Fact>
            ) : null}
          </dl>
          {canAsk ? (
            <div className="button-row">
              <Button onClick={() => onUseRootCause(d.root_cause ?? '')}>Use as the root cause</Button>
              {d.corrective_action || d.preventive_action ? (
                <Button
                  onClick={() =>
                    onUseCapa({
                      rootCause: d.root_cause ?? '',
                      corrective: d.corrective_action ?? '',
                      preventive: d.preventive_action ?? '',
                    })
                  }
                >
                  Use in a new CAPA
                </Button>
              ) : null}
              {askButton}
            </div>
          ) : null}
        </div>
      ) : (
        <>
          {waiting ? (
            <Notice tone="info">Drafting the root cause and CAPA… this usually takes under a minute.</Notice>
          ) : null}
          {d?.status === 'failed' ? <Notice tone="error">The draft could not be made: {d.error}</Notice> : null}
          {canAsk ? <div className="button-row">{askButton}</div> : null}
        </>
      )}
      {ask.error ? <Notice tone="error">Not asked: {(ask.error as Error).message}</Notice> : null}
    </div>
  );
}
