import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useOurLabels, type OurLabel } from './queries';
import { useIngredientList } from '../people/useIngredientList';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatCairoDate } from '../../lib/format';
import { languageName } from '../../lib/labels';
import { splitSections } from '../../lib/labelGap';
import { pdfText } from '../../lib/pdfText';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { PageHead, SectionHead } from '../../ui/Text';

function byNumber(a: string, b: string): number {
  const x = a.split('.').map(Number);
  const y = b.split('.').map(Number);
  return x[0] - y[0] || (x[1] ?? 0) - (y[1] ?? 0);
}

function AddLabel({ onSaved }: { onSaved: () => void }) {
  const ingredients = useIngredientList();
  const qc = useQueryClient();
  const [ingredient, setIngredient] = useState('');
  const [product, setProduct] = useState('');
  const [version, setVersion] = useState('');
  const [lang, setLang] = useState('en');
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);

  const sections = useMemo(() => (text.trim() ? splitSections(text) : {}), [text]);
  const keys = Object.keys(sections).sort(byNumber);
  const safety = keys.filter((k) => k.startsWith('4.'));

  const save = useMutation({
    mutationFn: async () =>
      unwrap<string>(
        await supabase.rpc('save_our_label', {
          p_ingredient: ingredient,
          p_product: product,
          p_version: version,
          p_lang: lang.trim(),
          p_sections: sections,
          p_file: fileName,
        }),
      ),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['our-labels'] });
      onSaved();
    },
  });

  async function readFile(file: File) {
    setReading(true);
    setReadError(null);
    try {
      const t = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf') ? await pdfText(file) : await file.text();
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
      className="panel our-label-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (ingredient && product.trim() && version.trim() && safety.length > 0) save.mutate();
      }}
    >
      <h2 className="panel-title">Add a label version</h2>
      <div className="form-grid">
        <Field label="Ingredient">
          <Select
            value={ingredient}
            onChange={(e) => setIngredient(e.target.value)}
            placeholder="Choose"
            options={(ingredients.data ?? []).map((i) => ({ value: i.id, label: i.inn_en }))}
            required
          />
        </Field>
        <Field label="Product" hint="Our product name and strength, e.g. Lornox 8 mg tablets.">
          <Input value={product} onChange={(e) => setProduct(e.target.value)} required />
        </Field>
        <Field label="Version" hint="Which approval this is, e.g. Leaflet approved by EDA, March 2024.">
          <Input value={version} onChange={(e) => setVersion(e.target.value)} required />
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
        <div className="our-label-preview">
          <span className="field-label">Sections found ({keys.length})</span>
          <ul className="our-label-sections">
            {keys.map((k) => (
              <li key={k}>
                <span className="mono">{k}</span>{' '}
                <span className="soft small" dir="auto">
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
      <Button
        type="submit"
        variant="primary"
        busy={save.isPending}
        disabled={!ingredient || !product.trim() || !version.trim() || safety.length === 0}
      >
        Save this version
      </Button>
    </form>
  );
}

export function OurLabelsPage() {
  const labels = useOurLabels();
  const { canReview } = useAuth();
  const [adding, setAdding] = useState(false);
  const [saved, setSaved] = useState(false);
  const current = (labels.data ?? []).filter((l) => !l.superseded_at);
  const older = (l: OurLabel) =>
    (labels.data ?? []).filter(
      (o) => o.superseded_at && o.ingredient_id === l.ingredient_id && o.product_name.toLowerCase() === l.product_name.toLowerCase(),
    ).length;

  return (
    <div className="page">
      <PageHead
        eyebrow="Watchlist"
        title="Our labels"
        lede="The text of our own product information, section by section. When an originator’s label changes, the notice shows which added sentences our label already says."
        actions={
          canReview && !adding ? (
            <Button
              variant="primary"
              onClick={() => {
                setAdding(true);
                setSaved(false);
              }}
            >
              Add a label version
            </Button>
          ) : null
        }
      />
      {adding ? (
        <AddLabel
          onSaved={() => {
            setAdding(false);
            setSaved(true);
          }}
        />
      ) : null}
      {saved ? <Notice tone="ok">Saved. The comparison on label-change notices now uses this version.</Notice> : null}

      <section className="section">
        <SectionHead index="01" title="Current versions" aside={<Link to="/ingredients">The watchlist</Link>} />
        {labels.isPending ? (
          <Loading label="Reading our labels" />
        ) : labels.isError ? (
          <ErrorNote error={labels.error} onRetry={() => void labels.refetch()} />
        ) : current.length === 0 ? (
          <Empty title="No label of ours is saved yet.">
            <p>Add the approved leaflet or SmPC of each product, as a PDF or as text. A new version keeps the older ones.</p>
          </Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <th scope="col">Ingredient</th>
                <th scope="col">Product</th>
                <th scope="col">Version</th>
                <th scope="col">Language</th>
                <th scope="col">Sections</th>
                <th scope="col">Saved</th>
              </tr>
            </thead>
            <tbody>
              {current.map((l) => (
                <tr key={l.id}>
                  <td>{l.ingredient?.inn_en ?? '—'}</td>
                  <td dir="auto">{l.product_name}</td>
                  <td dir="auto">
                    {l.version}
                    {older(l) > 0 ? <span className="cell-sub">{older(l)} older {older(l) === 1 ? 'version' : 'versions'} kept</span> : null}
                  </td>
                  <td>{languageName(l.lang)}</td>
                  <td className="mono small">{Object.keys(l.sections).sort(byNumber).join(' ')}</td>
                  <td>
                    {formatCairoDate(l.uploaded_at)}
                    <span className="cell-sub">
                      {l.uploaded_by_name ?? 'Someone'}
                      {l.file_name ? ` · ${l.file_name}` : ''}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>
    </div>
  );
}
