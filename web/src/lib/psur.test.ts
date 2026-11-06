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
  it('has no interval without a DLP or a frequency', () => {
    expect(intervalFor({ dlp: null, frequency: '3 years' })).toBeNull();
    expect(intervalFor({ dlp: '2030-01-01', frequency: null })).toBeNull();
  });
});
