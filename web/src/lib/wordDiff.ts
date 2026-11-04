// Word-level diff for SPC sections, in the original language. Japanese and Chinese script has no
// spaces between words, so each Han, Hiragana or Katakana character is its own token.

export type DiffOp = 'same' | 'add' | 'del';

export interface DiffPart {
  op: DiffOp;
  text: string;
}

const CJK = '\\p{Script=Han}\\p{Script=Hiragana}\\p{Script=Katakana}';
const TOKEN = new RegExp(`\\s+|[${CJK}]|[^\\s${CJK}]+`, 'gu');

export function tokenize(s: string): string[] {
  return s.match(TOKEN) ?? [];
}

/** Above this many comparison cells the middle is shown as one deletion and one addition. */
const MAX_CELLS = 4_000_000;

export function diffWords(before: string, after: string): DiffPart[] {
  const a = tokenize(before);
  const b = tokenize(after);
  const parts: DiffPart[] = [];
  const push = (op: DiffOp, text: string) => {
    if (!text) return;
    const last = parts.length > 0 ? parts[parts.length - 1] : undefined;
    if (last && last.op === op) last.text += text;
    else parts.push({ op, text });
  };

  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let ea = a.length;
  let eb = b.length;
  while (ea > p && eb > p && a[ea - 1] === b[eb - 1]) {
    ea--;
    eb--;
  }

  push('same', a.slice(0, p).join(''));
  const A = a.slice(p, ea);
  const B = b.slice(p, eb);
  const n = A.length;
  const m = B.length;

  if (n * m > MAX_CELLS) {
    push('del', A.join(''));
    push('add', B.join(''));
  } else if (n > 0 || m > 0) {
    const w = m + 1;
    const L = new Uint32Array((n + 1) * (m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        L[i * w + j] = A[i] === B[j] ? L[(i + 1) * w + j + 1] + 1 : Math.max(L[(i + 1) * w + j], L[i * w + j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) {
        push('same', A[i]);
        i++;
        j++;
      } else if (L[(i + 1) * w + j] >= L[i * w + j + 1]) {
        push('del', A[i]);
        i++;
      } else {
        push('add', B[j]);
        j++;
      }
    }
    while (i < n) push('del', A[i++]);
    while (j < m) push('add', B[j++]);
  }

  push('same', a.slice(ea).join(''));
  return parts;
}
