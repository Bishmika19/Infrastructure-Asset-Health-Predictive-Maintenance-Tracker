import { useEffect, useState } from 'react';
import { api, describeProblem, type Case, type User } from '../api/client';
import { ErrorNotice, StatusNotice } from '../app/AppShell';
import { WorkOrderStatusControl } from '../components/WorkOrderStatusControl';
import { CreateWorkOrderModal } from './CreateWorkOrderModal';

interface WorkOrdersProps {
  user: User;
  initialCreation: { assetId: string; alertId?: string } | null;
  onCreationOpened: () => void;
  onOpenAsset: (assetId: string) => void;
}

export function WorkOrders({ initialCreation, onCreationOpened, onOpenAsset, user }: WorkOrdersProps) {
  const [cases, setCases] = useState<Case[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [creatingFor, setCreatingFor] = useState<{ assetId: string; alertId?: string } | null>(null);

  async function load(cursor?: string): Promise<void> {
    try {
      const page = await api.listCases({ cursor });
      setCases((current) => cursor ? [...current, ...page.items] : page.items);
      setNextCursor(page.nextCursor);
      setError(null);
    } catch (requestError) {
      setError(describeProblem(requestError));
    }
  }

  // The list is fetched once on entry; explicit refresh and paging reuse the local loader.
  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (initialCreation) {
      setCreatingFor(initialCreation);
      onCreationOpened();
    }
  }, [initialCreation, onCreationOpened]);

  function created(caseRecord: Case): void {
    setCreatingFor(null);
    setCases((current) => [caseRecord, ...current]);
    setNotice(`Case ${caseRecord.id} created as ${caseRecord.status}.`);
  }

  function updated(caseRecord: Case): void {
    setCases((current) => current.map((item) => item.id === caseRecord.id ? caseRecord : item));
    setNotice(`Case advanced to ${caseRecord.status}.`);
  }

  return (
    <section aria-labelledby="cases-title">
      <div className="section-header">
        <div><p className="eyebrow">FR-5 &amp; FR-6 · Case lifecycle</p><h2 id="cases-title">Cases</h2></div>
        <button className="secondary-button" onClick={() => { void load(); }} type="button">Refresh</button>
      </div>
      <p className="muted">Cases are local demo work orders. Status changes always move forward one step.</p>
      <ErrorNotice message={error} />
      <StatusNotice message={notice} />
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Maintenance Cases</caption>
          <thead><tr><th>Case</th><th>Asset</th><th>Priority</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{cases.map((caseRecord) => (
            <tr key={caseRecord.id}>
              <td><strong>{caseRecord.id.slice(0, 8)}</strong><br /><span className="muted">{new Date(caseRecord.createdAt).toLocaleString()}</span></td>
              <td><button className="link-button" onClick={() => onOpenAsset(caseRecord.assetId)} type="button">{caseRecord.assetId}</button></td>
              <td>{caseRecord.priority}</td>
              <td><span className="status-tag">{caseRecord.status}</span></td>
              <td><WorkOrderStatusControl caseRecord={caseRecord} onUpdated={updated} user={user} /></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {cases.length === 0 && !error && <p className="empty-state">No Cases are currently available. Open a flagged asset from the maintenance queue to create one.</p>}
      {nextCursor && <button className="secondary-button" onClick={() => { void load(nextCursor); }} type="button">Load more Cases</button>}
      {user.role === 'asset_manager' && <p className="muted">Create a Case directly from a flagged asset in the maintenance queue.</p>}
      {creatingFor?.assetId && <CreateWorkOrderModal assetId={creatingFor.assetId} alertId={creatingFor.alertId} onClose={() => setCreatingFor(null)} onCreated={created} />}
    </section>
  );
}
