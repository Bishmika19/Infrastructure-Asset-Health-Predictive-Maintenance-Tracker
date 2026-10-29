function defaultApiBaseUrl(): string {
  if (typeof window === 'undefined') return 'http://localhost:8000';

  // The preview containers share a hostname and use the manifest-assigned backend port.
  // A VITE_API_BASE_URL override remains available for reverse-proxy deployments.
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? defaultApiBaseUrl())
  .replace(/\/$/, '');

const SESSION_KEY = 'asset-health.session';

export type Role = 'asset_manager' | 'maintenance_crew';
export type AssetType = 'Transformer' | 'Substation' | 'Pump' | 'Pipeline' | 'Other';
export type ColorBand = 'Green' | 'Amber' | 'Red';
export type CaseStatus = 'Open' | 'Assigned' | 'In Progress' | 'Complete';
export type CasePriority = 'Low' | 'Medium' | 'High' | 'Critical';
export type ConditionRating = 'Excellent' | 'Good' | 'Fair' | 'Poor' | 'Critical';

export interface User {
  id: string;
  username: string;
  role: Role;
}

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

export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}

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
  assetSnapshot: {
    assetId: string;
    assetType: AssetType;
    location: string;
    installationDate: string;
    manufacturer: string;
    lastServiceDate: string | null;
  };
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

interface Session {
  token: string;
  user: User;
}

interface RequestOptions extends Omit<RequestInit, 'body' | 'headers'> {
  body?: BodyInit | object;
  headers?: HeadersInit;
  ifMatch?: string;
  idempotencyKey?: string;
}

export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.name = 'ApiProblem';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function readSession(): Session | null {
  try {
    const stored = window.localStorage.getItem(SESSION_KEY);
    return stored ? (JSON.parse(stored) as Session) : null;
  } catch {
    return null;
  }
}

function saveSession(session: Session): void {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function toQuery(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
}

function isBodyInit(body: object | BodyInit): body is BodyInit {
  return body instanceof FormData || body instanceof URLSearchParams || body instanceof Blob;
}

function createIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();

  const values = crypto.getRandomValues(new Uint32Array(4));
  return Array.from(values, (value) => value.toString(16).padStart(8, '0')).join('-');
}

class ApiClient {
  private session: Session | null = readSession();

  get sessionUser(): User | null {
    return this.session?.user ?? null;
  }

  get hasToken(): boolean {
    return Boolean(this.session?.token);
  }

  async login(username: string, password: string): Promise<User> {
    const response = await this.request<{ accessToken: string; user: User }>('/api/v1/auth/login', {
      method: 'POST',
      body: { username, password },
    });
    this.session = { token: response.data.accessToken, user: response.data.user };
    saveSession(this.session);
    return response.data.user;
  }

  async me(): Promise<User> {
    const response = await this.request<User>('/api/v1/auth/me');
    if (this.session) {
      this.session = { ...this.session, user: response.data };
      saveSession(this.session);
    }
    return response.data;
  }

  clearSession(): void {
    this.session = null;
    window.localStorage.removeItem(SESSION_KEY);
  }

  listAssets(filters: { assetType?: AssetType; location?: string; cursor?: string } = {}): Promise<Page<Asset>> {
    return this.getPage('/api/v1/assets', filters);
  }

  getAsset(assetId: string): Promise<Asset> {
    return this.request<Asset>(`/api/v1/assets/${encodeURIComponent(assetId)}`).then((result) => result.data);
  }

  createAsset(values: Omit<Asset, 'status' | 'currentHealthScore' | 'currentColorBand' | 'flaggedSince' | 'scoreCalculatedAt' | 'version' | 'createdBy' | 'createdAt' | 'updatedAt'>): Promise<Asset> {
    return this.request<Asset>('/api/v1/assets', { method: 'POST', body: values }).then((result) => result.data);
  }

