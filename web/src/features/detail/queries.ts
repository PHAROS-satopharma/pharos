import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { fetchAllPages, unwrap } from '../../lib/api';
import { personNames } from '../../lib/people';
import { ISSUE_COLUMNS } from '../issues/queries';
import type {
  AttachmentRow,
  DocType,
  DocumentTextRow,
  IssueRow,
  LinkKind,
  LinkMethod,
  MatchRow,
  NotificationRow,
  ReviewEventRow,
  SourceChannel,
} from '../../lib/types';

export interface CopyDocument {
  id: string;
  url: string;
  title_orig: string;
  lang: string | null;
  doc_type: DocType;
  published_date: string | null;
  first_seen_at: string;
  r2_key: string | null;
  mime: string | null;
  is_backfill: boolean;
  source: {
    id: string;
    channel: SourceChannel;
    regulator: { name: string; country_name: string; country_code: string } | null;
  } | null;
}

export interface IssueCopy {
  link: LinkKind;
  method: LinkMethod;
  score: number | null;
  linked_at: string;
  linked_by_person: { full_name: string } | null;
  document: CopyDocument | null;
}

export interface SpcDiffSection {
  section: string;
  before: string;
  after: string;
}

export interface SpcChangeRow {
  id: string;
  sections: string[];
  diff: SpcDiffSection[];
  created_at: string;
  spc_product: { product_name: string; mah: string | null; country_code: string; url: string | null } | null;
  from_snap: { doc_date: string | null; fetched_at: string } | null;
  to_snap: { doc_date: string | null; fetched_at: string } | null;
}

export function useIssue(id: string) {
  return useQuery({
    queryKey: ['issue', id],
    queryFn: async () =>
      unwrap<IssueRow | null>(await supabase.from('v_issue_table').select(ISSUE_COLUMNS).eq('id', id).maybeSingle()),
  });
}

export function useCopies(id: string) {
  return useQuery({
    queryKey: ['issue-copies', id],
    queryFn: async () => {
      // Who linked a copy: the name comes from person_directory, because the person table shows a
      // non-admin only their own row.
      const raw =
        unwrap<(Omit<IssueCopy, 'linked_by_person'> & { linked_by: string | null })[] | null>(
          await supabase
            .from('issue_document')
            .select(
              'link,method,score,linked_at,linked_by,' +
                'document:document_id(id,url,title_orig,lang,doc_type,published_date,first_seen_at,r2_key,mime,is_backfill,' +
                'source:source_id(id,channel,regulator:regulator_id(name,country_name,country_code)))',
            )
            .eq('issue_id', id),
        ) ?? [];
      const names = await personNames(raw.map((r) => r.linked_by));
      const rows = raw.map(({ linked_by, ...r }): IssueCopy => {
        const name = linked_by ? names.get(linked_by) : undefined;
        return { ...r, linked_by_person: name ? { full_name: name } : null };
      });
      return rows
        .filter((r) => r.document !== null)
        .sort((a, b) => {
          if (a.link !== b.link) return a.link === 'anchor' ? -1 : 1;
          return (a.document?.published_date ?? '').localeCompare(b.document?.published_date ?? '');
        });
    },
  });
}

export interface EvidenceData {
  matches: MatchRow[];
  texts: DocumentTextRow[];
  attachments: AttachmentRow[];
}

export function useEvidence(issueId: string, docIds: string[]) {
  return useQuery({
    queryKey: ['issue-evidence', issueId, docIds],
    enabled: docIds.length > 0,
    queryFn: async (): Promise<EvidenceData> => {
      // Every page: a merged issue with many long copies has more than the API's 1,000 rows of matches.
      const [matches, texts, attachments] = await Promise.all([
        fetchAllPages<MatchRow>(async (from, to) =>
          await supabase
            .from('match')
            .select(
              'id,document_id,attachment_id,field,start_offset,end_offset,matched_text,snippet,confidence,' +
                'ingredient:ingredient_id(inn_en),drug_class:class_id(name_en)',
            )
            .in('document_id', docIds)
            .order('start_offset', { ascending: true })
            .order('id', { ascending: true })
            .range(from, to),
        ),
        fetchAllPages<DocumentTextRow>(async (from, to) =>
          await supabase
            .from('document_text')
            .select('document_id,attachment_id,text')
            .in('document_id', docIds)
            .order('document_id', { ascending: true })
            .order('attachment_id', { ascending: true, nullsFirst: true })
            .range(from, to),
        ),
        fetchAllPages<AttachmentRow>(async (from, to) =>
          await supabase
            .from('attachment')
            .select('id,document_id,url,filename,r2_key,mime,bytes,extraction,words')
            .in('document_id', docIds)
            .order('id', { ascending: true })
            .range(from, to),
        ),
      ]);
      return { matches, texts, attachments };
    },
  });
}

function parseDiff(raw: unknown): SpcDiffSection[] {
  if (!Array.isArray(raw)) return [];
  const out: SpcDiffSection[] = [];
  for (const item of raw) {
    if (item && typeof item === 'object') {
      const o = item as Record<string, unknown>;
      out.push({
        section: typeof o.section === 'string' ? o.section : String(o.section ?? ''),
        before: typeof o.before === 'string' ? o.before : '',
        after: typeof o.after === 'string' ? o.after : '',
      });
    }
  }
  return out;
}

export function useSpcChanges(issueId: string) {
  return useQuery({
    queryKey: ['issue-spc', issueId],
    queryFn: async () => {
      const rows =
        unwrap<(Omit<SpcChangeRow, 'diff'> & { diff: unknown })[] | null>(
          await supabase
            .from('spc_change')
            .select(
              'id,sections,diff,created_at,spc_product:spc_product_id(product_name,mah,country_code,url),' +
                'from_snap:from_snapshot(doc_date,fetched_at),to_snap:to_snapshot(doc_date,fetched_at)',
            )
            .eq('issue_id', issueId)
            .order('created_at', { ascending: false }),
        ) ?? [];
      return rows.map((r): SpcChangeRow => ({ ...r, diff: parseDiff(r.diff) }));
    },
  });
}

export function useReviews(issueId: string) {
  return useQuery({
    queryKey: ['issue-reviews', issueId],
    queryFn: async () => {
      // Reviewers' names come from person_directory: the person table shows a non-admin only their own row.
      const raw =
        unwrap<(Omit<ReviewEventRow, 'person'> & { person_id: string })[] | null>(
          await supabase
            .from('review_event')
            .select('id,from_status,to_status,comment,created_at,person_id')
            .eq('issue_id', issueId)
            .order('created_at', { ascending: true }),
        ) ?? [];
      const names = await personNames(raw.map((r) => r.person_id));
      return raw.map(({ person_id, ...r }): ReviewEventRow => {
        const name = names.get(person_id);
        return { ...r, person: name ? { full_name: name } : null };
      });
    },
  });
}

/** Messages about this notice: every person's for an admin, only your own otherwise (row-level security). */
export function useNotified(issueId: string) {
  return useQuery({
    queryKey: ['issue-notified', issueId],
    queryFn: async () =>
      unwrap<NotificationRow[] | null>(
        await supabase
          .from('notification')
          .select('id,kind,dry_run,sent_at,error,summary,person:person_id(full_name)')
          .eq('issue_id', issueId)
          .order('sent_at', { ascending: true }),
      ) ?? [],
  });
}
