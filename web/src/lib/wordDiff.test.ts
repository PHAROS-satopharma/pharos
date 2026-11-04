import { describe, expect, it } from 'vitest';
import { diffWords, tokenize } from './wordDiff';

describe('tokenize', () => {
  it('keeps spaces as their own tokens', () => {
    expect(tokenize('a  b')).toEqual(['a', '  ', 'b']);
  });
  it('splits Japanese into characters', () => {
    expect(tokenize('禁忌です')).toEqual(['禁', '忌', 'で', 'す']);
  });
});

describe('diffWords', () => {
  it('marks the changed word only', () => {
    expect(diffWords('a b c', 'a x c')).toEqual([
      { op: 'same', text: 'a ' },
      { op: 'del', text: 'b' },
      { op: 'add', text: 'x' },
      { op: 'same', text: ' c' },
    ]);
  });

  it('finds an added sentence', () => {
    const parts = diffWords('Do not use in pregnancy.', 'Do not use in pregnancy. Monitor liver function.');
    expect(parts.filter((p) => p.op === 'add').map((p) => p.text).join('')).toBe(' Monitor liver function.');
    expect(parts.filter((p) => p.op === 'del')).toEqual([]);
  });

  it('works on Japanese without spaces', () => {
    expect(diffWords('禁忌です', '禁忌でした')).toEqual([
      { op: 'same', text: '禁忌で' },
      { op: 'del', text: 'す' },
      { op: 'add', text: 'した' },
    ]);
  });

  it('rebuilds both texts', () => {
    const before = 'Hepatic impairment: reduce the dose.';
    const after = 'Severe hepatic impairment: contraindicated.';
    const parts = diffWords(before, after);
    expect(parts.filter((p) => p.op !== 'add').map((p) => p.text).join('')).toBe(before);
    expect(parts.filter((p) => p.op !== 'del').map((p) => p.text).join('')).toBe(after);
  });

  it('handles an empty side', () => {
    expect(diffWords('', 'new text')).toEqual([{ op: 'add', text: 'new text' }]);
    expect(diffWords('old', '')).toEqual([{ op: 'del', text: 'old' }]);
  });
});
