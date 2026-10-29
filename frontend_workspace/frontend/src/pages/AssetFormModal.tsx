import { FormEvent, useState } from 'react';
import { api, describeProblem, etagFor, type Asset, type AssetType } from '../api/client';
import { ErrorNotice } from '../app/AppShell';

const assetTypes: AssetType[] = ['Transformer', 'Substation', 'Pump', 'Pipeline', 'Other'];

interface AssetFormModalProps {
  asset?: Asset;
  onClose: () => void;
  onSaved: (asset: Asset) => void;
}

export function AssetFormModal({ asset, onClose, onSaved }: AssetFormModalProps) {
  const isEditing = Boolean(asset);
  const [assetId, setAssetId] = useState(asset?.assetId ?? '');
  const [assetType, setAssetType] = useState<AssetType>(asset?.assetType ?? 'Transformer');
  const [location, setLocation] = useState(asset?.location ?? '');
  const [installationDate, setInstallationDate] = useState(asset?.installationDate ?? '');
  const [manufacturer, setManufacturer] = useState(asset?.manufacturer ?? '');
  const [lastServiceDate, setLastServiceDate] = useState(asset?.lastServiceDate ?? '');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const values = {
        assetType,
        location,
        installationDate,
        manufacturer,
        lastServiceDate: lastServiceDate || null,
      };
      const saved = asset
        ? await api.updateAsset(asset.assetId, values, etagFor(asset.version))
        : await api.createAsset({ assetId, ...values });
      onSaved(saved);
    } catch (requestError) {
      setError(describeProblem(requestError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div aria-labelledby="asset-form-title" aria-modal="true" className="modal-backdrop" role="dialog">
      <form className="modal-card" onSubmit={submit}>
        <div className="section-header">
          <h2 id="asset-form-title">{isEditing ? 'Edit asset' : 'Create asset'}</h2>
          <button aria-label="Close asset form" className="icon-button" onClick={onClose} type="button">×</button>
        </div>
        <ErrorNotice message={error} />
        {!isEditing && (
          <>
            <label htmlFor="asset-id">Asset ID</label>
            <input id="asset-id" maxLength={128} onChange={(event) => setAssetId(event.target.value)} required value={assetId} />
          </>
        )}
        <label htmlFor="asset-type">Type</label>
        <select id="asset-type" onChange={(event) => setAssetType(event.target.value as AssetType)} value={assetType}>
          {assetTypes.map((type) => <option key={type} value={type}>{type}</option>)}
        </select>
        <label htmlFor="asset-location">Location</label>
        <input id="asset-location" maxLength={255} onChange={(event) => setLocation(event.target.value)} required value={location} />
        <label htmlFor="installation-date">Installation date</label>
        <input id="installation-date" onChange={(event) => setInstallationDate(event.target.value)} required type="date" value={installationDate} />
        <label htmlFor="manufacturer">Manufacturer</label>
        <input id="manufacturer" maxLength={255} onChange={(event) => setManufacturer(event.target.value)} required value={manufacturer} />
        <label htmlFor="last-service-date">Last service date <span className="optional">(optional)</span></label>
        <input id="last-service-date" onChange={(event) => setLastServiceDate(event.target.value)} type="date" value={lastServiceDate} />
        <div className="action-row">
          <button className="secondary-button" onClick={onClose} type="button">Cancel</button>
          <button disabled={submitting} type="submit">{submitting ? 'Saving…' : 'Save asset'}</button>
        </div>
      </form>
    </div>
  );
}
