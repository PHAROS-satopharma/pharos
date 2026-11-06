import { describe, expect, it } from 'vitest';
import { addMonths, frequencyMonths, intervalFor } from './psur';

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
    expect(addMonths('2026-08-31', 6)).toBe('2027-02-28');
  });
  it('starts the day after the previous DLP when a short month cut this one (audit, 6 Nov 2026)', () => {
    // 6-monthly, DLPs on 31 Aug and 28 Feb: the next DLP (31 Aug 2027) says the day is the 31st, so the interval
    // to 28 Feb 2027 starts on 1 Sep 2026, not on 29 Aug, which the previous PSUR covered.
    expect(intervalFor({ dlp: '2027-02-28', frequency: '6 months', next_dlp: '2027-08-31' })).toEqual({
      from: '2026-09-01',
      to: '2027-02-28',
    });
    // 30 November and 30 May: a month end that is the day itself, not a cut 31st
    expect(intervalFor({ dlp: '2026-11-30', frequency: '6 months', next_dlp: '2027-05-30' })).toEqual({
      from: '2026-05-31',
      to: '2026-11-30',
    });
    expect(intervalFor({ dlp: '2026-04-30', frequency: '6 months', next_dlp: '2026-10-31' })).toEqual({
      from: '2025-11-01',
      to: '2026-04-30',
    });
    // a DLP in the middle of the month is never moved by the next one
    expect(intervalFor({ dlp: '2026-03-15', frequency: '6 months', next_dlp: '2026-09-15' })).toEqual({
      from: '2025-09-16',
      to: '2026-03-15',
    });
  });

  it('has no interval without a DLP or a frequency', () => {
    expect(intervalFor({ dlp: null, frequency: '3 years' })).toBeNull();
    expect(intervalFor({ dlp: '2030-01-01', frequency: null })).toBeNull();
  });
});
