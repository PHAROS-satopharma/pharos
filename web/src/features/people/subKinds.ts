import type { PersonRole, SubKind } from '../../lib/types';

/** Source health alerts go to admins only (collectors/core/store.py subscribers('admin_health')). */
export function getsHealthAlerts(role: PersonRole | null | undefined): boolean {
  return role === 'admin';
}

/** What can be added for a person: health alerts only where they would arrive. */
export function subscriptionKinds(allowHealth: boolean): SubKind[] {
  return allowHealth ? ['ingredient', 'class_digest', 'admin_health'] : ['ingredient', 'class_digest'];
}
