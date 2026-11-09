import { ErrorNote, Loading } from '../../ui/States';
import { PageHead, SectionHead } from '../../ui/Text';
import { Audits } from './Audits';
import { CapaPlan } from './CapaPlan';
import { Deviations } from './Deviations';
import { useQuality } from './parts';
import { capaCounts, dayText } from './quality';
import '../../styles/quality.css';

/**
 * Quality (0107): an observation that needs a CAPA comes from a deviation (PV-SOP-021) or an audit (PV-SOP-022);
 * both end in the one CAPA plan. Everyone signed in reads it; a reviewer or an administrator records and takes
 * the steps. Nothing here is ever deleted: every change is kept in the history.
 */
export function QualityPage() {
  const q = useQuality();
  const counts = q.data ? capaCounts(q.data.capas) : null;
  const openDeviations = q.data ? q.data.deviations.filter((d) => d.status !== 'closed').length : 0;
  const openAudits = q.data ? q.data.audits.filter((a) => a.status !== 'closed').length : 0;
  return (
    <div className="page quality">
      <PageHead
        eyebrow="Quality"
        title="Deviations, audits and CAPA"
        lede="A CAPA comes from a deviation (PV-SOP-021) or from an audit observation (PV-SOP-022). Both end in the same CAPA plan. Nothing is ever deleted: every change is kept in the history."
      />
      {q.isPending ? (
        <Loading label="Reading the quality records" />
      ) : q.isError ? (
        <ErrorNote error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <>
          <section className="section">
            <SectionHead
              index="01"
              title="Deviations"
              aside={`${openDeviations} open · ${dayText(q.data.today)}`}
            />
            <Deviations deviations={q.data.deviations} capas={q.data.capas} />
          </section>
          <section className="section">
            <SectionHead index="02" title="Audits" aside={`${openAudits} open · internal and external`} />
            <Audits audits={q.data.audits} capas={q.data.capas} />
          </section>
          <section className="section">
            <SectionHead
              index="03"
              title="CAPA plan"
              aside={counts ? `${counts.open} open · ${counts.late} late` : undefined}
            />
            <CapaPlan capas={q.data.capas} />
          </section>
        </>
      )}
    </div>
  );
}
