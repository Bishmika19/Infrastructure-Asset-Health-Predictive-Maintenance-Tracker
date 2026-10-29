export type Role = 'asset_manager' | 'maintenance_crew';
export type AssetType = 'Transformer' | 'Substation' | 'Pump' | 'Pipeline' | 'Other';
export type ColorBand = 'Green' | 'Amber' | 'Red';
export type CaseStatus = 'Open' | 'Assigned' | 'In Progress' | 'Complete';
export type CasePriority = 'Low' | 'Medium' | 'High' | 'Critical';
export type ConditionRating = 'Excellent' | 'Good' | 'Fair' | 'Poor' | 'Critical';

export interface User { id: string; username: string; role: Role }
export interface Asset {
  assetId: string;
  assetType: AssetType;
  location: string;
  installationDate: string;
  manufacturer: string;
  lastServiceDate: string | null;
  status: 'active' | 'deactivated';
  currentHealthScore: number | null;
  currentColorBand: ColorBand | null;
  flaggedSince: string | null;
  scoreCalculatedAt: string | null;
  version: number;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}
export interface Page<T> { items: T[]; nextCursor: string | null }
export interface QueueItem {
  alertId: string;
  assetId: string;
  assetType: AssetType;
  location: string;
  currentHealthScore: number;
  currentColorBand: ColorBand;
  flaggedSince: string;
}
export interface Case {
  id: string;
  assetId: string;
  assetSnapshot: Pick<Asset, 'assetId' | 'assetType' | 'location' | 'installationDate' | 'manufacturer' | 'lastServiceDate'>;
  alertId: string | null;
  faultDescription: string;
  priority: CasePriority;
  assigneeId: string | null;
  status: CaseStatus;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  version: number;
}
export interface HistoryEvent {
  eventId: string;
  eventKind: 'inspection_logged' | 'alert_opened' | 'alert_resolved' | 'work_order_status_changed';
  occurredAt: string;
  actorId: string | null;
  details: Record<string, unknown>;
}
export interface Inspection {
  id: string;
  assetId: string;
  conditionRating: ConditionRating;
  observations: string;
  inspectorId: string;
  inspectedAt: string;
  createdAt: string;
  photos: Array<{
    id: string;
    contentType: 'image/jpeg' | 'image/png';
    sizeBytes: number;
    checksum: string;
    uploadedAt: string;
  }>;
}

type AssetInput = Pick<Asset, 'assetId' | 'assetType' | 'location' | 'installationDate' | 'manufacturer' | 'lastServiceDate'>;
const users: Record<Role, User> = {
  asset_manager: { id: 'asset-manager', username: 'Asset Manager', role: 'asset_manager' },
  maintenance_crew: { id: 'maintenance-crew', username: 'Maintenance Crew', role: 'maintenance_crew' },
};
/**
 * Sign-in accounts checked in the browser (the app runs without a server).
 * Usernames are matched case-insensitively with surrounding/repeated spaces ignored;
 * passwords must match exactly.
 */
const accounts: Array<{ username: string; password: string; role: Role }> = [
  { username: 'asset manager', password: 'asset manager', role: 'asset_manager' },
  { username: 'maintenance crew', password: 'maintenance crew', role: 'maintenance_crew' },
];

/** Crew members that a manager can assign Cases to. */
export const crewMembers: ReadonlyArray<Pick<User, 'id' | 'username'>> = [
  { id: users.maintenance_crew.id, username: users.maintenance_crew.username },
];

function normalizeUsername(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toLowerCase();
}
const seedDate = '2026-10-20T09:00:00.000Z';
const seedAssets: Array<[string, AssetType, string, string, number]> = [
  ['TR-001', 'Transformer', 'North Grid Station', 'Siemens', 32],
  ['SS-002', 'Substation', 'East Distribution Hub', 'ABB', 64],
  ['PM-003', 'Pump', 'Riverside Pumping Station', 'Grundfos', 92],
  ['PL-004', 'Pipeline', 'West Water Corridor', 'Flowserve', 48],
  ['TR-005', 'Transformer', 'South Grid Station', 'GE', 85],
  ['PM-006', 'Pump', 'Central Water Works', 'Xylem', 76],
];

function bandFor(score: number): ColorBand {
  return score < 50 ? 'Red' : score < 75 ? 'Amber' : 'Green';
}
function copy<T>(value: T): T {
  return structuredClone(value);
}
function page<T>(items: T[], cursor?: string): Page<T> {
  const offset = Number(cursor ?? 0);
  if (!Number.isSafeInteger(offset) || offset < 0) {
    throw new ApiProblem(400, 'invalid_cursor', 'This page is not available.');
  }
  return copy({ items: items.slice(offset, offset + 10), nextCursor: offset + 10 < items.length ? String(offset + 10) : null });
}

