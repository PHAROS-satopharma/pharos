import { describe, expect, it } from 'vitest';
import { excerpts, findOccurrences, normalizeRanges, resolveRanges, segments } from './highlight';

const marked = (text: string, ranges: { start: number; end: number }[]) =>
  segments(text, ranges)
    .map((s) => (s.mark ? `[${s.text}]` : s.text))
    .join('');

describe('normalizeRanges', () => {
  it('clamps, drops empty ranges, sorts and merges overlaps', () => {
    expect(
      normalizeRanges(
        [
          { start: 8, end: 12 },
          { start: -3, end: 2 },
          { start: 5, end: 5 },
          { start: 10, end: 40 },
        ],
        20,
      ),
    ).toEqual([
      { start: 0, end: 2 },
      { start: 8, end: 20 },
    ]);
  });

  it('merges touching ranges', () => {
    expect(normalizeRanges([{ start: 0, end: 3 }, { start: 3, end: 5 }], 10)).toEqual([{ start: 0, end: 5 }]);
  });

  it('ignores ranges that are not numbers', () => {
    expect(normalizeRanges([{ start: Number.NaN, end: 4 }], 10)).toEqual([]);
  });
});

describe('segments', () => {
  it('marks the matched words and keeps every character', () => {
    const text = 'Lornoxicam: risk of hepatotoxicity';
    expect(marked(text, [{ start: 0, end: 10 }])).toBe('[Lornoxicam]: risk of hepatotoxicity');
    expect(segments(text, [{ start: 0, end: 10 }]).map((s) => s.text).join('')).toBe(text);
  });

  it('returns one plain segment when nothing matched', () => {
    expect(segments('abc', [])).toEqual([{ text: 'abc', mark: false, start: 0 }]);
  });

  it('returns nothing for empty text', () => {
    expect(segments('', [{ start: 0, end: 3 }])).toEqual([]);
  });

  it('cuts a window and keeps offsets into the full text', () => {
    const text = 'aaa bbb ccc ddd';
    const segs = segments(text, [{ start: 4, end: 7 }], 2, 9);
    expect(segs).toEqual([
      { text: 'a ', mark: false, start: 2 },
      { text: 'bbb', mark: true, start: 4 },
      { text: ' c', mark: false, start: 7 },
    ]);
  });

  it('highlights Japanese by offsets', () => {
    const text = '【警告】ロルノキシカムを含む製剤';
    expect(marked(text, [{ start: 4, end: 11 }])).toBe('【警告】[ロルノキシカム]を含む製剤');
  });
});

describe('findOccurrences', () => {
  it('is case-insensitive and finds every occurrence', () => {
    expect(findOccurrences('Lornoxicam and LORNOXICAM', 'lornoxicam')).toEqual([
      { start: 0, end: 10 },
      { start: 15, end: 25 },
    ]);
  });

  it('treats regular-expression characters literally', () => {
    expect(findOccurrences('a (b) c', '(b)')).toEqual([{ start: 2, end: 5 }]);
  });

  it('finds Finnish and Korean words', () => {
    expect(findOccurrences('Lornoksikaamia sisältävät', 'lornoksikaamia')).toEqual([{ start: 0, end: 14 }]);
    expect(findOccurrences('로르녹시캄 안전성 서한', '로르녹시캄')).toEqual([{ start: 0, end: 5 }]);
  });

  it('returns nothing for an empty needle', () => {
    expect(findOccurrences('text', '  ')).toEqual([]);
  });
});

describe('resolveRanges', () => {
  it('uses offsets that fit and searches for the words when they do not', () => {
    const text = 'Meloxicam is not lornoxicam. Lornoxicam is.';
    expect(
      resolveRanges(text, [
        { start: 17, end: 27, text: 'lornoxicam' },
        { start: 500, end: 510, text: 'Lornoxicam' },
      ]),
    ).toEqual([
      { start: 17, end: 27 },
      { start: 29, end: 39 },
    ]);
  });

  it('keeps a match split across a PDF line by its offsets', () => {
    const text = 'enthält Lornoxi-\ncam als Wirkstoff';
    expect(marked(text, resolveRanges(text, [{ start: 8, end: 20, text: 'Lornoxi-\ncam' }]))).toBe(
      'enthält [Lornoxi-\ncam] als Wirkstoff',
    );
  });
});

describe('excerpts', () => {
  const long = `${'word '.repeat(100)}LORNOXICAM${' word'.repeat(100)}`;
  const at = long.indexOf('LORNOXICAM');

  it('cuts a window around the match on word boundaries', () => {
    const [ex] = excerpts(long, [{ start: at, end: at + 10 }], 30);
    expect(ex.clippedStart).toBe(true);
    expect(ex.clippedEnd).toBe(true);
    const joined = ex.segments.map((s) => s.text).join('');
    expect(joined.startsWith('word')).toBe(true);
    expect(joined.endsWith('word')).toBe(true);
    expect(ex.segments.filter((s) => s.mark).map((s) => s.text)).toEqual(['LORNOXICAM']);
  });

  it('merges windows that overlap', () => {
    const text = 'x '.repeat(50) + 'AA' + ' y'.repeat(5) + ' BB' + ' z'.repeat(50);
    const a = text.indexOf('AA');
    const b = text.indexOf('BB');
    const exs = excerpts(text, [{ start: a, end: a + 2 }, { start: b, end: b + 2 }], 20);
    expect(exs).toHaveLength(1);
    expect(exs[0].segments.filter((s) => s.mark).map((s) => s.text)).toEqual(['AA', 'BB']);
  });

  it('never splits a surrogate pair', () => {
    const text = '𝐀'.repeat(40) + 'hit' + '𝐀'.repeat(40);
    const i = text.indexOf('hit');
    for (const ctx of [5, 6, 7, 8]) {
      const [ex] = excerpts(text, [{ start: i, end: i + 3 }], ctx);
      const joined = ex.segments.map((s) => s.text).join('');
      expect(joined).not.toMatch(/^[\uDC00-\uDFFF]/);
      expect(joined).not.toMatch(/[\uD800-\uDBFF]$/);
    }
  });

  it('returns no excerpts when nothing matched', () => {
    expect(excerpts('abc', [])).toEqual([]);
  });
});
