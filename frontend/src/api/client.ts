import { getLanguage } from "../i18n";
import type {
  AIKeyRequest,
  AIProvider,
  AISettings,
  AIRecommendationRequest,
  AIRecommendationResponse,
  AIRecommendationStatus,
  AitherPresetsResponse,
  ArtifactList,
  BackupInfo,
  BackupList,
  ReleaseUpdateResponse,
  CapabilitiesResponse,
  CpuPolicy,
  CpuPolicyView,
  DatabaseStatus,
  DetailLevel,
  EventList,
  HealthResponse,
  Job,
  JobCreate,
  JobList,
  JobLive,
  JobReview,
  JobStatistics,
  JobStorageReport,
  JobState,
  LibraryImportResult,
  LibraryProfile,
  LibraryProfileDocument,
  LibraryProfileList,
  NoiseProfilesResponse,
  PlayerInfo,
  PreviewRecord,
  ProfileRecommendationResponse,
  ProfileSchemaResponse,
  ReleaseMetadataPayload,
  ReleasePreparation,
  ReleasePreparationList,
  ReleaseProfileList,
  ReleaseValidationResult,
  RuntimeCapabilitiesResponse,
  ScanList,
  SelectionPayload,
  SelectionValidation,
  SourceBrowserResponse,
  StatisticsResponse,
  TrackerReleaseProfile,
  UploadResetRequest,
} from "./types";

const base = import.meta.env.BASE_URL.endsWith("/")
  ? import.meta.env.BASE_URL.slice(0, -1)
  : import.meta.env.BASE_URL;

