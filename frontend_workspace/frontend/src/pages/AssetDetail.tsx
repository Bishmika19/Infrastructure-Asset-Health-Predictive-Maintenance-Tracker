import { useEffect, useState } from 'react';
import { api, describeProblem, etagFor, type Asset, type User } from '../api/client';
import { ErrorNotice, StatusNotice } from '../app/AppShell';
import { ScoreBadge } from './AssetRegister';

interface AssetDetailProps {
  assetId: string;
  user: User;
  onBack: () => void;
  onOpenInspection: (asset: Asset) => void;
  onOpenHistory: (asset: Asset) => void;
  onOpenCases: () => void;
}

export function AssetDetail({ assetId, onBack, onOpenCases, onOpenHistory, onOpenInspection, user }: AssetDetailProps) {
  const [asset, setAsset] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load(): Promise<void> {
    try {
      setAsset(await api.getAsset(assetId));
      setError(null);
    } catch (requestError) {
      setError(describeProblem(requestError));
    }
  }

  // The local loader is recreated only to capture the active asset ID.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, [assetId]);

  async function deactivate(): Promise<void> {
    if (!asset || !window.confirm(`Deactivate ${asset.assetId}? Its history will be retained.`)) return;
    try {
      const updated = await api.deactivateAsset(asset.assetId, etagFor(asset.version));
      setAsset(updated);
      setNotice(`${updated.assetId} is now deactivated.`);
    } catch (requestError) {
      setError(describeProblem(requestError));
    }
  }

  if (!asset) return <section><button className="secondary-button" onClick={onBack} type="button">Back to register</button><ErrorNotice message={error ?? 'Loading asset…'} /></section>;

  return (
    <section aria-labelledby="asset-detail-title">
      <button className="secondary-button" onClick={onBack} type="button">Back to register</button>
      <div className="section-header">
        <div>
          <p className="eyebrow">{asset.assetType} · {asset.status}</p>
          <h2 id="asset-detail-title">{asset.assetId}</h2>
        </div>
        <ScoreBadge asset={asset} />
      </div>
      <ErrorNotice message={error} />
      <StatusNotice message={notice} />
      <dl className="detail-grid">
        <div><dt>Location</dt><dd>{asset.location}</dd></div>
        <div><dt>Manufacturer</dt><dd>{asset.manufacturer}</dd></div>
        <div><dt>Installed</dt><dd>{asset.installationDate}</dd></div>
        <div><dt>Last service</dt><dd>{asset.lastServiceDate ?? 'No service recorded'}</dd></div>
        <div><dt>Score calculated</dt><dd>{asset.scoreCalculatedAt ? new Date(asset.scoreCalculatedAt).toLocaleString() : 'Not inspected'}</dd></div>
        <div><dt>Flagged since</dt><dd>{asset.flaggedSince ? new Date(asset.flaggedSince).toLocaleString() : 'Not flagged'}</dd></div>
      </dl>
      <div className="action-row">
        <button className="secondary-button" onClick={() => onOpenHistory(asset)} type="button">View history</button>
        {user.role === 'maintenance_crew' && asset.status === 'active' && <button onClick={() => onOpenInspection(asset)} type="button">Log inspection</button>}
        {user.role === 'asset_manager' && asset.status === 'active' && asset.flaggedSince && (
          <button onClick={onOpenCases} type="button">View Cases</button>
        )}
        {user.role === 'asset_manager' && asset.status === 'active' && <button className="danger-button" onClick={() => { void deactivate(); }} type="button">Deactivate asset</button>}
      </div>
    </section>
  );
}
