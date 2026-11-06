// The Japan code field: one input, the PMDA search link and why the code is copied by hand. Shared by the term
// editor (a new ingredient, saved with save_ingredient) and JapanCodeEdit (an ingredient that exists, saved with
// set_japan_code, migration 0052).
import type { ReactNode } from 'react';
import { Input } from '../../ui/Input';
import { isJapanCode } from './readiness';
import { PMDA_SEARCH, pmdaGeneralListUrl } from './japanCode';
import '../../styles/readiness.css';

export function JapanCodeField({
  value,
  onChange,
  current,
  action,
  children,
}: {
  value: string;
  onChange: (next: string) => void;
  /** The code the ingredient has now, shown above the field with a link to its PMDA page. */
  current?: string | null;
  /** A button beside the field (Save). */
  action?: ReactNode;
  /** A notice under the field (saved, failed). */
  children?: ReactNode;
}) {
  return (
    <fieldset className="japan-code">
      <legend className="term-group-head">
        <span className="term-group-name">Japan code</span>
        <span className="soft small">PMDA product code, for Japan’s label watch</span>
      </legend>
      {current !== undefined ? (
        <p className="japan-code-now">
          {current ? (
            <>
              Now <span className="mono">{current}</span> ·{' '}
              <a href={pmdaGeneralListUrl(current)} target="_blank" rel="noreferrer">
                its products on PMDA
              </a>
            </>
          ) : (
            'None yet'
          )}
        </p>
      ) : null}
      <div className="japan-code-row">
        <Input
          aria-label="Japan code"
          value={value}
          inputMode="text"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          placeholder="e.g. 1149036"
          onChange={(e) => onChange(e.target.value.toUpperCase())}
        />
        {action}
        <a className="btn btn-sm" href={PMDA_SEARCH} target="_blank" rel="noreferrer">
          Open the PMDA search
        </a>
      </div>
      {value.trim() && !isJapanCode(value) ? (
        <p className="small danger" role="status">
          A Japan code has 7 characters (for example 1149036), or 12 for the YJ code that starts with them.
        </p>
      ) : null}
      {children}
      <p className="japan-code-why">
        PMDA’s search answers a form, not an address, so PHAROS cannot look the package insert up by name. Search the
        name there, open the product, and copy the code from the end of its address (…/GeneralList/
        <span className="mono">code</span>). Without it the row says so; the ingredient is still watched everywhere
        else.
      </p>
    </fieldset>
  );
}
