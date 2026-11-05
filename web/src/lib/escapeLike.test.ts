import { describe, expect, it } from 'vitest';
import { escapeLike } from './api';

describe('escapeLike', () => {
  it('escapes the LIKE wildcards and the escape character', () => {
    expect(escapeLike('50% of_x\\y')).toBe('50\\% of\\_x\\\\y');
  });

  it('never leaves a * the API would read as "anything"', () => {
    expect(escapeLike('*')).toBe('_');
    expect(escapeLike('a*b')).toBe('a_b');
    expect(escapeLike('**')).not.toContain('*');
  });

  it('leaves ordinary text alone', () => {
    expect(escapeLike('Valproate – pregnancy')).toBe('Valproate – pregnancy');
  });
});
