import { describe, expect, it } from 'vitest';
import { linkAnswer } from './linkAnswer';

describe('linkAnswer', () => {
  it('answers an address that was never invited exactly like an invited one', () => {
    expect(linkAnswer(null)).toBe('sent');
    expect(linkAnswer('Signups not allowed for otp')).toBe('sent');
    expect(linkAnswer('User not found')).toBe('sent');
  });

  it('still shows real failures', () => {
    expect(linkAnswer('Email rate limit exceeded')).toBe('error');
    expect(linkAnswer('Failed to fetch')).toBe('error');
  });
});
