import { describe, expect, it } from 'vitest';
import { STATE_LABEL, defaultMeaning, shortHash, signatureState } from './signoff';

const SHA = '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08';

describe('shortHash', () => {
  it('keeps the first and the last eight characters of a SHA-256', () => {
    expect(shortHash(SHA)).toBe('9f86d081…b0f00a08');
  });
  it('leaves a short value whole, and says so when there is none', () => {
    expect(shortHash('abc123')).toBe('abc123');
    expect(shortHash('')).toBe('—');
    expect(shortHash(null)).toBe('—');
  });
  it('writes it in lower case without spaces, as sha256sum prints it', () => {
    expect(shortHash(` ${SHA.toUpperCase()} `)).toBe('9f86d081…b0f00a08');
  });
});

describe('signatureState', () => {
  it('matches when the record is as it was signed', () => {
    expect(signatureState(SHA, SHA)).toBe('matches');
  });
  it('is changed when the files were made again after signing', () => {
    expect(signatureState(SHA, 'a'.repeat(64))).toBe('changed');
  });
  it('is unknown while the record cannot be read', () => {
    expect(signatureState(SHA, null)).toBe('unknown');
    expect(signatureState(SHA, undefined)).toBe('unknown');
  });
  it('says it in her words', () => {
    expect(STATE_LABEL.matches).toBe('Fingerprint matches');
    expect(STATE_LABEL.changed).toBe('File changed since signing');
  });
});

describe('defaultMeaning', () => {
  it('offers "Approved" to an administrator and "Reviewed" to a reviewer', () => {
    expect(defaultMeaning('admin')).toBe('approved');
    expect(defaultMeaning('reviewer')).toBe('reviewed');
    expect(defaultMeaning(null)).toBe('reviewed');
  });
});
