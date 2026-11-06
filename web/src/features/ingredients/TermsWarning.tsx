// The old behaviour, kept for the test-first commit: the term proposal's warnings are not shown.
export function TermsWarning(_: { warnings: string[]; busy?: boolean; onReload: () => void }) {
  return null;
}
