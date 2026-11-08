import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { errorMessage, unwrap } from '../../lib/api';
import { formatDate } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { filesToUpload, uploadFolder } from './meddraUpload';

/**
 * MedDRA (migration 0102), from the company's own MSSO subscription. An administrator uploads the release; PHAROS
 * loads it (the "PHAROS dictionaries" workflow, within two hours); then each reaction's LLT is searched here and
 * chosen with "Use", which writes the code and the loaded version into the form.
 */

export interface MeddraDictionary {
  version: string;
  release: string;
  descriptors: number;
  terms: number;
  loaded_at: string;
}

interface MeddraUpload {
  folder: string;
  asked_at: string;
  status: 'waiting' | 'loading' | 'loaded' | 'failed' | 'replaced';
  message: string | null;
  done_at: string | null;
}

interface MeddraHit {
  llt_code: string;
  llt_name: string;
  current: boolean;
  pt_code: string;
  pt_name: string;
  hlt_name: string | null;
  hlgt_name?: string | null;
  soc_name: string | null;
  chosen_before?: number;
  release?: string | null;
}

const DICTIONARY_KEY = ['meddra-dictionary'];
const UPLOADS_KEY = ['meddra-uploads'];

export function useMeddraDictionary() {
  return useQuery({
    queryKey: DICTIONARY_KEY,
    queryFn: async () =>
      unwrap<MeddraDictionary | null>(
        await supabase
          .from('coding_dictionary')
          .select('version, release, descriptors, terms, loaded_at')
          .eq('name', 'meddra')
          .maybeSingle(),
      ),
    staleTime: 10 * 60_000,
  });
}

const UPLOAD_LABEL: Record<MeddraUpload['status'], string> = {
  waiting: 'Waiting to load',
  loading: 'Loading',
  loaded: 'Loaded',
  failed: 'Not loaded',
  replaced: 'Replaced by a newer upload',
};

/** The Cases screen's MedDRA panel: what is loaded, and for an administrator the upload. */
export function MeddraPanel({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const dictionary = useMeddraDictionary();
  const uploads = useQuery({
    queryKey: UPLOADS_KEY,
    queryFn: async () =>
      unwrap<MeddraUpload[]>(
        await supabase.from('meddra_upload').select('*').order('folder', { ascending: false }).limit(3),
      ),
    refetchInterval: (q) => ((q.state.data ?? []).some((u) => u.status === 'waiting' || u.status === 'loading') ? 60_000 : false),
  });
  const input = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: async (chosen: File[]) => {
      const folder = uploadFolder(new Date());
      for (const f of chosen) {
        const { error } = await supabase.storage
          .from('meddra')
          .upload(`${folder}/${f.name.replace(/[^A-Za-z0-9._-]+/g, '_')}`, f, { upsert: false, contentType: 'application/octet-stream' });
        if (error) throw new Error(`${f.name} was not stored: ${error.message}`);
      }
      unwrap(await supabase.rpc('ask_meddra_load', { p_folder: folder }));
    },
    onSuccess: () => {
      if (input.current) input.current.value = '';
      qc.invalidateQueries({ queryKey: UPLOADS_KEY });
    },
  });

  const latest = uploads.data?.[0];
  const d = dictionary.data;
  useEffect(() => {
    if (latest?.status === 'loaded') qc.invalidateQueries({ queryKey: DICTIONARY_KEY });
  }, [latest?.status, latest?.folder, qc]);

  return (
    <div className="meddra-panel">
      {d ? (
        <p>
          <Tag tone="success">Loaded</Tag> {d.version}: {d.terms.toLocaleString('en-GB')} Lowest Level Terms under{' '}
          {d.descriptors.toLocaleString('en-GB')} Preferred Terms, loaded {formatDate(d.loaded_at)}. Each reaction is
          coded from it on the case page.
        </p>
      ) : (
        <p>
          <Tag tone="warning">Not loaded</Tag> MedDRA is not loaded yet. Until it is, send a case on the CIOMS I form;
          the E2B file needs a MedDRA code on every reaction.
        </p>
      )}
      {latest && latest.status !== 'loaded' ? (
        <Notice tone={latest.status === 'failed' ? 'error' : 'info'}>
          Upload of {formatDate(latest.asked_at)}: {UPLOAD_LABEL[latest.status]}.
          {latest.status === 'waiting' || latest.status === 'loading' ? ' PHAROS loads it within two hours.' : null}
          {latest.message ? ` ${latest.message}` : null}
        </Notice>
      ) : null}
      {isAdmin ? (
        <div className="meddra-upload">
          <input
            ref={input}
            type="file"
            multiple
            accept=".zip,.asc"
            aria-label="The MedDRA release files"
            onChange={() => setProblem(null)}
          />
          <Button
            busy={upload.isPending}
            onClick={() => {
              const picked = filesToUpload(Array.from(input.current?.files ?? []));
              setProblem(picked.problem);
              if (!picked.problem) upload.mutate(picked.files);
            }}
          >
            Upload {d ? 'a new release' : 'MedDRA'}
          </Button>
          <span className="code-sub">
            The zip as MSSO sends it (MedDRA_xx_x_English.zip), or the .asc files of its MedAscii folder. The files stay
            private to PHAROS administrators.
          </span>
        </div>
      ) : null}
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      {upload.isError ? <Notice tone="error">{errorMessage(upload.error)}</Notice> : null}
      {upload.isSuccess ? <Notice tone="ok">Uploaded. PHAROS loads it within two hours.</Notice> : null}
    </div>
  );
}

