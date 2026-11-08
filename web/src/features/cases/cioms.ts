/**
 * The CIOMS I form of a confirmed case: the one-page suspect adverse reaction report authorities take by e-mail,
 * made in the browser from the confirmed form (safety_case.data, 0059) and printed or saved as PDF.
 *
 * It is the route while PHAROS has no MedDRA subscription: the reactions go in the reporter's words (in English,
 * with the words as written beside them), so no MedDRA code is needed. A MedDRA LLT code and version typed on the
 * case are printed beside the reaction when there. MeSH codes are PHAROS's own and never go on the form.
 *
 * Boxes follow the CIOMS I layout: I reaction information (1–13), II suspect drugs (14–21), III concomitant drugs
 * and history (22–23), IV manufacturer information (24a–25a). What the case does not hold (dechallenge,
 * rechallenge) is printed as not stated, never guessed.
 */

import { CRITERIA, OUTCOME, caseMissing, type CaseForm, type CaseStatus, type Product, type Reaction } from './caseForm';

/** Who sends the form (box 24a). */
export const MANUFACTURER = 'Sato Pharma, Egypt';

const NOT_STATED = 'Not stated';

/** Why the CIOMS I form cannot be made yet (the E2B checks without the MedDRA and ingredient-unit ones). */
export function ciomsProblems(form: CaseForm, serious: boolean | null, status: CaseStatus): string[] {
  const out = caseMissing(form).map((m) => `the case has no ${m} yet`);
  if (serious === null) out.push('seriousness is not decided');
  if (status !== 'confirmed' && status !== 'sent') out.push('the case is not confirmed');
  return out;
}

export interface CiomsInput {
  form: CaseForm;
  /** The case number (box 24b, the manufacturer's control number). */
  ref: string;
  /** Day zero: the date the company first received the report (box 24c). */
  dayZero: string;
  serious: boolean | null;
  /** A follow-up once the case was reopened with new information (box 25a). */
  followUp: boolean;
  /** The day the form is made (Cairo), 'YYYY-MM-DD'. */
  today: string;
}

