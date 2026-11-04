import { cx } from './cx';

/**
 * The PHAROS logo: the owner's artwork (lighthouse, globe, capsule, wordmark and subline), used exactly as
 * supplied, in its wide and stacked versions. It is full colour on a transparent ground with a navy wordmark, so it only ever sits on a light
 * surface (the top bar and the sign-in panel are light in both themes for that reason). Never recolour,
 * crop, stretch or redraw it; every use goes through this one component.
 */
const LOGOS = {
  // the wide logo, for the thin top bar and other one-line places
  wide: { src: '/brand/pharos-logo.webp', w: 2000, h: 667 },
  // the stacked logo, for the sign-in page and anywhere with room
  stacked: { src: '/brand/pharos-logo-stacked.webp', w: 1536, h: 1024 },
} as const;

export function PharosMark({
  variant = 'wide',
  height = 44,
  className,
}: {
  variant?: keyof typeof LOGOS;
  height?: number;
  className?: string;
}) {
  const logo = LOGOS[variant];
  return (
    <img
      className={cx('pharos-logo', className)}
      src={logo.src}
      width={Math.round((height * logo.w) / logo.h)}
      height={height}
      alt="PHAROS, Pharmaceutical Alerts & Regulatory Observation System"
      decoding="async"
    />
  );
}
