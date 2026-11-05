import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';
import { personNames } from '../../lib/people';
import { ISSUE_COLUMNS } from '../issues/queries';
import type {
  IssueRow,
  SignalEventRow,
  SignalOutcome,
  SignalPriority,
  SignalRow,
  SignalStage,
  SignalStep,
} from '../../lib/types';

export const SIGNAL_COLUMNS =
  'id,ref,title,stage,priority,outcome,ingredient_id,ingredient,owner_id,owner,opened_at,closed_at,updated_at,' +
  'validation_due,assessment_due,action_due,next_due,overdue,notices';

export type SignalView = 'open' | 'closed' | 'all';

export function useSignals(view: SignalView) {
  return useQuery({
    queryKey: ['signals', view],
    queryFn: async () => {
      let q = supabase.from('v_signal_table').select(SIGNAL_COLUMNS);
      if (view === 'open') q = q.neq('stage', 'closed');
      if (view === 'closed') q = q.eq('stage', 'closed');
      // Open signals by the day the current stage is due, so the most urgent leads; closed ones newest first.
      q =
        view === 'closed'
          ? q.order('closed_at', { ascending: false, nullsFirst: false })
          : q.order('next_due', { ascending: true, nullsFirst: false }).order('opened_at', { ascending: false });
      return unwrap<SignalRow[] | null>(await q.order('id', { ascending: true })) ?? [];
    },
  });
}

export function useSignal(id: string) {
  return useQuery({
    queryKey: ['signal', id],
    queryFn: async () =>
      unwrap<SignalRow | null>(await supabase.from('v_signal_table').select(SIGNAL_COLUMNS).eq('id', id).maybeSingle()),
  });
}

/** The notices behind a signal, as rows of the notifications list. */
export function useSignalNotices(id: string) {
  return useQuery({
    queryKey: ['signal-notices', id],
    queryFn: async () => {
      const links =
        unwrap<{ issue_id: string }[] | null>(await supabase.from('signal_issue').select('issue_id').eq('signal_id', id)) ??
        [];
      if (links.length === 0) return [];
      return (
        unwrap<IssueRow[] | null>(
          await supabase
            .from('v_issue_table')
            .select(ISSUE_COLUMNS)
            .in(
              'id',
              links.map((l) => l.issue_id),
            )
            .order('first_date', { ascending: true, nullsFirst: false }),
        ) ?? []
      );
    },
  });
}

export function useSignalEvents(id: string) {
  return useQuery({
    queryKey: ['signal-events', id],
    queryFn: async () => {
      // Names come from person_directory: the person table shows a non-admin only their own row.
      const raw =
        unwrap<(Omit<SignalEventRow, 'person' | 'owner'> & { person_id: string; owner_id: string | null })[] | null>(
          await supabase
            .from('signal_event')
            .select('id,step,from_stage,to_stage,priority,outcome,due,comment,created_at,person_id,owner_id,issue_id')
            .eq('signal_id', id)
            .order('created_at', { ascending: true })
            .order('id', { ascending: true }),
        ) ?? [];
      const names = await personNames(raw.flatMap((r) => [r.person_id, r.owner_id]));
      return raw.map(({ person_id, owner_id, ...r }): SignalEventRow => {
        const who = names.get(person_id);
        const owner = owner_id ? names.get(owner_id) : undefined;
        return { ...r, person: who ? { full_name: who } : null, owner: owner ? { full_name: owner } : null };
      });
    },
  });
}

/** The signal a notice belongs to, if any. */
export function useIssueSignal(issueId: string) {
  return useQuery({
    queryKey: ['issue-signal', issueId],
    queryFn: async () => {
      const link = unwrap<{ signal_id: string } | null>(
        await supabase.from('signal_issue').select('signal_id').eq('issue_id', issueId).maybeSingle(),
      );
      if (!link) return null;
      return unwrap<SignalRow | null>(
        await supabase.from('v_signal_table').select(SIGNAL_COLUMNS).eq('id', link.signal_id).maybeSingle(),
      );
    },
  });
}

/** Active reviewers and administrators, who may own a signal. */
export function useOwners() {
  return useQuery({
    queryKey: ['signal-owners'],
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap<{ id: string; full_name: string }[] | null>(
        await supabase
          .from('person_directory')
          .select('id,full_name')
          .eq('active', true)
          .in('role', ['admin', 'reviewer'])
          .order('full_name'),
      ) ?? [],
  });
}

/** The database refused a step: the signal moved on since this page read it (SQLSTATE PH409). */
export class StaleSignalError extends Error {
  constructor() {
    super('Someone else moved this signal a moment ago. It has been reloaded — please look again.');
    this.name = 'StaleSignalError';
  }
}

function isStale(error: { code?: string; message?: string } | null): boolean {
  if (!error) return false;
  return error.code === 'PH409' || (error.message ?? '').startsWith('STALE_SIGNAL');
}

function useRefreshSignal() {
  const qc = useQueryClient();
  return (signalId: string | null, issueId?: string) =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['signals'] }),
      signalId ? qc.invalidateQueries({ queryKey: ['signal', signalId] }) : null,
      signalId ? qc.invalidateQueries({ queryKey: ['signal-events', signalId] }) : null,
      signalId ? qc.invalidateQueries({ queryKey: ['signal-notices', signalId] }) : null,
      issueId ? qc.invalidateQueries({ queryKey: ['issue-signal', issueId] }) : null,
    ]);
}

export interface StepInput {
  step: SignalStep;
  fromStage: SignalStage;
  comment?: string;
  priority?: SignalPriority | null;
  outcome?: SignalOutcome | null;
  owner?: string | null;
  due?: string | null;
}

export function useTakeStep(signalId: string) {
  const refresh = useRefreshSignal();
  return useMutation({
    mutationFn: async (s: StepInput) => {
      const res = await supabase.rpc('signal_take_step', {
        p_signal: signalId,
        p_step: s.step,
        p_from_stage: s.fromStage,
        p_comment: s.comment?.trim() || null,
        p_priority: s.priority ?? null,
        p_outcome: s.outcome ?? null,
        p_owner: s.owner ?? null,
        p_due: s.due || null,
      });
      if (isStale(res.error)) throw new StaleSignalError();
      return unwrap<SignalStage>(res);
    },
    // A stale step also reloads, so the page shows the signal as it is now.
    onSettled: () => refresh(signalId),
  });
}

export function useOpenSignal(issueId: string) {
  const refresh = useRefreshSignal();
  return useMutation({
    mutationFn: async (v: { title: string; ingredient: string | null; comment: string }) =>
      unwrap<string>(
        await supabase.rpc('open_signal', {
          p_issue: issueId,
          p_title: v.title,
          p_ingredient: v.ingredient,
          p_comment: v.comment.trim() || null,
        }),
      ),
    onSuccess: (id) => refresh(id, issueId),
  });
}

export function useLinkToSignal(issueId: string) {
  const refresh = useRefreshSignal();
  return useMutation({
    mutationFn: async (v: { signalId: string; comment: string }) => {
      unwrap<null>(
        await supabase.rpc('link_signal_issue', {
          p_signal: v.signalId,
          p_issue: issueId,
          p_comment: v.comment.trim() || null,
        }),
      );
      return v.signalId;
    },
    onSuccess: (id) => refresh(id, issueId),
  });
}
