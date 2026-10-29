import { useEffect, useState } from 'react';
import { api, describeProblem, type QueueItem } from '../api/client';
import { ErrorNotice } from '../app/AppShell';

interface MaintenanceQueueProps {
  onOpenAsset: (assetId: string) => void;
  onCreateCase: (caseDraft: { assetId: string; alertId: string }) => void;
}

export function MaintenanceQueue({ onCreateCase, onOpenAsset }: MaintenanceQueueProps) {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(cursor?: string): Promise<void> {
    try {
      const page = await api.listQueue(cursor);
      setItems((current) => cursor ? [...current, ...page.items] : page.items);
      setNextCursor(page.nextCursor);
      setError(null);
    } catch (requestError) {
      setError(describeProblem(requestError));
    }
  }

  useEffect(() => { void load(); }, []);

  return (
    <section aria-labelledby="queue-title">
      <div className="section-header">
        <div><p className="eyebrow">FR-4 · Predictive alert</p><h2 id="queue-title">Maintenance queue</h2></div>
        <button className="secondary-button" onClick={() => { void load(); }} type="button">Refresh</button>
      </div>
      <p className="muted">Assets are ordered by lowest score, oldest flagged time, then asset ID.</p>
      <ErrorNotice message={error} />
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Flagged assets requiring maintenance</caption>
          <thead><tr><th>Asset</th><th>Location</th><th>Score</th><th>Flagged since</th><th>Actions</th></tr></thead>
          <tbody>{items.map((item) => (
            <tr key={item.alertId}>
              <td><strong>{item.assetId}</strong><br /><span className="muted">{item.assetType}</span></td>
              <td>{item.location}</td>
              <td><span className="score-badge red">{item.currentColorBand}: {item.currentHealthScore}</span></td>
              <td>{new Date(item.flaggedSince).toLocaleString()}</td>
              <td className="table-actions">
                <button className="link-button" onClick={() => onOpenAsset(item.assetId)} type="button">Details</button>
                <button className="link-button" onClick={() => onCreateCase({ assetId: item.assetId, alertId: item.alertId })} type="button">Create Case</button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {items.length === 0 && !error && <p className="empty-state">There are no active predictive alerts.</p>}
      {nextCursor && <button className="secondary-button" onClick={() => { void load(nextCursor); }} type="button">Load more queue items</button>}
    </section>
  );
}
