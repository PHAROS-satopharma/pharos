import { describe, expect, it } from 'vitest';
import { frequencyMonths, intervalFor, pbrerSection, signalInInterval, sortIssues, type PsurIssue } from './psur';

describe('the EURD interval', () => {
  it('reads years and months', () => {
    expect(frequencyMonths('7 years')).toBe(84);
    expect(frequencyMonths('1 year')).toBe(12);
    expect(frequencyMonths('6 months')).toBe(6);
    expect(frequencyMonths('Not applicable')).toBeNull();
    expect(frequencyMonths(null)).toBeNull();
  });
  it('ends at the DLP and starts the day after the one before (lornoxicam, list of 21 October 2026)', () => {
    expect(intervalFor({ dlp: '2031-12-01', frequency: '7 years' })).toEqual({ from: '2024-12-02', to: '2031-12-01' });
  });
  it('keeps a month end a month end', () => {
    expect(intervalFor({ dlp: '2027-02-28', frequency: '6 months' })).toEqual({ from: '2026-08-29', to: '2027-02-28' });
    expect(intervalFor({ dlp: '2028-02-29', frequency: '1 year' })).toEqual({ from: '2027-03-01', to: '2028-02-29' });
  });
  it('has no interval without a DLP or a frequency', () => {
    expect(intervalFor({ dlp: null, frequency: '3 years' })).toBeNull();
    expect(intervalFor({ dlp: '2030-01-01', frequency: null })).toBeNull();
  });
});

describe('the PBRER sections', () => {
  const issue = (id: string, doc_type: PsurIssue['doc_type'], status: PsurIssue['status']): PsurIssue => ({
    id,
    first_date: '2026-11-05',
    doc_type,
    title: id,
    status,
    class_only: false,
    link: null,
    anchor_country: null,
    anchor_regulator: null,
    countries: null,
    lang: null,
  });
  it('puts each notice in its section and the not-relevant ones apart', () => {
    expect(pbrerSection('dhpc')).toBe('actions');
    expect(pbrerSection('label_change')).toBe('labels');
    expect(pbrerSection('literature')).toBe('literature');
    const s = sortIssues([
      issue('a', 'dhpc', 'relevant'),
      issue('b', 'label_change', 'new'),
      issue('c', 'literature', 'reviewed'),
      issue('d', 'recall', 'not_relevant'),
    ]);
    expect(s.actions.map((i) => i.id)).toEqual(['a']);
    expect(s.labels.map((i) => i.id)).toEqual(['b']);
    expect(s.literature.map((i) => i.id)).toEqual(['c']);
    expect(s.notRelevant.map((i) => i.id)).toEqual(['d']);
  });
  it('counts a signal open on any Cairo day of the interval', () => {
    // 22:30 UTC on 31 Dec is already 1 Jan in Cairo.
    expect(signalInInterval({ opened_at: '2026-12-31T22:30:00Z', closed_at: null }, '2026-11-05', '2026-12-31')).toBe(false);
    expect(signalInInterval({ opened_at: '2026-10-01T08:00:00Z', closed_at: '2026-11-05T08:00:00Z' }, '2026-11-05', '2026-12-31')).toBe(true);
    expect(signalInInterval({ opened_at: '2026-10-01T08:00:00Z', closed_at: '2026-11-04T08:00:00Z' }, '2026-11-05', '2026-12-31')).toBe(false);
  });
});
