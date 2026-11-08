// A source a person added (origin 'user'): change what it publishes, how often it is read and its notes, or remove
// it (0100 remove_source: deleted when it has found nothing, switched off and kept when it has). The app's own
// sources are switched on and off only: the collector writes them back on every run.
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap, unwrapChanged } from '../../lib/api';
import { KIND_LABEL, SCHEDULE_LABEL } from '../../lib/labels';
import { SOURCE_KINDS, SOURCE_SCHEDULES, type Source, type SourceKind, type SourceSchedule } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Notice } from '../../ui/States';

export function ChangeSource({ source, label, onDone }: { source: Source; label: string; onDone: () => void }) {
  const qc = useQueryClient();
  const [kind, setKind] = useState<SourceKind>(source.kind);
  const [schedule, setSchedule] = useState<SourceSchedule>(source.schedule);
  const [notes, setNotes] = useState(source.notes ?? '');
  const save = useMutation({
    mutationFn: async () => {
      unwrapChanged(
        await supabase
          .from('source')
          .update({ kind, schedule, notes: notes.trim() || null })
          .eq('id', source.id)
          .eq('origin', 'user')
          .select('id'),
        'this source',
      );
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['sources'] });
      onDone();
    },
  });

  return (
    <div className="hz-edit" role="group" aria-label={`Change ${label}`}>
      <div className="form-grid">
        <Field label="What it publishes">
          <Select
            value={kind}
            onChange={(e) => setKind(e.target.value as SourceKind)}
            options={SOURCE_KINDS.map((k) => ({ value: k, label: KIND_LABEL[k] }))}
          />
        </Field>
        <Field label="How often to read it">
          <Select
            value={schedule}
            onChange={(e) => setSchedule(e.target.value as SourceSchedule)}
            options={SOURCE_SCHEDULES.map((s) => ({ value: s, label: SCHEDULE_LABEL[s] }))}
          />
        </Field>
      </div>
      <Field label="Notes (optional)">
        <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <p className="small muted">To read a different link, add it as a new source and remove this one.</p>
      {save.isError ? <Notice tone="error">Not saved: {errorMessage(save.error)}</Notice> : null}
      <div className="hz-edit-actions">
        <Button size="sm" variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
        <Button size="sm" variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function RemoveSource({ source, label, onDone }: { source: Source; label: string; onDone: () => void }) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: async () =>
      unwrap<{ outcome: 'deleted' | 'switched_off' }>(await supabase.rpc('remove_source', { p_id: source.id })),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ['sources'] });
      if (r.outcome === 'deleted') onDone();
    },
  });

  return (
    <div className="hz-edit hz-remove" role="group" aria-label={`Remove ${label}`}>
      {remove.data?.outcome === 'switched_off' ? (
        <>
          <Notice tone="ok">
            Switched off and kept: it has already found notices, and they stay in the record. It is no longer read.
          </Notice>
          <div className="hz-edit-actions">
            <Button size="sm" variant="quiet" onClick={onDone}>
              Close
            </Button>
          </div>
        </>
      ) : (
        <>
          <p>
            Remove <strong>{label}</strong>? If it has found nothing yet it is deleted. If it has found notices it is
            switched off and kept, with what it found.
          </p>
          {remove.isError ? <Notice tone="error">Not removed: {errorMessage(remove.error)}</Notice> : null}
          <div className="hz-edit-actions">
            <Button size="sm" variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>
              Remove the source
            </Button>
            <Button size="sm" variant="quiet" onClick={onDone}>
              Keep it
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