// PUBLIC_INTERFACE
export class ApiProblem extends Error {
  /** A local validation error, retaining the existing UI error contract. */
  // PUBLIC_INTERFACE
  constructor(public readonly status: number, public readonly code: string, message: string, public readonly requestId?: string) {
    super(message);
    this.name = 'ApiProblem';
  }
}

// PUBLIC_INTERFACE
export class LocalDataClient {
  /** In-browser data repository seeded with the built-in asset dataset. Starts signed out. */
  private user: User | null = null;
  private sequence = 0;
  private assets: Asset[] = seedAssets.map(([assetId, assetType, location, manufacturer, score]) => ({
    assetId, assetType, location, manufacturer,
    installationDate: '2018-04-15', lastServiceDate: '2026-07-10', status: 'active',
    currentHealthScore: score, currentColorBand: bandFor(score),
    flaggedSince: score < 75 ? seedDate : null, scoreCalculatedAt: seedDate,
    version: 1, createdBy: users.asset_manager.id, createdAt: seedDate, updatedAt: seedDate,
  }));
  private cases: Case[] = [{
    id: 'WO-001', assetId: 'TR-001',
    assetSnapshot: {
      assetId: 'TR-001', assetType: 'Transformer', location: 'North Grid Station',
      manufacturer: 'Siemens', installationDate: '2018-04-15', lastServiceDate: '2026-07-10',
    },
    alertId: 'alert-TR-001', faultDescription: 'Inspect overheating and replace worn cooling components.',
    priority: 'High', assigneeId: users.maintenance_crew.id, status: 'Assigned',
    createdBy: users.asset_manager.id, createdAt: seedDate, updatedAt: seedDate, version: 1,
  }];
  private history: Record<string, HistoryEvent[]> = Object.fromEntries(
    seedAssets.map(([id, , , , score]) => [id, [{
      eventId: `inspection-${id}`, eventKind: 'inspection_logged', occurredAt: seedDate,
      actorId: users.maintenance_crew.id, details: { observations: 'Scheduled condition assessment.', healthScore: score },
    }, ...(score < 75 ? [{
      eventId: `alert-${id}`, eventKind: 'alert_opened' as const, occurredAt: seedDate,
      actorId: null, details: { healthScore: score, colorBand: bandFor(score) },
    }] : [])]]),
  );
  private id(prefix: string): string {
    this.sequence += 1;
    return `${prefix}-local-${this.sequence}`;
  }
  private actor(): User {
    if (!this.user) throw new ApiProblem(401, 'sign_in_required', 'Please sign in to continue.');
    return this.user;
  }
  private manager(): void {
    if (this.actor().role !== 'asset_manager') throw new ApiProblem(403, 'manager_required', 'This action requires the Asset Manager role.');
  }
  private asset(assetId: string): Asset {
    const asset = this.assets.find((item) => item.assetId === assetId);
    if (!asset) throw new ApiProblem(404, 'asset_not_found', 'The asset was not found.');
    return asset;
  }
  private activeAsset(assetId: string): Asset {
    const asset = this.asset(assetId);
    if (asset.status !== 'active') throw new ApiProblem(409, 'inactive_asset', 'This asset is deactivated.');
    return asset;
  }
  private caseRecord(id: string): Case {
    const item = this.cases.find((record) => record.id === id);
    if (!item) throw new ApiProblem(404, 'case_not_found', 'The Case was not found.');
    return item;
  }
  private checkVersion(version: number, etag: string): void {
    if (etag !== etagFor(version)) throw new ApiProblem(412, 'version_conflict', 'This record has changed. Refresh and try again.');
  }
  private record(assetId: string, eventKind: HistoryEvent['eventKind'], details: Record<string, unknown>): void {
    (this.history[assetId] ??= []).unshift({
      eventId: this.id('event'), eventKind, occurredAt: new Date().toISOString(),
      actorId: this.actor().id, details: copy(details),
    });
  }
  // PUBLIC_INTERFACE
  get sessionUser(): User | null {
    /** Return the signed-in user, or null when signed out. */
    return copy(this.user);
  }
  // PUBLIC_INTERFACE
  get hasToken(): boolean {
    /** Whether a user is currently signed in; no token is issued or stored. */
    return this.user !== null;
  }
  // PUBLIC_INTERFACE
  async login(username: string, password: string): Promise<User> {
    /**
     * Sign in with a username and password.
     * Returns the signed-in user, or rejects with a 422 when fields are empty
     * and a 401 when the credentials do not match a known account.
     */
    if (!username.trim() || !password) {
      throw new ApiProblem(422, 'credentials_required', 'Enter your username and password.');
    }
    const account = accounts.find((item) => item.username === normalizeUsername(username) && item.password === password);
    if (!account) throw new ApiProblem(401, 'invalid_credentials', 'Incorrect username or password.');
    this.user = copy(users[account.role]);
    return copy(this.user);
  }
  // PUBLIC_INTERFACE
  async me(): Promise<User> {
    /** Return the signed-in user, rejecting with a 401 when signed out. */
    return copy(this.actor());
  }
  // PUBLIC_INTERFACE
  clearSession(): void {
    /** Sign out while retaining this page's data edits. */
    this.user = null;
  }
  // PUBLIC_INTERFACE
  async listAssets(filters: { assetType?: AssetType; location?: string; cursor?: string } = {}): Promise<Page<Asset>> {
    /** Filter the local asset register and return a page of results. */
    return page(this.assets.filter((asset) =>
      (!filters.assetType || asset.assetType === filters.assetType)
      && (!filters.location || asset.location.toLowerCase().includes(filters.location.toLowerCase()))), filters.cursor);
  }
  // PUBLIC_INTERFACE
  async getAsset(assetId: string): Promise<Asset> {
    /** Return an isolated copy of a local asset. */
    return copy(this.asset(assetId));
  }
  // PUBLIC_INTERFACE
  async createAsset(values: AssetInput): Promise<Asset> {
    /** Add an unscored asset to the register. */
    this.manager();
    if (!values.assetId.trim() || !values.location.trim() || !values.manufacturer.trim()) {
      throw new ApiProblem(422, 'required_fields', 'Asset ID, location and manufacturer are required.');
    }
    if (this.assets.some((asset) => asset.assetId === values.assetId)) throw new ApiProblem(409, 'duplicate_asset', 'An asset with this ID already exists.');
    const now = new Date().toISOString();
    const asset: Asset = {
      ...copy(values), status: 'active', currentHealthScore: null, currentColorBand: null,
      flaggedSince: null, scoreCalculatedAt: null, version: 1,
      createdBy: this.actor().id, createdAt: now, updatedAt: now,
    };
    this.assets.unshift(asset);
    return copy(asset);
  }
  // PUBLIC_INTERFACE
  async updateAsset(assetId: string, values: Partial<Omit<AssetInput, 'assetId'>>, etag: string): Promise<Asset> {
    /** Update local asset details, rejecting stale versions. */
    this.manager();
    const asset = this.activeAsset(assetId);
    this.checkVersion(asset.version, etag);
    Object.assign(asset, copy(values), { version: asset.version + 1, updatedAt: new Date().toISOString() });
    return copy(asset);
  }
  // PUBLIC_INTERFACE
  async deactivateAsset(assetId: string, etag: string): Promise<Asset> {
    /** Deactivate an asset and remove its local queue entry. */
    this.manager();
    const asset = this.activeAsset(assetId);
    this.checkVersion(asset.version, etag);
    asset.status = 'deactivated';
    asset.version += 1;
    asset.updatedAt = new Date().toISOString();
    return copy(asset);
  }
  // PUBLIC_INTERFACE
  async listQueue(cursor?: string): Promise<Page<QueueItem>> {
    /** Derive predictive alerts from active Amber and Red assets. */
    const items = this.assets.filter((asset) => asset.status === 'active' && asset.flaggedSince).map((asset) => ({
      alertId: `alert-${asset.assetId}`, assetId: asset.assetId, assetType: asset.assetType,
      location: asset.location, currentHealthScore: asset.currentHealthScore!,
      currentColorBand: asset.currentColorBand!, flaggedSince: asset.flaggedSince!,
    })).sort((a, b) => a.currentHealthScore - b.currentHealthScore);
    return page(items, cursor);
  }
  // PUBLIC_INTERFACE
  async listCases(filters: { cursor?: string; assetId?: string; status?: CaseStatus } = {}): Promise<Page<Case>> {
    /** Return filtered local work orders. */
    return page(this.cases.filter((item) =>
      (!filters.assetId || item.assetId === filters.assetId)
      && (!filters.status || item.status === filters.status)), filters.cursor);
  }
  // PUBLIC_INTERFACE
  async getCase(caseId: string): Promise<{ data: Case; etag: string | null }> {
    /** Return a local Case with its optimistic update version. */
    const item = this.caseRecord(caseId);
    return { data: copy(item), etag: etagFor(item.version) };
  }
  // PUBLIC_INTERFACE
  async createCase(values: { assetId: string; alertId?: string; faultDescription: string; priority: CasePriority; assigneeId?: string }): Promise<Case> {
    /** Create a work order and record its initial status in history. */
    this.manager();
    const asset = this.activeAsset(values.assetId);
    if (!values.faultDescription.trim()) throw new ApiProblem(422, 'description_required', 'Enter a fault description.');
    const now = new Date().toISOString();
    const item: Case = {
      ...copy(values), id: this.id('WO'), assetSnapshot: {
        assetId: asset.assetId, assetType: asset.assetType, location: asset.location,
        installationDate: asset.installationDate, manufacturer: asset.manufacturer, lastServiceDate: asset.lastServiceDate,
      },
      alertId: values.alertId ?? null, assigneeId: values.assigneeId || null,
      status: values.assigneeId ? 'Assigned' : 'Open', version: 1,
      createdBy: this.actor().id, createdAt: now, updatedAt: now,
    };
    this.cases.unshift(item);
    this.record(item.assetId, 'work_order_status_changed', { caseId: item.id, status: item.status });
    return copy(item);
  }
  // PUBLIC_INTERFACE
  async updateCase(caseId: string, values: Partial<Pick<Case, 'status' | 'faultDescription' | 'priority' | 'assigneeId'>>, etag: string): Promise<Case> {
    /** Advance a local work order, preserving role and version checks. */
    const item = this.caseRecord(caseId);
    const actor = this.actor();
    this.checkVersion(item.version, etag);
    const next: Record<CaseStatus, CaseStatus | null> = { Open: 'Assigned', Assigned: 'In Progress', 'In Progress': 'Complete', Complete: null };
    if (actor.role !== 'asset_manager' && (
      item.assigneeId !== actor.id || !['Assigned', 'In Progress'].includes(item.status)
      || Object.keys(values).some((key) => key !== 'status')
    )) throw new ApiProblem(403, 'not_assigned', 'Only the assigned crew or a manager can advance this Case.');
    if (values.status && values.status !== next[item.status]) throw new ApiProblem(409, 'invalid_transition', 'Advance the Case one status at a time.');
    Object.assign(item, copy(values), { version: item.version + 1, updatedAt: new Date().toISOString() });
    this.record(item.assetId, 'work_order_status_changed', { caseId, status: item.status });
    return copy(item);
  }
  // PUBLIC_INTERFACE
  async listHistory(assetId: string, cursor?: string): Promise<Page<HistoryEvent>> {
    /** Return the selected asset's newest-first local timeline. */
    this.asset(assetId);
    return page(this.history[assetId] ?? [], cursor);
  }
  // PUBLIC_INTERFACE
  async createInspection(assetId: string, values: { conditionRating: ConditionRating; observations: string; photos: File[] }): Promise<Inspection> {
    /** Record an inspection locally; photo metadata only is retained, with no upload. */
    const actor = this.actor();
    const asset = this.activeAsset(assetId);
    if (!values.observations.trim()) throw new ApiProblem(422, 'observations_required', 'Enter inspection observations.');
    if (values.photos.length > 10 || values.photos.some((photo) => !['image/jpeg', 'image/png'].includes(photo.type) || photo.size > 10_000_000)) {
      throw new ApiProblem(422, 'invalid_photos', 'Choose at most 10 JPEG or PNG photos, no larger than 10 MB each.');
    }
    const now = new Date().toISOString();
    // Illustrative rating-based scoring, not a production predictive model.
    const scores: Record<ConditionRating, number> = { Excellent: 95, Good: 82, Fair: 62, Poor: 38, Critical: 15 };
    const wasFlagged = Boolean(asset.flaggedSince);
    asset.currentHealthScore = scores[values.conditionRating];
    asset.currentColorBand = bandFor(asset.currentHealthScore);
    asset.flaggedSince = asset.currentColorBand === 'Green' ? null : asset.flaggedSince ?? now;
    asset.scoreCalculatedAt = now;
    asset.updatedAt = now;
    asset.version += 1;
    const inspection: Inspection = {
      id: this.id('inspection'), assetId, conditionRating: values.conditionRating,
      observations: values.observations, inspectorId: actor.id, inspectedAt: now, createdAt: now,
      photos: values.photos.map((photo) => ({
        id: this.id('photo'), contentType: photo.type as 'image/jpeg' | 'image/png',
        sizeBytes: photo.size, checksum: '', uploadedAt: now,
      })),
    };
    this.record(assetId, 'inspection_logged', { inspectionId: inspection.id, conditionRating: values.conditionRating, observations: values.observations, healthScore: asset.currentHealthScore });
    if (wasFlagged !== Boolean(asset.flaggedSince)) {
      this.record(assetId, asset.flaggedSince ? 'alert_opened' : 'alert_resolved', { healthScore: asset.currentHealthScore });
    }
    return copy(inspection);
  }
}

export const api = new LocalDataClient();

// PUBLIC_INTERFACE
export function etagFor(version: number): string {
  /** Format a local record version for the existing update controls. */
  return `"${version}"`;
}

// PUBLIC_INTERFACE
export function describeProblem(error: unknown): string {
  /** Provide a user-readable validation or workflow error. */
  return error instanceof ApiProblem ? error.message : 'The action could not be completed. Please try again.';
}
