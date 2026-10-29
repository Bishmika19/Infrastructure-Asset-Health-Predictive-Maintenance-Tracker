import { describe, expect, it, vi } from 'vitest';
import { etagFor, LocalDataClient } from './client';

describe('standalone local data', () => {
  it('loads seeded assets, queue, cases and history without any fetch', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('No backend'));
    try {
      const client = new LocalDataClient();
      expect(client.sessionUser?.role).toBe('asset_manager');
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
    const client = new LocalDataClient();
    const result = await client.listAssets({ assetType: 'Transformer', location: 'north' });
    expect(result.items.map((asset) => asset.assetId)).toEqual(['TR-001']);
    result.items[0].location = 'Changed';
    expect((await client.getAsset('TR-001')).location).toBe('North Grid Station');
  });

  it('creates and updates assets, rejects duplicates and stale edits, and resets on a new instance', async () => {
    const client = new LocalDataClient();
    const input = { assetId: 'NEW-1', assetType: 'Pump' as const, location: 'Test', manufacturer: 'Demo', installationDate: '2020-01-01', lastServiceDate: null };
    const asset = await client.createAsset(input);
    await expect(client.createAsset(input)).rejects.toMatchObject({ status: 409 });
    const updated = await client.updateAsset(asset.assetId, { location: 'Updated' }, etagFor(asset.version));
    expect(updated.location).toBe('Updated');
    await expect(client.updateAsset(asset.assetId, {}, etagFor(asset.version))).rejects.toMatchObject({ status: 412 });
    await client.deactivateAsset(asset.assetId, etagFor(updated.version));
    expect((await client.getAsset(asset.assetId)).status).toBe('deactivated');
    await expect(new LocalDataClient().getAsset(asset.assetId)).rejects.toMatchObject({ status: 404 });
  });

  it('recalculates illustrative health scores and reconciles queue and history', async () => {
    const client = new LocalDataClient();
    await client.selectRole('maintenance_crew');
    await client.createInspection('TR-001', { conditionRating: 'Excellent', observations: 'Cooling repaired.', photos: [] });
    expect((await client.getAsset('TR-001')).currentColorBand).toBe('Green');
    expect((await client.listQueue()).items.some((item) => item.assetId === 'TR-001')).toBe(false);
    expect((await client.listHistory('TR-001')).items[0].eventKind).toBe('alert_resolved');
    await client.createInspection('TR-001', { conditionRating: 'Critical', observations: 'New fault.', photos: [] });
    expect((await client.listQueue()).items[0].assetId).toBe('TR-001');
    await expect(client.createInspection('TR-001', { conditionRating: 'Good', observations: ' ', photos: [] })).rejects.toMatchObject({ status: 422 });
  });

  it('creates and advances work orders with role and version checks', async () => {
    const client = new LocalDataClient();
    const item = await client.createCase({ assetId: 'PM-003', faultDescription: 'Check bearings', priority: 'Medium', assigneeId: 'demo-crew' });
    expect(item.status).toBe('Assigned');
    await client.selectRole('maintenance_crew');
    const updated = await client.updateCase(item.id, { status: 'In Progress' }, etagFor(item.version));
    await expect(client.updateCase(item.id, { status: 'Complete' }, etagFor(item.version))).rejects.toMatchObject({ status: 412 });
    expect((await client.updateCase(item.id, { status: 'Complete' }, etagFor(updated.version))).status).toBe('Complete');
    await expect(client.createCase({ assetId: 'PM-003', faultDescription: 'Test', priority: 'Low' })).rejects.toMatchObject({ status: 403 });
    expect((await client.listHistory('PM-003')).items[0].eventKind).toBe('work_order_status_changed');
    client.clearSession();
    expect(client.sessionUser).toBeNull();
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
    expect((await client.selectRole('asset_manager')).id).toBe('demo-manager');
  });

  it('removes deactivated assets from the queue and rejects further inspections', async () => {
    const client = new LocalDataClient();
    await client.deactivateAsset('TR-001', etagFor(1));
    expect((await client.listQueue()).items.some((item) => item.assetId === 'TR-001')).toBe(false);
    await expect(client.createInspection('TR-001', { conditionRating: 'Good', observations: 'Test', photos: [] })).rejects.toMatchObject({ status: 409 });
    await expect(client.listAssets({ cursor: '-1' })).rejects.toMatchObject({ status: 400 });
  });
});
