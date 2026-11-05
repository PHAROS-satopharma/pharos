import type { PersonRole, SubKind } from '../../lib/types';

/** Source health alerts go to admins only (collectors/core/store.py subscribers('admin_health')). */
export function getsHealthAlerts(role: PersonRole | null | undefined): boolean {
  return role === 'admin';
}

/**
 * What can be added for a person: health alerts only where they would arrive. The daily count of new items
 * on the authorities' pages (collectors/alerts.py new_items_digest_if_due) is for everyone on the team.
 */
export function subscriptionKinds(allowHealth: boolean): SubKind[] {
  const everyone: SubKind[] = ['ingredient', 'class_digest', 'new_items_digest'];
  return allowHealth ? [...everyone, 'admin_health'] : everyone;
}
