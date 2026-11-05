import { describe, expect, it } from 'vitest';
import { getsHealthAlerts, subscriptionKinds } from './subKinds';

describe('health alerts on the People page', () => {
  it('are offered for admins only, the only people the collector sends them to', () => {
    expect(getsHealthAlerts('admin')).toBe(true);
    expect(getsHealthAlerts('reviewer')).toBe(false);
    expect(getsHealthAlerts('reader')).toBe(false);
    expect(subscriptionKinds(getsHealthAlerts('reviewer'))).not.toContain('admin_health');
    expect(subscriptionKinds(getsHealthAlerts('admin'))).toContain('admin_health');
  });
});

describe("new items on the authorities' pages", () => {
  it('are offered to everyone on the team, once a day', () => {
    expect(subscriptionKinds(false)).toContain('new_items_digest');
    expect(subscriptionKinds(true)).toContain('new_items_digest');
  });
});
