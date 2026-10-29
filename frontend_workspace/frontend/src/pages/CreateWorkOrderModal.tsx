import { FormEvent, useState } from 'react';
import { api, crewMembers, describeProblem, type Case, type CasePriority } from '../api/client';
import { ErrorNotice } from '../app/AppShell';

const priorities: CasePriority[] = ['Low', 'Medium', 'High', 'Critical'];

interface CreateWorkOrderModalProps {
  assetId: string;
  alertId?: string;
  onClose: () => void;
  onCreated: (caseRecord: Case) => void;
}

export function CreateWorkOrderModal({ alertId, assetId, onClose, onCreated }: CreateWorkOrderModalProps) {
  const [faultDescription, setFaultDescription] = useState('');
  const [priority, setPriority] = useState<CasePriority>('Medium');
  const [assigneeId, setAssigneeId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onCreated(await api.createCase({
        assetId,
        alertId,
        faultDescription,
        priority,
        assigneeId: assigneeId || undefined,
      }));
    } catch (requestError) {
      setError(describeProblem(requestError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div aria-labelledby="case-form-title" aria-modal="true" className="modal-backdrop" role="dialog">
      <form className="modal-card" onSubmit={submit}>
        <div className="section-header"><h2 id="case-form-title">Create Case for {assetId}</h2><button aria-label="Close Case form" className="icon-button" onClick={onClose} type="button">×</button></div>
        <p className="muted">Cases can be created only for active flagged assets.</p>
        <ErrorNotice message={error} />
        <label htmlFor="fault-description">Fault description</label>
        <textarea id="fault-description" maxLength={4000} onChange={(event) => setFaultDescription(event.target.value)} required rows={6} value={faultDescription} />
        <label htmlFor="priority">Priority</label>
        <select id="priority" onChange={(event) => setPriority(event.target.value as CasePriority)} value={priority}>
          {priorities.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <label htmlFor="assignee-id">Assign to crew <span className="optional">(optional)</span></label>
        <select id="assignee-id" onChange={(event) => setAssigneeId(event.target.value)} value={assigneeId}>
          <option value="">Unassigned</option>
          {crewMembers.map((member) => <option key={member.id} value={member.id}>{member.username}</option>)}
        </select>
        <div className="action-row"><button className="secondary-button" onClick={onClose} type="button">Cancel</button><button disabled={submitting} type="submit">{submitting ? 'Creating…' : 'Create Case'}</button></div>
      </form>
    </div>
  );
}
