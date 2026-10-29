import { useState } from 'react';
import { api, describeProblem, type Case, type User } from '../api/client';
import { ErrorNotice } from '../app/AppShell';

const nextStatus: Record<Case['status'], Case['status'] | null> = {
  Open: 'Assigned',
  Assigned: 'In Progress',
  'In Progress': 'Complete',
  Complete: null,
};

interface WorkOrderStatusControlProps {
  caseRecord: Case;
  user: User;
  onUpdated: (caseRecord: Case) => void;
}

export function WorkOrderStatusControl({ caseRecord, onUpdated, user }: WorkOrderStatusControlProps) {
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const target = nextStatus[caseRecord.status];
  const isEligibleCrew = user.role === 'maintenance_crew'
    && caseRecord.assigneeId === user.id
    && (caseRecord.status === 'Assigned' || caseRecord.status === 'In Progress');
  const canAdvance = target !== null && (user.role === 'asset_manager' || isEligibleCrew);

  async function advance(): Promise<void> {
    if (!target) return;
    setUpdating(true);
    setError(null);
    try {
      const latest = await api.getCase(caseRecord.id);
      if (!latest.etag) {
        setError('The Case could not be updated because its current version was not provided.');
        return;
      }
      onUpdated(await api.updateCase(caseRecord.id, { status: target }, latest.etag));
    } catch (requestError) {
      const message = describeProblem(requestError);
      setError(requestError instanceof Error && 'status' in requestError && requestError.status === 412
        ? 'This Case changed while you were viewing it. The latest version has been loaded; review it and try again.'
        : message);
    } finally {
      setUpdating(false);
    }
  }

  if (!canAdvance) return null;

  return (
    <div className="status-control">
      <button disabled={updating} onClick={() => { void advance(); }} type="button">
        {updating ? 'Updating…' : `Advance to ${target}`}
      </button>
      <ErrorNotice message={error} />
    </div>
  );
}
