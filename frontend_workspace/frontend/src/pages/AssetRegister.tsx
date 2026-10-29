import { useEffect, useState } from 'react';
import { api, describeProblem, type Asset, type AssetType, type User } from '../api/client';
import { ErrorNotice, StatusNotice } from '../app/AppShell';
import { AssetFormModal } from './AssetFormModal';

interface AssetRegisterProps {
  user: User;
  onOpenAsset: (asset: Asset) => void;
  onOpenInspection: (asset: Asset) => void;
  onOpenHistory: (asset: Asset) => void;
}

const assetTypes: AssetType[] = ['Transformer', 'Substation', 'Pump', 'Pipeline', 'Other'];

export function AssetRegister({ onOpenAsset, onOpenHistory, onOpenInspection, user }: AssetRegisterProps) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [assetType, setAssetType] = useState<AssetType | ''>('');
  const [location, setLocation] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | undefined>();

  async function load(reset = true): Promise<void> {
    setError(null);
    try {
      const page = await api.listAssets({
        assetType: assetType || undefined,
        location: location || undefined,
        cursor: reset ? undefined : nextCursor ?? undefined,
      });
      setAssets((current) => reset ? page.items : [...current, ...page.items]);
      setNextCursor(page.nextCursor);
    } catch (requestError) {
      setError(describeProblem(requestError));
    }
  }

  // Filters are applied by the submitted form; this effect intentionally performs one mount load.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, []);

  function saved(asset: Asset): void {
    setShowForm(false);
    setEditing(undefined);
    setNotice(`Asset ${asset.assetId} saved.`);
    void load();
  }

  const isManager = user.role === 'asset_manager';

  return (
    <section aria-labelledby="asset-register-title">
      <div className="section-header">
        <div>
          <p className="eyebrow">FR-1 · Asset register</p>
          <h2 id="asset-register-title">Infrastructure assets</h2>
        </div>
        {isManager && <button onClick={() => { setEditing(undefined); setShowForm(true); }} type="button">Create asset</button>}
      </div>
      <ErrorNotice message={error} />
      <StatusNotice message={notice} />
      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void load(); }}>
        <label>
          Type
          <select onChange={(event) => setAssetType(event.target.value as AssetType | '')} value={assetType}>
            <option value="">All types</option>
            {assetTypes.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <label>
          Location
          <input maxLength={255} onChange={(event) => setLocation(event.target.value)} placeholder="Filter by location" value={location} />
        </label>
        <button type="submit">Apply filters</button>
      </form>
      <div className="table-wrap">
        <table>
          <caption className="sr-only">Asset register</caption>
          <thead><tr><th>Asset</th><th>Location</th><th>Health</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {assets.map((asset) => (
              <tr key={asset.assetId}>
                <td><strong>{asset.assetId}</strong><br /><span className="muted">{asset.assetType}</span></td>
                <td>{asset.location}</td>
                <td><ScoreBadge asset={asset} /></td>
                <td><span className={`status-tag ${asset.status}`}>{asset.status}</span></td>
                <td className="table-actions">
                  <button className="link-button" onClick={() => onOpenAsset(asset)} type="button">Details</button>
                  <button className="link-button" onClick={() => onOpenHistory(asset)} type="button">History</button>
                  {user.role === 'maintenance_crew' && asset.status === 'active' && (
                    <button className="link-button" onClick={() => onOpenInspection(asset)} type="button">Log inspection</button>
                  )}
                  {isManager && (
                    <button className="link-button" onClick={() => { setEditing(asset); setShowForm(true); }} type="button">Edit</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {assets.length === 0 && !error && <p className="empty-state">No assets match the selected filters.</p>}
      {nextCursor && <button className="secondary-button" onClick={() => { void load(false); }} type="button">Load more assets</button>}
      {showForm && <AssetFormModal asset={editing} onClose={() => setShowForm(false)} onSaved={saved} />}
    </section>
  );
}

export function ScoreBadge({ asset }: { asset: Asset }) {
  if (asset.currentHealthScore === null || !asset.currentColorBand) {
    return <span className="score-badge unscored">Not inspected</span>;
  }
  return <span className={`score-badge ${asset.currentColorBand.toLowerCase()}`}>{asset.currentColorBand}: {asset.currentHealthScore}</span>;
}
