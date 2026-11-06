import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatCairoDate } from '../../lib/format';
import { languageName } from '../../lib/labels';
import { pdfText } from '../../lib/pdfText';
import { personNames } from '../../lib/people';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { ErrorNote, Loading, Notice } from '../../ui/States';
import { sectionOrder, splitSections } from './labelText';
import type { OurLabelRow } from './types';

type Current = OurLabelRow & { uploaded_by_name: string };

/** The current version(s) of our label for the ingredient, with who uploaded each (names, never ids). */
function useOurLabel(ingredientId: string) {
  return useQuery({
    queryKey: ['our-label', ingredientId],
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<Current[]> => {
      const rows =
        unwrap<OurLabelRow[] | null>(
          await supabase
            .from('our_label')
            .select('id,ingredient_id,product_name,version,lang,sections,file_name,uploaded_by,uploaded_at,superseded_at')
            .eq('ingredient_id', ingredientId)
            .is('superseded_at', null)
            .order('uploaded_at', { ascending: false }),
        ) ?? [];
      const names = await personNames(rows.map((r) => r.uploaded_by));
      return rows.map((r) => ({ ...r, uploaded_by_name: names.get(r.uploaded_by) ?? 'Someone' }));
    },
  });
}

/**
 * Our label, above the label changes: the current version, and for a reviewer or administrator the upload of a
 * new one (PDF read on this computer, a text file, or pasted text; only the numbered sections are saved).
 * The collector compares every change of the last year with the new version on its next run.
 */
export function OurLabel({ ingredientId }: { ingredientId: string }) {
  const { canReview } = useAuth();
  const q = useOurLabel(ingredientId);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const current = q.data ?? [];

  return (
    <div className="lab-ours">
      <div className="lab-ours-head">
        <h3 className="lab-ours-title">Our label</h3>
        {canReview && !editing && !q.isPending ? (
          <Button
            size="sm"
            onClick={() => {
              setEditing(true);
              setSaved(false);
            }}
          >
            {current.length ? 'Replace' : 'Upload our label'}
          </Button>
        ) : null}
      </div>
      {q.isPending ? (
        <Loading label="Reading our label" />
      ) : q.isError ? (
        <ErrorNote error={q.error} onRetry={() => void q.refetch()} />
      ) : current.length === 0 ? (
        <p className="lab-gap-quiet">
          No label of ours uploaded yet.{' '}
          {canReview
            ? 'Upload the approved leaflet or SmPC of our product, as a PDF or as text; each label change is then compared with it.'
            : 'A reviewer or an administrator uploads it; each label change is then compared with it.'}
        </p>
      ) : (
        <ul className="lab-ours-list">
          {current.map((l) => (
            <li key={l.id} className="lab-ours-item">
              <strong dir="auto">{l.product_name}</strong>
              <span dir="auto">{l.version}</span>
              <span className="lab-ours-meta">
                {languageName(l.lang)} · {Object.keys(l.sections).length} sections · uploaded {formatCairoDate(l.uploaded_at)} by{' '}
                {l.uploaded_by_name}
                {l.file_name ? ` · ${l.file_name}` : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <UploadForm
          ingredientId={ingredientId}
          current={current[0]}
          onSaved={() => {
            setEditing(false);
            setSaved(true);
          }}
          onCancel={() => setEditing(false)}
        />
      ) : null}
      {saved ? <Notice tone="ok">Saved. Compared with the label changes within 4 hours, on the next collection run.</Notice> : null}
    </div>
  );
}

function UploadForm({
  ingredientId,
  current,
  onSaved,
  onCancel,
}: {
  ingredientId: string;
  current: Current | undefined;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const qc = useQueryClient();
  const [product, setProduct] = useState(current?.product_name ?? '');
  const [version, setVersion] = useState('');
  const [lang, setLang] = useState(current?.lang ?? 'en');
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);

  const sections = useMemo(() => (text.trim() ? splitSections(text) : {}), [text]);
  const keys = Object.keys(sections).sort(sectionOrder);
  const safety = keys.filter((k) => k.startsWith('4.'));
  const ready = product.trim().length > 0 && version.trim().length > 0 && safety.length > 0;

  const save = useMutation({
    mutationFn: async () =>
      unwrap<string>(
        await supabase.rpc('save_our_label', {
          p_ingredient: ingredientId,
          p_product: product.trim(),
          p_version: version.trim(),
          p_lang: lang.trim(),
          p_sections: sections,
          p_file: fileName,
        }),
      ),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['our-label', ingredientId] });
      // The changes now name the new version, with no comparison until the collector's next run.
      await qc.invalidateQueries({ queryKey: ['label-changes'] });
      onSaved();
    },
  });

  async function readFile(file: File) {
    setReading(true);
    setReadError(null);
    try {
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      const t = isPdf ? await pdfText(file) : await file.text();
      setText(t);
      setFileName(file.name);
      if (t.replace(/\s/g, '').length < 200) {
        setReadError('Almost no text was found: the PDF may be a scan. Paste the label text below instead.');
      }
    } catch (e) {
      setReadError(errorMessage(e));
    } finally {
      setReading(false);
    }
  }

  return (
    <form
      className="lab-ours-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) save.mutate();
      }}
    >
      <div className="form-grid">
        <Field label="Product" hint="Our product name and strength, e.g. Lornox 8 mg tablets.">
          <Input value={product} onChange={(e) => setProduct(e.target.value)} required maxLength={200} />
        </Field>
        <Field label="Version" hint="Which approval this is, e.g. Leaflet approved by EDA, March 2024.">
          <Input value={version} onChange={(e) => setVersion(e.target.value)} required maxLength={200} />
        </Field>
        <Field label="Language" hint="The language of the text, as a code: en, ar, fr.">
          <Input value={lang} onChange={(e) => setLang(e.target.value)} required pattern="[a-z]{2,3}(-[A-Za-z0-9]{2,8})*" />
        </Field>
      </div>
      <Field label="The label as a PDF or text file" hint="Read on this computer; only the sections found are saved.">
        <Input
          type="file"
          accept="application/pdf,.pdf,text/plain,.txt"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void readFile(f);
          }}
        />
      </Field>
      <Field label="Or paste the text" hint="Section headings start a line with their number: 4.4 Special warnings…">
        <Textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} dir="auto" />
      </Field>
      {reading ? <Loading label="Reading the PDF" /> : null}
      {readError ? <Notice tone="error">{readError}</Notice> : null}

      {keys.length > 0 ? (
        <div className="lab-preview">
          <span className="field-label">Sections found ({keys.length})</span>
          <ul className="lab-preview-list">
            {keys.map((k) => (
              <li key={k}>
                <span className="lab-preview-num">{k}</span>
                <span className="lab-preview-text" dir="auto">
                  {sections[k].slice(0, 140)}
                  {sections[k].length > 140 ? '…' : ''}
                </span>
              </li>
            ))}
          </ul>
          {safety.length === 0 ? (
            <Notice tone="error">No safety section (4.1 to 4.9) was found. Check that each heading starts its own line.</Notice>
          ) : null}
        </div>
      ) : null}

      {save.isError ? <Notice tone="error">Not saved: {errorMessage(save.error)}</Notice> : null}
      <div className="lab-form-actions">
        <Button type="submit" variant="primary" busy={save.isPending} disabled={!ready}>
          Save this version
        </Button>
        <Button variant="quiet" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
