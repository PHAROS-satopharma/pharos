import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { TermsWarning } from './TermsWarning';

const TIMED_OUT =
  'Wikidata did not answer in time, so the names in other languages are missing: only the English sources are shown.';

/** The first element in the tree whose text is `label` (the tree is walked, nothing is mounted). */
function findByText(node: ReactNode, label: string): ReactElement<{ onClick?: () => void; children?: ReactNode }> | null {
  if (Array.isArray(node)) {
    for (const n of node) {
      const hit = findByText(n, label);
      if (hit) return hit;
    }
    return null;
  }
  if (!isValidElement<{ children?: ReactNode }>(node)) return null;
  if (node.props.children === label) return node as ReactElement<{ onClick?: () => void; children?: ReactNode }>;
  if (typeof node.type === 'function') return findByText((node.type as (p: unknown) => ReactNode)(node.props), label);
  return findByText(node.props.children, label);
}

describe('TermsWarning', () => {
  it('shows nothing when the lookup sent no warning', () => {
    expect(renderToStaticMarkup(<TermsWarning warnings={[]} onReload={() => {}} />)).toBe('');
  });

  it('shows each warning and a button to load the names again', () => {
    const html = renderToStaticMarkup(
      <TermsWarning warnings={[TIMED_OUT, 'PubChem did not answer; its suggestions are missing.']} onReload={() => {}} />,
    );
    expect(html).toContain('names in other languages are missing');
    expect(html).toContain('PubChem did not answer');
    expect(html).toContain('Load the names again');
    expect(html).toContain('role="alert"');
  });

  it('the button runs the lookup again', () => {
    const onReload = vi.fn();
    const button = findByText(TermsWarning({ warnings: [TIMED_OUT], onReload }), 'Load the names again');
    expect(button).not.toBeNull();
    button?.props.onClick?.();
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