function useDebounced(value: string, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function path(h: MeddraHit): string {
  return [h.pt_name !== h.llt_name ? `PT ${h.pt_name}` : null, h.soc_name].filter(Boolean).join(' · ');
}

/** One reaction's MedDRA code: the LLT chosen (named from the loaded MedDRA), and a search to choose it. */
export function MeddraCoding({
  code,
  version,
  words,
  editable,
  onChoose,
}: {
  code: string | null | undefined;
  version: string | null | undefined;
  words: string;
  editable: boolean;
  onChoose: (code: string | null, version: string | null) => void;
}) {
  const dictionary = useMeddraDictionary();
  const d = dictionary.data;
  const typed = (code ?? '').trim();
  const named = useQuery({
    queryKey: ['meddra-lookup', typed],
    queryFn: async () => unwrap<MeddraHit[]>(await supabase.rpc('meddra_lookup', { p_code: typed }))[0] ?? null,
    enabled: !!d && /^\d{8}$/.test(typed),
    staleTime: 10 * 60_000,
  });
  const [searching, setSearching] = useState(false);
  const [text, setText] = useState('');
  const q = useDebounced((searching ? text : words).trim());
  const hits = useQuery({
    queryKey: ['meddra-search', q],
    queryFn: async () => unwrap<MeddraHit[]>(await supabase.rpc('meddra_search', { p_text: q, p_limit: 8 })),
    enabled: !!d && editable && q.length >= 3 && (searching || !typed),
    staleTime: 5 * 60_000,
  });
  if (!d) return null;

  const h = named.data;
  const warn =
    typed && /^\d{8}$/.test(typed) && named.isSuccess && !h
      ? `This code is not in ${d.version}.`
      : h && !h.current
        ? 'This LLT is no longer current in MedDRA: choose a current one.'
        : h && version && version.trim() !== d.release
          ? `The version says ${version.trim()}; the loaded MedDRA is ${d.release}.`
          : null;

  return (
    <div className="code-box">
      <div className="code-head">
        <span className="code-label">MedDRA code</span>
        {h ? (
          <span className="code-chosen">
            <Tag tone="blue">LLT</Tag> {h.llt_name} <span className="code-sub">{h.llt_code}</span>
            <span className="code-sub">{path(h)}</span>
          </span>
        ) : (
          <span className="code-sub">{typed ? typed : 'Not coded yet'}</span>
        )}
        {editable && typed ? (
          <Button size="sm" variant="quiet" onClick={() => onChoose(null, null)}>
            Remove the code
          </Button>
        ) : null}
      </div>
      {warn ? <Notice tone="error">{warn}</Notice> : null}
      {editable && searching ? (
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Search MedDRA: words, or an 8-digit LLT code"
          aria-label="Search MedDRA"
        />
      ) : null}
      {editable && hits.data && (searching || !typed) ? (
        hits.data.length ? (
          <ul className="code-list">
            {hits.data.map((x) => (
              <li key={x.llt_code}>
                <span className="code-name">
                  {x.chosen_before ? <Tag tone="success">Chosen before</Tag> : null}{' '}
                  {x.llt_name} <span className="code-sub">{x.llt_code}</span>
                  {!x.current ? <span className="code-sub"> not current</span> : null}
                  <span className="code-sub">{path(x)}</span>
                </span>
                <Button
                  size="sm"
                  onClick={() => {
                    onChoose(x.llt_code, d.release);
                    setSearching(false);
                  }}
                >
                  Use
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="code-sub">No MedDRA term is close to these words.</p>
        )
      ) : null}
      {editable && !searching ? (
        <Button size="sm" variant="quiet" onClick={() => setSearching(true)}>
          Search MedDRA
        </Button>
      ) : null}
    </div>
  );
}
