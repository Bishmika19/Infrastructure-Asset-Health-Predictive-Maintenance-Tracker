import { FormEvent, useState } from 'react';
import { api, describeProblem, type Asset, type ConditionRating } from '../api/client';
import { ErrorNotice, StatusNotice } from '../app/AppShell';

const MAX_PHOTOS = 10;
const MAX_PHOTO_BYTES = 10_000_000;
const ratings: ConditionRating[] = ['Excellent', 'Good', 'Fair', 'Poor', 'Critical'];

interface LogInspectionProps {
  asset: Asset;
  onBack: () => void;
  onLogged: (asset: Asset) => void;
}

export function LogInspection({ asset, onBack, onLogged }: LogInspectionProps) {
  const [rating, setRating] = useState<ConditionRating>('Good');
  const [observations, setObservations] = useState('');
  const [photos, setPhotos] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function choosePhotos(files: FileList | null): void {
    const next = Array.from(files ?? []);
    const invalid = next.find((file) => !['image/jpeg', 'image/png'].includes(file.type) || file.size > MAX_PHOTO_BYTES);
    if (next.length > MAX_PHOTOS || invalid) {
      setPhotos([]);
      setError(`Choose at most ${MAX_PHOTOS} JPEG or PNG photos, each no larger than 10 MB.`);
      return;
    }
    setError(null);
    setPhotos(next);
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createInspection(asset.assetId, { conditionRating: rating, observations, photos });
      setNotice('Inspection logged. The asset score has been recalculated.');
      onLogged(await api.getAsset(asset.assetId));
    } catch (requestError) {
      setError(describeProblem(requestError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-labelledby="inspection-title">
      <button className="secondary-button" onClick={onBack} type="button">Back to asset</button>
      <p className="eyebrow">FR-3 · Crew workflow</p>
      <h2 id="inspection-title">Log inspection for {asset.assetId}</h2>
      <ErrorNotice message={error} />
      <StatusNotice message={notice} />
      <form className="form-card" onSubmit={submit}>
        <label htmlFor="condition-rating">Condition rating</label>
        <select id="condition-rating" onChange={(event) => setRating(event.target.value as ConditionRating)} value={rating}>
          {ratings.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <label htmlFor="observations">Observations</label>
        <textarea id="observations" maxLength={4000} onChange={(event) => setObservations(event.target.value)} required rows={7} value={observations} />
        <label htmlFor="photos">Photos <span className="optional">(optional; JPEG/PNG, max 10 files, 10 MB each)</span></label>
        <input accept="image/jpeg,image/png" id="photos" multiple onChange={(event) => choosePhotos(event.target.files)} type="file" />
        {photos.length > 0 && <p className="muted">{photos.length} photo{photos.length === 1 ? '' : 's'} ready to upload.</p>}
        <button disabled={submitting} type="submit">{submitting ? 'Logging inspection…' : 'Log inspection'}</button>
      </form>
    </section>
  );
}
