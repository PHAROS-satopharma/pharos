import { cx } from './cx';

/**
 * Sato Pharma's own logo, cropped to its ink so it lines up with type. The dark version sits on light
 * grounds (the sign-in panel), the reverse on navy (the footer). It credits the company that made PHAROS;
 * it is never the identity of a page — PHAROS is — so it stays small and only appears at the foot.
 */
const SATO = {
  dark: '/brand/sato-pharma.png',
  reverse: '/brand/sato-pharma-reverse.png',
} as const;
const SATO_W = 307;
const SATO_H = 116;

export function SatoMark({ tone, height = 22 }: { tone: keyof typeof SATO; height?: number }) {
  return (
    <img
      className="sato-mark"
      src={SATO[tone]}
      width={Math.round((height * SATO_W) / SATO_H)}
      height={height}
      alt="Sato Pharma"
      decoding="async"
    />
  );
}

/** The maker's credit: the Sato Pharma logo on a hairline, then who PHAROS serves. */
export function SatoCredit({ tone, className }: { tone: keyof typeof SATO; className?: string }) {
  return (
    <div className={cx('sato-credit', `sato-credit-${tone}`, className)}>
      <SatoMark tone={tone} />
      <span className="sato-credit-rule" aria-hidden />
      <span className="sato-credit-text">
        <span className="micro">Developed in-house for</span>
        <span className="sato-credit-dept">The Pharmacovigilance Department</span>
      </span>
    </div>
  );
}

/** The copyright line, the year read from the clock. */
export function SatoCopyright({ className }: { className?: string }) {
  return (
    <span className={cx('micro', className)}>
      © {new Date().getFullYear()} Sato Pharma. All rights reserved.
    </span>
  );
}
