import type {
  DocType,
  IssueStatus,
  LinkMethod,
  MatchField,
  MatchMode,
  NotifKind,
  PersonRole,
  SourceChannel,
  SourceHealth,
  SourceKind,
  SourceSchedule,
  SubKind,
  TermKind,
} from './types';

export const STATUS_LABEL: Record<IssueStatus, string> = {
  new: 'New',
  reviewed: 'Reviewed',
  relevant: 'Relevant',
  not_relevant: 'Not relevant',
};

export const DOC_TYPE_LABEL: Record<DocType, string> = {
  dhpc: 'DHPC letter',
  safety_alert: 'Safety alert',
  safety_update: 'Safety update',
  recall: 'Recall',
  psusa: 'PSUSA outcome',
  label_change: 'Label change',
  signal: 'Signal',
  newsletter: 'Newsletter',
  literature: 'Literature',
  other: 'Other',
};

export const CHANNEL_LABEL: Record<SourceChannel, string> = {
  rss: 'RSS feed',
  atom: 'Atom feed',
  json: 'Data file',
  api: 'Public API',
  html: 'Web page',
  browser: 'Web page, read in a browser',
  email: 'Email newsletter',
};

export const KIND_LABEL: Record<SourceKind, string> = {
  safety: 'Safety notices',
  recall: 'Recalls',
  spc: 'Product information (SPC)',
  literature: 'Literature',
};

export const SCHEDULE_LABEL: Record<SourceSchedule, string> = {
  '4h': 'Every 4 hours',
  '12h': 'Twice a day',
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
};

export const HEALTH_LABEL: Record<SourceHealth, { label: string; explain: string }> = {
  ok: { label: 'Working', explain: 'Read without trouble on the last check.' },
  degraded: {
    label: 'Needs a look',
    explain: 'The page changed shape, or it has been quiet for longer than usual.',
  },
  down: { label: 'Not reachable', explain: 'The last checks could not reach the site.' },
  blocked: {
    label: 'Blocks automated reading',
    explain: 'The site refuses automated visits. It is read another way, or by hand.',
  },
  unknown: { label: 'Not checked yet', explain: 'No check has finished yet.' },
};

export const TERM_KIND_LABEL: Record<TermKind, string> = {
  inn: 'Ingredient name',
  salt: 'Salt form',
  brand: 'Brand name',
  code: 'Code',
  synonym: 'Synonym',
};

export const MODE_LABEL: Record<MatchMode, string> = {
  stem: 'Word start (catches endings)',
  exact: 'Whole word only',
  substring: 'Anywhere in the text',
};

export const FIELD_LABEL: Record<MatchField, string> = {
  structured: 'Structured data',
  title: 'Title',
  body: 'Notice text',
  attachment: 'Attached file',
};

export const METHOD_LABEL: Record<LinkMethod, string> = {
  auto: 'Linked automatically',
  suggested: 'Suggested link',
  manual: 'Linked by a person',
};

export const ROLE_LABEL: Record<PersonRole, string> = {
  admin: 'Administrator',
  reviewer: 'Reviewer',
  reader: 'Reader',
};

export const SUB_KIND_LABEL: Record<SubKind, string> = {
  ingredient: 'Ingredient notices, immediately',
  class_digest: 'Class-wide notices, daily digest',
  admin_health: 'Source health alerts',
};

export const NOTIF_KIND_LABEL: Record<NotifKind, string> = {
  immediate: 'Immediate message',
  digest: 'Daily digest',
  health: 'Source health',
  report: 'Monthly report',
};

const languageNames = new Intl.DisplayNames(['en'], { type: 'language' });
const regionNames = new Intl.DisplayNames(['en'], { type: 'region' });

/** "Japanese" for "ja". Falls back to the code only if the browser does not know it. */
export function languageName(code: string | null | undefined): string {
  if (!code) return 'Unknown language';
  try {
    return languageNames.of(code) ?? code;
  } catch {
    return code;
  }
}

/** "Germany" for "DE"; "European Union" for "EU". */
export function regionName(code: string | null | undefined): string {
  if (!code) return '';
  if (code.toUpperCase() === 'EU') return 'European Union';
  try {
    return regionNames.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

/** "www.ema.europa.eu" for a full URL. */
export function hostOf(url: string | null | undefined): string {
  if (!url) return '';
  try {
    return new URL(url).host.replace(/^www\./, '');
  } catch {
    return url;
  }
}
