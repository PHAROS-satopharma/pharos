import type { IssueRow } from './types';
import { DOC_TYPE_LABEL, STATUS_LABEL } from './labels';
import { cairoToday } from './format';
import { safeHref } from './safeHref';

type ExcelModule = typeof import('exceljs');

async function loadExcel(): Promise<ExcelModule> {
  // exceljs is large; it loads only when someone exports. Its browser build is CommonJS, so the
  // classes may sit on the default export.
  const mod = await import('exceljs');
  const withDefault = mod as unknown as { default?: ExcelModule };
  return withDefault.default ?? mod;
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function dayToDate(d: string | null): Date | null {
  if (!d) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  return m ? new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))) : null;
}

const INK = 'FF0E1B24';
const LINE = 'FFD9D5CC';
const SEA = 'FF1F4E5F';

/** Writes the rows of the table, as filtered on screen, to an .xlsx file and downloads it. */
export async function exportIssues(rows: IssueRow[], filterNote: string, matching?: number): Promise<void> {
  const Excel = await loadExcel();
  const wb = new Excel.Workbook();
  wb.creator = 'PHAROS';
  wb.created = new Date();

  const ws = wb.addWorksheet('Safety notifications', { views: [{ state: 'frozen', ySplit: 1 }] });
  ws.columns = [
    { header: 'Date', key: 'date', width: 13 },
    { header: 'Country', key: 'country', width: 18 },
    { header: 'Also published in', key: 'also', width: 28 },
    { header: 'Regulator', key: 'regulator', width: 34 },
    { header: 'Ingredient', key: 'ingredient', width: 22 },
    { header: 'Safety notification (original title)', key: 'title', width: 80 },
    { header: 'Type', key: 'type', width: 18 },
    { header: 'Status', key: 'status', width: 14 },
    { header: 'Link', key: 'link', width: 48 },
  ];

  for (const r of rows) {
    const anchor = r.anchor_country ?? r.countries?.[0] ?? '';
    const row = ws.addRow({
      date: dayToDate(r.first_date),
      country: anchor,
      also: (r.countries ?? []).filter((c) => c !== anchor).join(', '),
      regulator: r.anchor_regulator ?? '',
      ingredient: (r.ingredients ?? []).join(', ') || (r.class_only ? 'Class-wide' : ''),
      title: r.title,
      type: DOC_TYPE_LABEL[r.doc_type] ?? r.doc_type,
      status: STATUS_LABEL[r.status] ?? r.status,
      link: r.link ?? '',
    });
    const href = safeHref(r.link);
    if (r.link && href) {
      row.getCell('link').value = { text: r.link, hyperlink: href };
      row.getCell('link').font = { color: { argb: SEA }, underline: true };
    }
    row.alignment = { vertical: 'top' };
    row.border = { bottom: { style: 'thin', color: { argb: LINE } } };
    row.getCell('date').numFmt = 'd mmm yyyy';
    row.getCell('title').alignment = { wrapText: true, vertical: 'top' };
  }

  const head = ws.getRow(1);
  head.font = { bold: true, color: { argb: INK } };
  head.border = { bottom: { style: 'thin', color: { argb: INK } } };
  head.height = 20;
  ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: 9 } };

  const about = wb.addWorksheet('About this file');
  about.columns = [{ header: 'PHAROS — export of safety notifications', key: 'a', width: 100 }];
  about.getRow(1).font = { bold: true, color: { argb: INK } };
  about.addRow({
    a:
      matching !== undefined && matching > rows.length
        ? `Exported ${cairoToday()} (Cairo). The first ${rows.length} of ${matching} matching rows: narrow the filters to export the rest.`
        : `Exported ${cairoToday()} (Cairo). ${rows.length} rows.`,
  });
  about.addRow({ a: `Filters: ${filterNote || 'none'}` });
  about.addRow({ a: 'Titles are the regulators’ originals, exactly as published, never translated.' });

  const buf = await wb.xlsx.writeBuffer();
  downloadBlob(
    new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
    `PHAROS-notices-${cairoToday()}.xlsx`,
  );
}
