// The Japan codes field: one input for one code or several (PMDA files each form under its own code), the PMDA search
// link and why the codes are copied by hand. Shared by the term editor (a new ingredient, saved with save_ingredient)
// and JapanCodeEdit (an ingredient that exists, saved with set_japan_codes, migration 0069).
import { Fragment, type ReactNode } from 'react';
import { Input } from '../../ui/Input';
import { PMDA_SEARCH, japanCodesOf, pmdaGeneralListUrl } from './japanCode';
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
  /** The codes the ingredient has now, shown above the field, each with a link to its PMDA page. */
  current?: string[];
  /** A button beside the field (Save). */
  action?: ReactNode;
  /** A notice under the field (saved, failed). */
  children?: ReactNode;
}) {
  const { wrong } = japanCodesOf(value);
  return (
    <fieldset className="japan-code">
      <legend className="term-group-head">
        <span className="term-group-name">Japan codes</span>
        <span className="soft small">PMDA product codes, for Japan’s label watch</span>
      </legend>
      {current !== undefined ? (
        <p className="japan-code-now">
          {current.length > 0 ? (
            <>
              Now{' '}
              {current.map((code, i) => (
                <Fragment key={code}>
                  {i > 0 ? ' · ' : null}
                  <span className="mono">{code}</span>{' '}
                  <a href={pmdaGeneralListUrl(code)} target="_blank" rel="noreferrer">
                    {current.length > 1 ? 'its products' : 'its products on PMDA'}
                  </a>
                </Fragment>
              ))}
            </>
          ) : (
            'None yet'
          )}
        </p>
      ) : null}
      <div className="japan-code-row">
        <Input
          aria-label="Japan codes"
          value={value}
          inputMode="text"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          placeholder="e.g. 1141007, 1141700"
          onChange={(e) => onChange(e.target.value.toUpperCase())}
        />
        {action}
        <a className="btn btn-sm" href={PMDA_SEARCH} target="_blank" rel="noreferrer">
          Open the PMDA search
        </a>
      </div>
      {wrong.length > 0 ? (
        <p className="small danger" role="status">
          Not a Japan code: {wrong.join(', ')}. A Japan code has 7 characters (for example 1149036), or 12 for the YJ
          code that starts with them.
        </p>
      ) : null}
      {children}
      <p className="japan-code-why">
        PMDA’s search answers a form, not an address, so PHAROS cannot look the package insert up by name. Search the
        name there, open the product, and copy the code from the end of its address (…/GeneralList/
        <span className="mono">code</span>). PMDA files each form under its own code (tablets, suppositories, an
        injection): give every one, separated by commas, and Japan’s label watch reads them all. Without a code the
        row says so; the ingredient is still watched everywhere else.
      </p>
    </fieldset>
  );
}