/** Text made safe for HTML. */
export function esc(v: unknown): string {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function filled(v: unknown): boolean {
  return v !== null && v !== undefined && String(v).trim() !== '';
}

function text(v: unknown): string {
  return filled(v) ? String(v).trim() : '';
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

/** '2026-05-03' → '03 MAY 2026', '2026-05' → 'MAY 2026', '2026' → '2026'; anything else as written. */
export function ciomsDate(v: string | null | undefined): string {
  const t = text(v);
  const m = /^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(t);
  if (!m) return t;
  const [, y, mo, d] = m;
  const month = mo ? MONTHS[Number(mo) - 1] : undefined;
  if (mo && !month) return t;
  return [d, month, y].filter(Boolean).join(' ');
}

function labelOf(list: { value: string; label: string }[], v: string | null | undefined): string {
  return list.find((x) => x.value === v)?.label ?? text(v);
}

/** Whole days between two full dates, both days counted; null unless both are full dates in order. */
export function therapyDays(start: string | null | undefined, stop: string | null | undefined): number | null {
  const full = /^\d{4}-\d{2}-\d{2}$/;
  if (!full.test(text(start)) || !full.test(text(stop))) return null;
  const n = Math.round((Date.parse(`${stop}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1;
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** A product's name with its active ingredients and strengths ("Royafloxacin 500 mg (levofloxacin 500 mg)"). */
export function productLine(p: Product): string {
  const name = text(p.name);
  const parts = (p.ingredients ?? [])
    .filter((x) => filled(x.name))
    .map((x) => [text(x.name), filled(x.amount) ? `${text(x.amount)} ${text(x.unit)}`.trim() : ''].filter(Boolean).join(' '));
  const generic = parts.length ? parts.join(' + ') : text(p.active_ingredient);
  return generic && generic.toLowerCase() !== name.toLowerCase() ? `${name} (${generic})` : name;
}

/** Words kept in their own direction (Arabic inside an English line), with Unicode isolates. */
export function isolate(words: string): string {
  return `⁨${words}⁩`;
}

/** One reaction as box 7 + 13 writes it. */
export function reactionLine(r: Reaction, i: number): string {
  const english = text(r.english);
  const verbatim = text(r.verbatim);
  const words = english && english.toLowerCase() !== verbatim.toLowerCase() ? `${english} (reported as: “${isolate(verbatim)}”)` : verbatim || english;
  const bits: string[] = [];
  if (filled(r.onset_date)) bits.push(`onset ${ciomsDate(r.onset_date)}`);
  if (filled(r.end_date)) bits.push(`ended ${ciomsDate(r.end_date)}`);
  if (filled(r.outcome)) bits.push(`outcome: ${labelOf(OUTCOME, r.outcome).toLowerCase()}`);
  const criteria = (r.criteria ?? []).map((c) => labelOf(CRITERIA, c).toLowerCase());
  if (criteria.length) bits.push(`serious: ${criteria.join(', ')}`);
  if (/^\d{8}$/.test(text(r.meddra_llt_code))) {
    bits.push(`MedDRA LLT ${text(r.meddra_llt_code)}${filled(r.meddra_version) ? ` (v${text(r.meddra_version)})` : ''}`);
  }
  return `${i + 1}. ${words}${bits.length ? ` — ${bits.join('; ')}` : ''}`;
}

/** The earliest onset of the reactions (boxes 4–6). */
function firstOnset(reactions: Reaction[]): string {
  const days = reactions.map((r) => text(r.onset_date)).filter(Boolean).sort();
  return days.length ? ciomsDate(days[0]) : '';
}

function tick(on: boolean, label: string): string {
  return `<span class="tick"><span class="box">${on ? '✕' : ''}</span>${esc(label)}</span>`;
}

/** One box; attrs are fixed attributes written here (colspan, class), never case data. */
function cell(no: string, label: string, value: string, attrs = ''): string {
  return `<td${attrs ? ` ${attrs}` : ''}><div class="lbl"><b>${esc(no)}</b> ${esc(label)}</div><div class="val">${value || '&nbsp;'}</div></td>`;
}

function lines(list: string[]): string {
  return list.map((l) => esc(l)).join('<br>');
}

/** The whole CIOMS I form as a printable HTML page. */
export function ciomsHtml(input: CiomsInput): string {
  const f = input.form;
  const p = f.patient ?? {};
  const rep = f.reporter ?? {};
  const reactions = (f.reactions ?? []).filter((r) => filled(r.verbatim) || filled(r.english));
  const products = (f.products ?? []).filter((x) => filled(x.name));
  const suspects = products.filter((x) => x.role === 'suspect' || x.role === 'interacting');
  const concomitant = products.filter((x) => x.role === 'concomitant');
  const criteria = new Set(reactions.flatMap((r) => r.criteria ?? []));

  const age = filled(p.age_value)
    ? `${text(p.age_value)} ${text(p.age_unit) || 'year'}${Number(p.age_value) === 1 ? '' : 's'}`
    : text(p.age_group);
  const sex = p.sex === 'female' ? 'F' : p.sex === 'male' ? 'M' : '';

  const describe = [
    ...reactions.map(reactionLine),
    ...(filled(f.narrative) ? ['', text(f.narrative)] : []),
    ...(filled(f.causality) ? ['', `Causality: ${text(f.causality)}`] : []),
  ];

  const suspectRows = suspects.length ? suspects : [{} as Product];
  const drugs = suspectRows.map((x, i) => `${i + 1}. ${productLine(x)}${x.role === 'interacting' ? ' — interacting' : ''}`);
  const dose = suspectRows.map((x, i) => `${i + 1}. ${text(x.dose) || NOT_STATED}`);
  const route = suspectRows.map((x, i) => `${i + 1}. ${text(x.route) || NOT_STATED}`);
  const indication = suspectRows.map((x, i) => `${i + 1}. ${text(x.indication) || NOT_STATED}`);
  const dates = suspectRows.map(
    (x, i) => `${i + 1}. ${ciomsDate(x.start_date) || '?'} to ${ciomsDate(x.stop_date) || (filled(x.start_date) ? 'ongoing / not stated' : '?')}`,
  );
  const duration = suspectRows.map((x, i) => {
    const n = therapyDays(x.start_date, x.stop_date);
    return `${i + 1}. ${n ? `${n} day${n === 1 ? '' : 's'}` : NOT_STATED}`;
  });
  const actions = suspectRows
    .map((x, i) => (filled(x.action_taken) ? `${i + 1}. action taken: ${text(x.action_taken).replace(/_/g, ' ')}` : ''))
    .filter(Boolean);

  const concomitantLines = concomitant.map((x) => {
    const when = [ciomsDate(x.start_date), ciomsDate(x.stop_date)].filter(Boolean).join(' to ');
    return [productLine(x), text(x.dose), text(x.route), when].filter(Boolean).join(', ');
  });

  const history = [
    text(p.medical_history),
    p.pregnant === true ? 'Pregnant at the time of the reaction.' : '',
  ].filter(Boolean);

  const professional = ['physician', 'pharmacist', 'other_health_professional'].includes(String(rep.qualification));
  const source = {
    study: f.report_type === 'study',
    literature: f.report_type === 'literature' || filled(f.literature_reference),
    professional,
    other: !professional && f.report_type !== 'study' && f.report_type !== 'literature' && !filled(f.literature_reference),
  };
  const reporterLine = [text(rep.name), text(rep.qualification).replace(/_/g, ' '), text(rep.organisation), text(rep.country)]
    .filter(Boolean)
    .join(', ');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CIOMS I ${esc(input.ref)}</title>
<style>
  @page { size: A4; margin: 12mm; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 16px; background: #fff; color: #111; font: 9.5pt/1.35 Arial, Helvetica, sans-serif; }
  .note { max-width: 186mm; margin: 0 auto 12px; padding: 8px 10px; border: 1px solid #111; font-size: 10pt; }
  .sheet { max-width: 186mm; margin: 0 auto; }
  h1 { margin: 0; font-size: 13pt; letter-spacing: .04em; }
  .head { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 2px solid #111; padding-bottom: 4px; margin-bottom: 6px; }
  .head small { font-size: 8.5pt; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 6px; }
  td { border: 1px solid #111; padding: 3px 5px; vertical-align: top; }
  .sec { background: #111; color: #fff; font-weight: bold; font-size: 9pt; letter-spacing: .06em; padding: 3px 5px; }
  .lbl { font-size: 7.5pt; text-transform: uppercase; letter-spacing: .02em; }
  .val { min-height: 1.4em; white-space: normal; overflow-wrap: anywhere; }
  .tall .val { min-height: 6em; }
  .tick { display: block; font-size: 8.5pt; }
  .tick .box { display: inline-block; width: 11px; height: 11px; border: 1px solid #111; margin-right: 5px; text-align: center; line-height: 10px; font-size: 9px; vertical-align: -1px; }
  .foot { font-size: 7.5pt; margin-top: 4px; }
  @media print { body { padding: 0; } .note { display: none; } }
</style>
</head>
<body>
<p class="note">To send it: press Ctrl+P (or ⌘P) and choose “Save as PDF”. This box is not printed.</p>
<div class="sheet">
  <div class="head"><h1>CIOMS FORM — SUSPECT ADVERSE REACTION REPORT</h1><small>Case ${esc(input.ref)}</small></div>
  <table>
    <colgroup>${'<col style="width:10.5%">'.repeat(7)}<col style="width:26.5%"></colgroup>
    <tr><td colspan="8" class="sec">I. REACTION INFORMATION</td></tr>
    <tr>
      ${cell('1.', 'Patient initials', esc(text(p.initials)))}
      ${cell('1a.', 'Country', esc(text(f.country)))}
      ${cell('2.', 'Date of birth', esc(ciomsDate(p.birth_date)))}
      ${cell('2a.', 'Age', esc(age))}
      ${cell('3.', 'Sex', esc(sex))}
      ${cell('3a.', 'Weight', esc(filled(p.weight_kg) ? `${text(p.weight_kg)} kg` : ''))}
      ${cell('4–6.', 'Reaction onset', esc(firstOnset(reactions)))}
      <td rowspan="2"><div class="lbl"><b>8–12.</b> Check all appropriate to adverse reaction</div>
        ${tick(criteria.has('death'), 'Patient died')}
        ${tick(criteria.has('hospitalisation'), 'Involved or prolonged inpatient hospitalisation')}
        ${tick(criteria.has('disability'), 'Involved persistent or significant disability or incapacity')}
        ${tick(criteria.has('life_threatening'), 'Life threatening')}
        ${tick(criteria.has('congenital_anomaly'), 'Congenital anomaly')}
        ${tick(criteria.has('other_medically_important'), 'Other medically important condition')}
        ${tick(input.serious === false, 'Not serious')}
      </td>
    </tr>
    <tr>${cell('7 + 13.', 'Describe reaction(s) (including relevant tests / lab data)', lines(describe), 'class="tall" colspan="7"')}</tr>
  </table>
  <table>
    <colgroup><col style="width:24.5%"><col style="width:24.5%"><col style="width:24.5%"><col style="width:26.5%"></colgroup>
    <tr><td colspan="4" class="sec">II. SUSPECT DRUG(S) INFORMATION</td></tr>
    <tr>${cell('14.', 'Suspect drug(s) (include generic name)', lines(drugs), 'colspan="3"')}
      <td rowspan="3"><div class="lbl"><b>20.</b> Did reaction abate after stopping drug?</div>
        ${tick(false, 'Yes')}${tick(false, 'No')}${tick(true, 'NA / not stated')}
        <div class="lbl" style="margin-top:6px"><b>21.</b> Did reaction reappear after reintroduction?</div>
        ${tick(false, 'Yes')}${tick(false, 'No')}${tick(true, 'NA / not stated')}
        ${actions.length ? `<div class="foot">${lines(actions)}</div>` : ''}
      </td></tr>
    <tr>${cell('15.', 'Daily dose(s)', lines(dose))}${cell('16.', 'Route(s) of administration', lines(route), 'colspan="2"')}</tr>
    <tr>${cell('17.', 'Indication(s) for use', lines(indication))}${cell('18.', 'Therapy dates (from / to)', lines(dates))}${cell('19.', 'Therapy duration', lines(duration))}</tr>
  </table>
  <table>
    <tr><td class="sec">III. CONCOMITANT DRUG(S) AND HISTORY</td></tr>
    <tr>${cell('22.', 'Concomitant drug(s) and dates of administration (exclude those used to treat reaction)', concomitantLines.length ? lines(concomitantLines) : esc(NOT_STATED))}</tr>
    <tr>${cell('23.', 'Other relevant history (e.g. diagnostics, allergies, pregnancy with last month of period)', history.length ? lines(history) : esc(NOT_STATED))}</tr>
  </table>
  <table>
    <colgroup><col style="width:36.75%"><col style="width:36.75%"><col style="width:26.5%"></colgroup>
    <tr><td colspan="3" class="sec">IV. MANUFACTURER INFORMATION</td></tr>
    <tr>${cell('24a.', 'Name and address of manufacturer', esc(MANUFACTURER), 'colspan="2"')}
      <td rowspan="3"><div class="lbl"><b>24d.</b> Report source</div>
        ${tick(source.study, 'Study')}${tick(source.literature, 'Literature')}${tick(source.professional, 'Health professional')}${tick(source.other, 'Other (consumer / patient)')}
        ${filled(f.literature_reference) ? `<div class="foot">${esc(text(f.literature_reference))}</div>` : ''}
        ${reporterLine ? `<div class="foot">Reporter: ${esc(reporterLine)}</div>` : ''}
      </td></tr>
    <tr>${cell('24b.', 'Mfr control no.', esc(input.ref))}${cell('24c.', 'Date received by manufacturer', esc(ciomsDate(input.dayZero)))}</tr>
    <tr>${cell('', 'Date of this report', esc(ciomsDate(input.today)))}
      <td><div class="lbl"><b>25a.</b> Report type</div>${tick(!input.followUp, 'Initial')}${tick(input.followUp, 'Follow-up')}</td></tr>
  </table>
  <p class="foot">Reactions are given in the reporter's words; MedDRA coding is not attached to this report unless shown beside a reaction.</p>
</div>
</body>
</html>`;
}
