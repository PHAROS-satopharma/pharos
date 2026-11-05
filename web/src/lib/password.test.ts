import { describe, expect, it } from 'vitest';
import { PASSWORD_HINT, PASSWORD_MIN_LENGTH, passwordProblem } from './password';

describe('passwordProblem', () => {
  it('refuses 10 and 11 characters (the server needs 12)', () => {
    expect(passwordProblem('Abcdefgh12')).toMatch(/12 characters/);
    expect(passwordProblem('Abcdefgh123')).toMatch(/12 characters/);
  });

  it('needs a lower-case letter, a capital and a digit', () => {
    expect(passwordProblem('abcdefgh1234')).not.toBeNull();
    expect(passwordProblem('ABCDEFGH1234')).not.toBeNull();
    expect(passwordProblem('Abcdefghijkl')).not.toBeNull();
  });

  it('accepts what the server accepts', () => {
    expect(passwordProblem('Abcdefgh1234')).toBeNull();
    expect(PASSWORD_HINT).toContain('12 characters');
    expect(PASSWORD_MIN_LENGTH).toBe(12); // supabase/config.toml minimum_password_length
  });
});