export const API_ROOT = `${base}/api/v1`;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly payload: unknown;

  constructor(status: number, detail: string, payload: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

async function responseError(response: Response): Promise<ApiError> {
  const raw = await response.text();
  let payload: unknown = raw || null;
  let detail = `A kérés sikertelen (${response.status})`;
  if (raw) {
    try {
      payload = JSON.parse(raw) as unknown;
    } catch {
      detail = raw;
    }
  }
  if (payload && typeof payload === "object" && "detail" in payload) {
    const apiDetail = payload.detail;
    if (typeof apiDetail === "string") {
      detail = apiDetail;
    } else if (Array.isArray(apiDetail)) {
      const messages = apiDetail.flatMap((item) =>
        item && typeof item === "object" && "msg" in item && typeof item.msg === "string"
          ? [item.msg]
          : [],
      );
      if (messages.length) detail = messages.join("; ");
    }
  }
  return new ApiError(response.status, detail, payload);
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      // The backend answers its messages in the interface language.
      "Accept-Language": getLanguage(),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    credentials: "same-origin",
  });

  if (!response.ok) throw await responseError(response);

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => apiFetch<HealthResponse>("/health"),
  capabilities: () => apiFetch<CapabilitiesResponse>("/capabilities"),
  runtimeCapabilities: () =>
    apiFetch<RuntimeCapabilitiesResponse>("/runtime-capabilities"),
  sources: (path?: string) =>
    apiFetch<SourceBrowserResponse>(
      `/sources${path ? `?path=${encodeURIComponent(path)}` : ""}`,
    ),
  jobs: (states?: JobState[], limit = 100, offset = 0) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    states?.forEach((state) => params.append("state", state));
    return apiFetch<JobList>(`/jobs?${params}`);
  },
  job: (id: string) => apiFetch<Job>(`/jobs/${encodeURIComponent(id)}`),
  createJob: (request: JobCreate) =>
    apiFetch<Job>("/jobs", { method: "POST", body: JSON.stringify(request) }),
  cancelJob: (id: string) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  pauseJob: (id: string, expectedControlRevision?: number) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/pause`, {
      method: "POST",
      body: JSON.stringify(expectedControlRevision == null ? {} : { expected_control_revision: expectedControlRevision }),
    }),
  continueJob: (id: string, expectedControlRevision?: number) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/continue`, {
      method: "POST",
      body: JSON.stringify(expectedControlRevision == null ? {} : { expected_control_revision: expectedControlRevision }),
    }),
  requestCancelJob: (id: string, expectedControlRevision?: number) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      body: JSON.stringify(expectedControlRevision == null ? {} : { expected_control_revision: expectedControlRevision }),
    }),
  retryJob: (id: string, expectedVersion: number) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/retry`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  restartJob: (id: string, expectedVersion: number, reconfigure = false) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/restart`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion, reconfigure }),
    }),
  purgeJob: (id: string, expectedVersion: number) =>
    apiFetch<void>(
      `/jobs/${encodeURIComponent(id)}/purge?expected_version=${expectedVersion}&preserve_release=true`,
      { method: "DELETE" },
    ),
  jobStorage: (id: string) =>
    apiFetch<JobStorageReport>(`/jobs/${encodeURIComponent(id)}/storage`),
  jobLive: (id: string) =>
    apiFetch<JobLive>(`/jobs/${encodeURIComponent(id)}/live`),
  cleanupJob: (id: string, expectedVersion: number) =>
    apiFetch<unknown>(`/jobs/${encodeURIComponent(id)}/cleanup`, {
      method: "POST",
      body: JSON.stringify({ scope: "temporary", expected_version: expectedVersion }),
    }),
  deleteJobRelease: (
    id: string,
    request: {
      confirmation: string;
      expected_sha256: string;
      force_if_seeded: boolean;
      preparation_versions: Record<string, number>;
    },
  ) => apiFetch<void>(`/jobs/${encodeURIComponent(id)}/release`, { method: "DELETE", body: JSON.stringify(request) }),
  resumeJob: (id: string) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  retryUpload: (id: string) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/retry-upload`, { method: "POST" }),
  jobReview: (id: string) =>
    apiFetch<JobReview>(`/jobs/${encodeURIComponent(id)}/review`),
  confirmTrackLanguages: (id: string, languages: Record<string, string>, expectedVersion: number) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/review/languages`, {
      method: "POST",
      body: JSON.stringify({ languages, expected_version: expectedVersion }),
    }),
  resetUpload: (id: string, request: UploadResetRequest) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/reset-upload`, {
      method: "POST",
      body: JSON.stringify(request),
    }),
  releaseProfiles: () =>
    apiFetch<ReleaseProfileList | TrackerReleaseProfile[]>("/release-profiles"),
  releasePreparations: (jobId: string) =>
    apiFetch<ReleasePreparationList | ReleasePreparation[]>(
      `/jobs/${encodeURIComponent(jobId)}/release-preparations`,
    ),
  createReleasePreparation: (
    jobId: string,
    request: { profile_id: string; metadata: ReleaseMetadataPayload },
  ) =>
    apiFetch<ReleasePreparation>(
      `/jobs/${encodeURIComponent(jobId)}/release-preparations`,
      { method: "POST", body: JSON.stringify(request) },
    ),
  releasePreparation: (preparationId: string) =>
    apiFetch<ReleasePreparation>(
      `/release-preparations/${encodeURIComponent(preparationId)}`,
    ),
  releasePreparationAction: (
    preparationId: string,
    action: "build" | "dupe-check",
    expectedVersion: number,
  ) =>
    apiFetch<ReleasePreparation>(
      `/release-preparations/${encodeURIComponent(preparationId)}/${action}`,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: expectedVersion }),
      },
    ),
  validateReleasePreparation: (preparationId: string, expectedVersion: number) =>
    apiFetch<ReleaseValidationResult>(
      `/release-preparations/${encodeURIComponent(preparationId)}/validate`,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: expectedVersion }),
      },
    ),
  deleteReleasePreparation: (preparationId: string, expectedVersion: number) =>
    apiFetch<void>(
      `/release-preparations/${encodeURIComponent(preparationId)}?expected_version=${expectedVersion}`,
      { method: "DELETE" },
    ),
  scans: (jobId: string) =>
    apiFetch<ScanList>(`/scans?job_id=${encodeURIComponent(jobId)}`),
  artifacts: (jobId: string) =>
    apiFetch<ArtifactList>(`/artifacts?job_id=${encodeURIComponent(jobId)}&limit=500`),
  events: (jobId: string, afterId = 0) =>
    apiFetch<EventList>(
      `/events?job_id=${encodeURIComponent(jobId)}&after_id=${afterId}&limit=1000`,
    ),
  analyzeMkv: (path: string) =>
    apiFetch<Record<string, unknown>>(`/analyze-mkv?path=${encodeURIComponent(path)}`),
  profileSchema: (encoder: "x264" | "x265", detail: DetailLevel) =>
    apiFetch<ProfileSchemaResponse>(
      `/profiles/${encoder}/schema?detail_level=${detail}`,
    ),
  profileRecommendation: (
    encoder: "x264" | "x265",
    detail: DetailLevel,
    contentType: string,
  ) =>
    apiFetch<ProfileRecommendationResponse>(
      `/profiles/${encoder}/recommendation?detail_level=${detail}&content_type=${encodeURIComponent(contentType.toLowerCase())}`,
    ),
  aitherPresets: (encoder: "x264" | "x265", contentType: string) =>
    apiFetch<AitherPresetsResponse>(
      `/profiles/${encoder}/aither-presets?content_type=${encodeURIComponent(contentType.toLowerCase())}`,
    ),
  noiseProfiles: (encoder: "x264" | "x265", contentType: string) =>
    apiFetch<NoiseProfilesResponse>(
      `/profiles/${encoder}/noise-profiles?content_type=${encodeURIComponent(contentType.toLowerCase())}`,
    ),
  profileLibrary: () => apiFetch<LibraryProfileList>("/profile-library"),
  saveLibraryProfile: (document: LibraryProfileDocument, overwrite = false) =>
    apiFetch<LibraryProfile>(`/profile-library${overwrite ? "?overwrite=true" : ""}`, {
      method: "POST",
      body: JSON.stringify(document),
    }),
  deleteLibraryProfile: (id: string) =>
    apiFetch<void>(`/profile-library/${encodeURIComponent(id)}`, { method: "DELETE" }),
  exportLibraryProfile: (id: string) =>
    apiFetch<Record<string, unknown>>(`/profile-library/${encodeURIComponent(id)}/export`),
  exportLibrary: () => apiFetch<Record<string, unknown>>("/profile-library/export"),
  importLibraryProfiles: (
    document: Record<string, unknown>,
    onConflict: "rename" | "skip" | "overwrite" = "rename",
  ) =>
    apiFetch<LibraryImportResult>(`/profile-library/import?on_conflict=${onConflict}`, {
      method: "POST",
      body: JSON.stringify(document),
    }),
  statistics: (limit = 200) => apiFetch<StatisticsResponse>(`/statistics?limit=${limit}`),
  jobStatistics: (id: string) =>
    apiFetch<JobStatistics>(`/jobs/${encodeURIComponent(id)}/statistics`),
  playerInfo: (jobId: string) =>
    apiFetch<PlayerInfo>(`/jobs/${encodeURIComponent(jobId)}/player`),
  createPreview: (
    jobId: string,
    request: { start_seconds: number; duration_seconds: number; height: number },
  ) =>
    apiFetch<PreviewRecord>(`/jobs/${encodeURIComponent(jobId)}/previews`, {
      method: "POST",
      body: JSON.stringify(request),
    }),
  deletePreview: (jobId: string, name: string) =>
    apiFetch<void>(
      `/jobs/${encodeURIComponent(jobId)}/previews/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  databaseStatus: () => apiFetch<DatabaseStatus>("/system/database"),
  cpuPolicy: () => apiFetch<CpuPolicyView>("/system/cpu-policy"),
  saveCpuPolicy: (policy: CpuPolicy) =>
    apiFetch<CpuPolicyView>("/system/cpu-policy", { method: "PUT", body: JSON.stringify(policy) }),
  backups: () => apiFetch<BackupList>("/system/backups"),
  releaseUpdate: () => apiFetch<ReleaseUpdateResponse>("/system/release-update"),
  createBackup: () => apiFetch<BackupInfo>("/system/backups", { method: "POST" }),
  aiRecommendationStatus: () =>
    apiFetch<AIRecommendationStatus>("/ai-recommendation/status"),
  saveAISettings: (settings: AISettings) =>
    apiFetch<AIRecommendationStatus>("/system/ai-settings", { method: "PUT", body: JSON.stringify(settings) }),
  setAIKey: (provider: AIProvider, apiKey: string) =>
    apiFetch<AIKeyRequest>(`/system/ai-credentials/${provider}`, {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey }),
    }),
  deleteAIKey: (provider: AIProvider) =>
    apiFetch<AIKeyRequest>(`/system/ai-credentials/${provider}`, { method: "DELETE" }),
  aiRecommendation: (id: string, request: AIRecommendationRequest) =>
    apiFetch<AIRecommendationResponse>(
      `/jobs/${encodeURIComponent(id)}/ai-recommendation`,
      { method: "POST", body: JSON.stringify(request) },
    ),
  validateSelection: (id: string, selection: SelectionPayload, version?: number) =>
    apiFetch<SelectionValidation>(
      `/jobs/${encodeURIComponent(id)}/selection/validate`,
      {
        method: "POST",
        body: JSON.stringify({ selection, expected_version: version }),
      },
    ),
  saveSelection: (id: string, selection: SelectionPayload, version?: number) =>
    apiFetch<Job>(`/jobs/${encodeURIComponent(id)}/selection`, {
      method: "POST",
      body: JSON.stringify({
        selection,
        message: "Operátori beállítások jóváhagyva a webes felületen",
        expected_version: version,
      }),
    }),
};

export function previewUrl(jobId: string, name: string): string {
  return `${API_ROOT}/jobs/${encodeURIComponent(jobId)}/previews/${encodeURIComponent(name)}`;
}

export function artifactContentUrl(id: string): string {
  return `${API_ROOT}/artifacts/${encodeURIComponent(id)}/content`;
}

export async function fetchArtifactText(id: string): Promise<string> {
  const response = await fetch(artifactContentUrl(id), {
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, "A melléklet nem olvasható", null);
  return response.text();
}

export async function fetchArtifactJson<T>(id: string): Promise<T> {
  const response = await fetch(artifactContentUrl(id), {
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, "A melléklet nem olvasható", null);
  return response.json() as Promise<T>;
}
