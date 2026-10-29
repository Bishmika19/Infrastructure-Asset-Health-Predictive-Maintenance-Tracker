import { useEffect, useState } from 'react';
import { api, describeProblem, type Asset, type HistoryEvent } from '../api/client';
import { ErrorNotice } from '../app/AppShell';

interface AssetHistoryProps {
  asset: Asset;
  onBack: () => void;
}

const labels: Record<HistoryEvent['eventKind'], string> = {
  inspection_logged: 'Inspection logged',
  alert_opened: 'Alert opened',
  alert_resolved: 'Alert resolved',
  work_order_status_changed: 'Case status changed',
};

export function AssetHistory({ asset, onBack }: AssetHistoryProps) {
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(cursor?: string): Promise<void> {
    try {
      const page = await api.listHistory(asset.assetId, cursor);
      setEvents((current) => cursor ? [...current, ...page.items] : page.items);
      setNextCursor(page.nextCursor);
      setError(null);
    } catch (requestError) {
      setError(describeProblem(requestError));
    }
  }

  // The local loader is recreated only to capture the active asset ID.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, [asset.assetId]);

  return (
    <section aria-labelledby="history-title">
      <button className="secondary-button" onClick={onBack} type="button">Back to asset</button>
      <p className="eyebrow">FR-7 · Read-only timeline</p>
      <h2 id="history-title">History for {asset.assetId}</h2>
      <ErrorNotice message={error} />
      <ol className="timeline">
        {events.map((event) => (
          <li key={`${event.eventKind}-${event.eventId}`}>
            <div className="timeline-marker" aria-hidden="true" />
            <div>
              <h3>{labels[event.eventKind]}</h3>
              <p><time dateTime={event.occurredAt}>{new Date(event.occurredAt).toLocaleString()}</time> · Actor: {event.actorId ?? 'System'}</p>
              <pre>{JSON.stringify(event.details, null, 2)}</pre>
            </div>
          </li>
        ))}
      </ol>
      {events.length === 0 && !error && <p className="empty-state">No history has been recorded for this asset yet.</p>}
      {nextCursor && <button className="secondary-button" onClick={() => { void load(nextCursor); }} type="button">Load more history</button>}
    </section>
  );
}
