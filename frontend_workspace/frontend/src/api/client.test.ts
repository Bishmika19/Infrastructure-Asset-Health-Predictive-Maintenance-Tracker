import { describe, expect, it, vi } from 'vitest';
import { etagFor, LocalDataClient } from './client';

/** Create a client already signed in as the Asset Manager. */
async function managerClient(): Promise<LocalDataClient> {
  const client = new LocalDataClient();
  await client.login('asset manager', 'asset manager');
  return client;
}

describe('sign in', () => {
  it('starts signed out and accepts the Asset Manager and Maintenance Crew credentials', async () => {
    const client = new LocalDataClient();
    expect(client.sessionUser).toBeNull();
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
    const manager = await client.login('asset manager', 'asset manager');
    expect(manager).toMatchObject({ id: 'asset-manager', username: 'Asset Manager', role: 'asset_manager' });
    client.clearSession();
    const crew = await client.login('  Maintenance   Crew ', 'maintenance crew');
    expect(crew).toMatchObject({ id: 'maintenance-crew', role: 'maintenance_crew' });
    expect(client.sessionUser?.role).toBe('maintenance_crew');
  });

  it('rejects empty, unknown and mismatched credentials', async () => {
    const client = new LocalDataClient();
    await expect(client.login('', '')).rejects.toMatchObject({ status: 422 });
    await expect(client.login('asset manager', 'wrong')).rejects.toMatchObject({ status: 401 });
    await expect(client.login('asset manager', 'maintenance crew')).rejects.toMatchObject({ status: 401 });
    await expect(client.login('asset manager', 'Asset Manager')).rejects.toMatchObject({ status: 401 });
    await expect(client.login('admin', 'admin')).rejects.toMatchObject({ status: 401 });
    expect(client.sessionUser).toBeNull();
  });
});

describe('standalone data', () => {
  it('loads seeded assets, queue, cases and history without any fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('No backend'));
    try {
      const client = await managerClient();
      expect((await client.listAssets()).items).toHaveLength(6);
      expect((await client.listQueue()).items).toHaveLength(3);
      expect((await client.listCases()).items[0].id).toBe('WO-001');
      expect((await client.listHistory('TR-001')).items.length).toBeGreaterThan(0);
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });

  it('filters assets and isolates callers from stored objects', async () => {
    const client = await managerClient();
    const result = await client.listAssets({ assetType: 'Transformer', location: 'north' });
    expect(result.items.map((asset) => asset.assetId)).toEqual(['TR-001']);
    result.items[0].location = 'Changed';
    expect((await client.getAsset('TR-001')).location).toBe('North Grid Station');
  });

  it('creates and updates assets, rejects duplicates and stale edits, and resets on a new instance', async () => {
    const client = await managerClient();
    const input = { assetId: 'NEW-1', assetType: 'Pump' as const, location: 'Test', manufacturer: 'Acme', installationDate: '2020-01-01', lastServiceDate: null };
    const asset = await client.createAsset(input);
    await expect(client.createAsset(input)).rejects.toMatchObject({ status: 409 });
    const updated = await client.updateAsset(asset.assetId, { location: 'Updated' }, etagFor(asset.version));
    expect(updated.location).toBe('Updated');
    await expect(client.updateAsset(asset.assetId, {}, etagFor(asset.version))).rejects.toMatchObject({ status: 412 });
    await client.deactivateAsset(asset.assetId, etagFor(updated.version));
    expect((await client.getAsset(asset.assetId)).status).toBe('deactivated');
    await expect(new LocalDataClient().getAsset(asset.assetId)).rejects.toMatchObject({ status: 404 });
  });

  it('requires sign-in for changes', async () => {
    const client = new LocalDataClient();
    await expect(client.deactivateAsset('TR-001', etagFor(1))).rejects.toMatchObject({ status: 401 });
  });

  it('recalculates illustrative health scores and reconciles queue and history', async () => {
    const client = new LocalDataClient();
    await client.login('maintenance crew', 'maintenance crew');
    await client.createInspection('TR-001', { conditionRating: 'Excellent', observations: 'Cooling repaired.', photos: [] });
    expect((await client.getAsset('TR-001')).currentColorBand).toBe('Green');
    expect((await client.listQueue()).items.some((item) => item.assetId === 'TR-001')).toBe(false);
    expect((await client.listHistory('TR-001')).items[0].eventKind).toBe('alert_resolved');
    await client.createInspection('TR-001', { conditionRating: 'Critical', observations: 'New fault.', photos: [] });
    expect((await client.listQueue()).items[0].assetId).toBe('TR-001');
    await expect(client.createInspection('TR-001', { conditionRating: 'Good', observations: ' ', photos: [] })).rejects.toMatchObject({ status: 422 });
  });

  it('creates and advances work orders with role and version checks', async () => {
    const client = await managerClient();
    const item = await client.createCase({ assetId: 'PM-003', faultDescription: 'Check bearings', priority: 'Medium', assigneeId: 'maintenance-crew' });
    expect(item.status).toBe('Assigned');
    client.clearSession();
    await client.login('maintenance crew', 'maintenance crew');
    const updated = await client.updateCase(item.id, { status: 'In Progress' }, etagFor(item.version));
    await expect(client.updateCase(item.id, { status: 'Complete' }, etagFor(item.version))).rejects.toMatchObject({ status: 412 });
    expect((await client.updateCase(item.id, { status: 'Complete' }, etagFor(updated.version))).status).toBe('Complete');
    await expect(client.createCase({ assetId: 'PM-003', faultDescription: 'Test', priority: 'Low' })).rejects.toMatchObject({ status: 403 });
    expect((await client.listHistory('PM-003')).items[0].eventKind).toBe('work_order_status_changed');
    client.clearSession();
    expect(client.sessionUser).toBeNull();
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
  });

  it('removes deactivated assets from the queue and rejects further inspections', async () => {
    const client = await managerClient();
    await client.deactivateAsset('TR-001', etagFor(1));
    expect((await client.listQueue()).items.some((item) => item.assetId === 'TR-001')).toBe(false);
    await expect(client.createInspection('TR-001', { conditionRating: 'Good', observations: 'Test', photos: [] })).rejects.toMatchObject({ status: 409 });
    await expect(client.listAssets({ cursor: '-1' })).rejects.toMatchObject({ status: 400 });
  });
});