  updateAsset(assetId: string, values: Partial<Pick<Asset, 'assetType' | 'location' | 'installationDate' | 'manufacturer' | 'lastServiceDate'>>, etag: string): Promise<Asset> {
    return this.request<Asset>(`/api/v1/assets/${encodeURIComponent(assetId)}`, {
      method: 'PUT',
      body: values,
      ifMatch: etag,
    }).then((result) => result.data);
  }

  deactivateAsset(assetId: string, etag: string): Promise<Asset> {
    return this.request<Asset>(`/api/v1/assets/${encodeURIComponent(assetId)}/deactivate`, {
      method: 'POST',
      ifMatch: etag,
    }).then((result) => result.data);
  }

  listQueue(cursor?: string): Promise<Page<QueueItem>> {
    return this.getPage('/api/v1/maintenance-queue', { cursor });
  }

  listCases(filters: { cursor?: string; assetId?: string; status?: CaseStatus } = {}): Promise<Page<Case>> {
    return this.getPage('/api/v1/cases', filters);
  }

  getCase(caseId: string): Promise<{ data: Case; etag: string | null }> {
    return this.request<Case>(`/api/v1/cases/${caseId}`);
  }

  createCase(values: {
    assetId: string;
    alertId?: string;
    faultDescription: string;
    priority: CasePriority;
    assigneeId?: string;
  }, idempotencyKey = createIdempotencyKey()): Promise<Case> {
    return this.request<Case>('/api/v1/cases', {
      method: 'POST',
      body: values,
      idempotencyKey,
    }).then((result) => result.data);
  }

  updateCase(caseId: string, values: Partial<Pick<Case, 'status' | 'faultDescription' | 'priority' | 'assigneeId'>>, etag: string): Promise<Case> {
    return this.request<Case>(`/api/v1/cases/${caseId}`, {
      method: 'PATCH',
      body: values,
      ifMatch: etag,
    }).then((result) => result.data);
  }

  listHistory(assetId: string, cursor?: string): Promise<Page<HistoryEvent>> {
    return this.getPage(`/api/v1/assets/${encodeURIComponent(assetId)}/history`, { cursor });
  }

  createInspection(assetId: string, values: {
    conditionRating: ConditionRating;
    observations: string;
    photos: File[];
  }): Promise<Inspection> {
    const form = new FormData();
    form.append('condition_rating', values.conditionRating);
    form.append('observations', values.observations);
    values.photos.forEach((photo) => form.append('photos', photo));
    return this.request<Inspection>(`/api/v1/assets/${encodeURIComponent(assetId)}/inspections`, {
      method: 'POST',
      body: form,
    }).then((result) => result.data);
  }

  private getPage<T>(path: string, query: Record<string, string | undefined>): Promise<Page<T>> {
    return this.request<Page<T>>(`${path}${toQuery(query)}`).then((result) => result.data);
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<{ data: T; etag: string | null }> {
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (this.session?.token) headers.set('Authorization', `Bearer ${this.session.token}`);
    if (options.ifMatch) headers.set('If-Match', options.ifMatch);
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);

    let body: BodyInit | undefined;
    if (options.body !== undefined) {
      if (isBodyInit(options.body)) {
        body = options.body;
      } else {
        headers.set('Content-Type', 'application/json');
        body = JSON.stringify(options.body);
      }
    }

    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      body,
      headers,
    });

    if (!response.ok) {
      const problem = await response.json().catch(() => null) as {
        code?: string;
        detail?: string;
        title?: string;
        requestId?: string;
      } | null;
      throw new ApiProblem(
        response.status,
        problem?.code ?? 'request_failed',
        problem?.detail ?? problem?.title ?? `Request failed with status ${response.status}`,
        problem?.requestId,
      );
    }

    return {
      data: await response.json() as T,
      etag: response.headers.get('ETag'),
    };
  }
}

export const api = new ApiClient();

export function etagFor(version: number): string {
  return `"${version}"`;
}

export function describeProblem(error: unknown): string {
  if (error instanceof ApiProblem) {
    return error.requestId ? `${error.message} (reference ${error.requestId})` : error.message;
  }
  return 'The request could not be completed. Check your connection and try again.';
}
