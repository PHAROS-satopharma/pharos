import '../../styles/sources.css';
import { countNew, useHorizontal } from './newItems';

/** "N new" beside the Sources tab: items the authorities published since the person last looked. */
export function NewCount() {
  const data = useHorizontal();
  const n = countNew(data);
  if (data.isPending || data.error || n === 0) return null;
  return (
    <span className="hz-tab-count" title="New on the authorities' pages since you last looked">
      {n} new
    </span>
  );
}
