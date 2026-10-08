import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Code2,
  Disc3,
  Download,
  File,
  FileJson,
  FileText,
  FolderOpen,
  Gauge,
  HardDrive,
  Images,
  Info,
  ListChecks,
  LoaderCircle,
  MoreHorizontal,
  PackageCheck,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldCheck,
  StopCircle,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { api, ApiError, artifactContentUrl, fetchArtifactText } from "../api/client";
import type { Artifact, DiscScanResult, EventRecord, Job, JobLive, JobOperation, JobStorageReport, ReleasePreparation, ReleasePreparationList, Scan } from "../api/types";
import { ComparisonPanel } from "../components/ComparisonPanel";
import { PipelineSteps } from "../components/JobCard";
import { JobStatisticsCard } from "../components/JobStatisticsCard";
import { LiveStepPanel, StepTimelineCard, useJobLive } from "../components/LiveStep";
import { PlayerPanel } from "../components/PlayerPanel";
import { LanguageReviewCard, UploadReviewCard, VideoMetricsReviewCard } from "../components/ReviewPanels";
import { ReleasePanel } from "../components/ReleasePanel";
import { SelectionWizard } from "../components/SelectionWizard";
import { Badge, Button, Card, EmptyState, LoadingPanel, Modal, Notice, PageHeader, ProgressBar } from "../components/ui";
import { t } from "../i18n";
import { normalizeStoredSelection } from "../selection";
import { UPLOAD_IMAGE_SET_LABELS } from "../uploads";
import { contentLabel, formatBytes, formatDate, formatEventMessage, formatStatusMessage, formatWorkerError, humanize, isFastComparisonTimeoutReview, isRunningState, stageProgress, stateLabel, stateTone } from "../utils";

type Tab = "overview" | "settings" | "comparison" | "player" | "release" | "events" | "files";
type JobDetailLocationState = {
  newlyCreated?: boolean;
  retryStarted?: boolean;
};

interface CompletedReleaseDeleteSnapshot {
  id: string;
  version: number;
  manifest: {
    releaseName: string;
    sha256: string;
  };
  state: string;
  preparationVersions: Record<string, number>;
}

const TAB_VALUES: readonly Tab[] = ["overview", "settings", "comparison", "player", "release", "events", "files"];

function jobTabs(): Array<{ value: Tab; label: string; icon: typeof Info }> {
  return [
    { value: "overview", label: t("Áttekintés", "Overview"), icon: Gauge },
    { value: "settings", label: t("Beállítások", "Settings"), icon: Settings2 },
    { value: "comparison", label: "Comparison", icon: Images },
    { value: "player", label: t("Lejátszó", "Player"), icon: Play },
    { value: "release", label: "Release", icon: PackageCheck },
    { value: "events", label: t("Események", "Events"), icon: ClipboardList },
    { value: "files", label: t("Fájlok és logok", "Files and logs"), icon: FolderOpen },
  ];
}

const RETRYABLE_FAILED_STATES = new Set(["READY", "ENCODING", "MUXING", "QC", "COMPARISON"]);

/** The worker is executing a step of this job (a paused job keeps its state). */
function workerRunning(job: Job | undefined): boolean {
  return job !== undefined && isRunningState(job.state) && job.control_state !== "PAUSED";
}

function fallbackOperations(job: Job): string[] {
  if (job.state === "COMPLETED") return ["delete"];
  if (job.state === "FAILED") return ["retry_failed", "delete"];
  if (job.state === "CANCELLED") return ["restart_cancelled", "delete"];
  if (!job.control_state) return [];
  if (job.control_state === "PAUSED") return ["resume", "cancel"];
  if (job.control_state === "PAUSE_REQUESTED") return ["cancel"];
  if (job.control_state === "CANCEL_REQUESTED") return [];
  return ["pause", "cancel"];
}

function operationsFor(job: Job): Set<string> {
  const operations = Array.isArray(job.allowed_operations)
    ? job.allowed_operations.filter((operation): operation is string => typeof operation === "string")
    : fallbackOperations(job);
  return new Set(operations);
}

function controlStatus(job: Job): { label: string; message: string; tone: "neutral" | "info" | "success" | "warning" | "danger" } {
  if (job.control_state === "PAUSED") return { label: t("Szüneteltetve", "Paused"), message: job.control_message || t("A munka biztonságos ponton vár a folytatásra.", "The job waits at a safe point to be resumed."), tone: "warning" };
  if (job.control_state === "PAUSE_REQUESTED") return { label: t("Szüneteltetés folyamatban", "Pausing"), message: job.control_message || t("A worker a következő biztonságos ponton állítja meg a munkát.", "The worker stops the job at the next safe point."), tone: "warning" };
  if (job.control_state === "CANCEL_REQUESTED") return { label: t("Megszakítás folyamatban", "Cancelling"), message: job.control_message || t("A worker rendezetten lezárja a futó folyamatot.", "The worker shuts the running process down cleanly."), tone: "danger" };
  return { label: stateLabel(job.state), message: formatStatusMessage(job.status_message, t("Állapotfrissítésre vár", "Waiting for a status update")), tone: stateTone(job.state) };
}

function latestSuccessfulScan(scans: Scan[]): Scan | undefined {
  return scans.find((scan) => ["AWAITING_SELECTION", "COMPLETED"].includes(scan.status));
}

function imageUploadLabel(value: string | null): string {
  if (value === "imgbb") return t("Csak ImgBB", "ImgBB only");
  if (value === "catbox") return t("Csak Catbox", "Catbox only");
  if (value === "freeimage") return t("Csak Freeimage", "Freeimage only");
  return t("Automatikus tartalékkal", "Automatic with fallback");
}

function releasePreparationsFrom(
  value: ReleasePreparationList | ReleasePreparation[] | undefined,
): ReleasePreparation[] {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  if (Array.isArray(value.items)) return value.items;
  return Array.isArray(value.preparations) ? value.preparations : [];
}

function releasePreparationVersions(
  value: ReleasePreparationList | ReleasePreparation[] | undefined,
): Record<string, number> {
  const entries = releasePreparationsFrom(value).flatMap((preparation) => {
    const id = typeof preparation.id === "string"
      ? preparation.id
      : typeof preparation.preparation_id === "string"
        ? preparation.preparation_id
        : null;
    return id && typeof preparation.version === "number" ? [[id, preparation.version] as const] : [];
  });
  return Object.fromEntries(entries.sort(([left], [right]) => left.localeCompare(right)));
}

function completedReleaseDeleteSnapshot(
  job: Job | undefined,
  output: Artifact | undefined,
  preparations: ReleasePreparationList | ReleasePreparation[] | undefined,
): CompletedReleaseDeleteSnapshot | null {
  if (!job || job.state !== "COMPLETED" || !output?.sha256 || preparations === undefined) return null;
  const filename = output.name || output.path.split(/[\\/]/).at(-1) || job.name;
  return {
    id: job.id,
    version: job.version,
    manifest: {
      releaseName: filename.replace(/\.mkv$/i, ""),
      sha256: output.sha256,
    },
    state: job.state,
    preparationVersions: releasePreparationVersions(preparations),
  };
}

export function JobDetailPage() {
  const { jobId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const locationState = location.state as JobDetailLocationState | null;
  const requestedParams = new URLSearchParams(location.search);
  const requestedTab = requestedParams.get("tab") as Tab | null;
  const requestedAction = requestedParams.get("action");
  const [tab, setTab] = useState<Tab>(requestedTab && TAB_VALUES.includes(requestedTab) ? requestedTab : "overview");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [retryOpen, setRetryOpen] = useState(false);
  const [restartOpen, setRestartOpen] = useState(false);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [releaseDeleteTarget, setReleaseDeleteTarget] = useState<CompletedReleaseDeleteSnapshot | null>(null);
  const [purgeConfirmation, setPurgeConfirmation] = useState("");
  const [releaseDeleteConfirmation, setReleaseDeleteConfirmation] = useState("");
  const [forceSeededReleaseDelete, setForceSeededReleaseDelete] = useState(false);
  const operationMenuRef = useRef<HTMLDetailsElement>(null);
  const requestedReleaseDeleteHandled = useRef(false);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const queryClient = useQueryClient();
  const jobQuery = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId), refetchInterval: 4000 });
  const scansQuery = useQuery({ queryKey: ["scans", jobId], queryFn: () => api.scans(jobId), refetchInterval: 5000 });
  const artifactsQuery = useQuery({ queryKey: ["artifacts", jobId], queryFn: () => api.artifacts(jobId), refetchInterval: 7000 });
  const eventsQuery = useQuery({ queryKey: ["events", jobId], queryFn: () => api.events(jobId), refetchInterval: 4000 });
  const storageQuery = useQuery({ queryKey: ["job-storage", jobId], queryFn: () => api.jobStorage(jobId), refetchInterval: 15_000, retry: false });
  const running = workerRunning(jobQuery.data);
  const liveQuery = useJobLive(jobId, running);
  const awaitsOperator = jobQuery.data?.state === "NEEDS_REVIEW" || jobQuery.data?.state === "UPLOAD_FAILED";
  const reviewQuery = useQuery({
    queryKey: ["job-review", jobId, jobQuery.data?.version],
    queryFn: () => api.jobReview(jobId),
    enabled: awaitsOperator,
    retry: false,
  });
  const reviewKind = awaitsOperator ? reviewQuery.data?.kind ?? null : null;
  const uploadReview = reviewKind === "upload" || reviewKind === "upload_failed";
  const runtimeQuery = useQuery({
    queryKey: ["runtime-capabilities"],
    queryFn: api.runtimeCapabilities,
    staleTime: 60_000,
    enabled: uploadReview,
    retry: false,
  });
  const releasePreparationsQuery = useQuery({
    queryKey: ["release-preparations", jobId],
    queryFn: () => api.releasePreparations(jobId),
    enabled: jobQuery.data?.state === "COMPLETED",
    refetchInterval: 10_000,
  });
  const outputArtifact = artifactsQuery.data?.items.find((artifact) => artifact.kind === "OUTPUT");

  useEffect(() => {
    if (requestedAction !== "delete-release" || requestedReleaseDeleteHandled.current) return;
    const snapshot = completedReleaseDeleteSnapshot(
      jobQuery.data,
      outputArtifact,
      releasePreparationsQuery.data,
    );
    if (!snapshot) return;
    requestedReleaseDeleteHandled.current = true;
    setReleaseDeleteTarget(snapshot);
  }, [jobQuery.data, outputArtifact, releasePreparationsQuery.data, requestedAction]);
  const control = useMutation({
    mutationFn: ({ action, revision }: { action: Extract<JobOperation, "pause" | "resume" | "cancel">; revision?: number }) => {
      if (action === "pause") return api.pauseJob(jobId, revision);
      if (action === "resume") return api.continueJob(jobId, revision);
      return api.requestCancelJob(jobId, revision);
    },
    onSuccess: (updatedJob, variables) => {
      if (variables.action === "cancel") setCancelOpen(false);
      queryClient.setQueryData(["job", jobId], updatedJob);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["events", jobId] }),
      ]);
    },
  });
  const retryUpload = useMutation({
    mutationFn: () => api.retryUpload(jobId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
  });
  const retryJob = useMutation({
    mutationFn: (expectedVersion: number) => api.retryJob(jobId, expectedVersion),
    onSuccess: (retriedJob) => {
      setRetryOpen(false);
      queryClient.setQueryData(["job", jobId], retriedJob);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["events", jobId] }),
      ]);
      navigate(`/jobs/${encodeURIComponent(jobId)}`, {
        replace: true,
        state: { retryStarted: true } satisfies JobDetailLocationState,
      });
    },
  });
  const restartJob = useMutation({
    mutationFn: ({ expectedVersion, reconfigure }: { expectedVersion: number; reconfigure: boolean }) =>
      api.restartJob(jobId, expectedVersion, reconfigure),
    onSuccess: (restartedJob, { reconfigure }) => {
      setRestartOpen(false);
      queryClient.setQueryData(["job", jobId], restartedJob);
      // Reopened for changes: straight to the prefilled selection wizard.
      if (reconfigure && restartedJob.state === "AWAITING_SELECTION") setTab("settings");
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["events", jobId] }),
      ]);
      navigate(`/jobs/${encodeURIComponent(jobId)}`, {
        replace: true,
        state: { retryStarted: true } satisfies JobDetailLocationState,
      });
    },
  });
  const purgeJob = useMutation({
    mutationFn: (expectedVersion: number) => api.purgeJob(jobId, expectedVersion),
    onSuccess: () => {
      setPurgeOpen(false);
      queryClient.removeQueries({ queryKey: ["job", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate("/archive", { replace: true });
    },
  });
  const cleanupJob = useMutation({
    mutationFn: (expectedVersion: number) => api.cleanupJob(jobId, expectedVersion),
    onSuccess: () => {
      setCleanupOpen(false);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-storage", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["events", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["artifacts", jobId] }),
      ]);
    },
  });
  const deleteRelease = useMutation({
    mutationFn: (request: { confirmation: string; expected_sha256: string; force_if_seeded: boolean; preparation_versions: Record<string, number> }) => api.deleteJobRelease(jobId, request),
    onSuccess: () => {
      setReleaseDeleteTarget(null);
      setReleaseDeleteConfirmation("");
      setForceSeededReleaseDelete(false);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-storage", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["artifacts", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["release-preparations", jobId] }),
      ]);
    },
  });
  const resumeComparison = useMutation({
    mutationFn: () => api.resumeJob(jobId),
    onSuccess: (resumedJob) => {
      queryClient.setQueryData(["job", jobId], resumedJob);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["events", jobId] }),
      ]);
      navigate(`/jobs/${encodeURIComponent(jobId)}`, {
        replace: true,
        state: { retryStarted: true } satisfies JobDetailLocationState,
      });
    },
  });

  function openRetryConfirmation() {
    retryJob.reset();
    setRetryOpen(true);
  }

  function closeRetryConfirmation() {
    if (retryJob.isPending) return;
    retryJob.reset();
    setRetryOpen(false);
  }

  if (jobQuery.isLoading) return <div className="page"><LoadingPanel label={t("Munka betöltése…", "Loading job…")} /></div>;
  if (jobQuery.isError || !jobQuery.data) return (
    <div className="page"><Notice tone="danger" title={t("A munka nem nyitható meg", "The job cannot be opened")}>{jobQuery.error instanceof Error ? jobQuery.error.message : t("Ismeretlen hiba", "Unknown error")}</Notice><Link className="button button--secondary" to="/queue"><ArrowLeft size={17} /> {t("Vissza", "Back")}</Link></div>
  );

  const job = jobQuery.data;
  const visibleTabs = jobTabs().filter((item) => item.value !== "player" || job.state === "COMPLETED");
  const scanRow = latestSuccessfulScan(scansQuery.data?.items ?? []);
  const scan = scanRow?.result && "playlists" in scanRow.result ? scanRow.result as DiscScanResult : null;
  const artifacts = artifactsQuery.data?.items ?? [];
  const events = eventsQuery.data?.items ?? [];
  const latestWorkspaceEvent = [...events].reverse().find((event) => ["job.workspace-cleaned", "job.workspace-cleanup-warning"].includes(event.kind));
  const workspaceCleaned = latestWorkspaceEvent?.kind === "job.workspace-cleaned";
  const workspaceCleanupWarning = latestWorkspaceEvent?.kind === "job.workspace-cleanup-warning";
  const allowedOperations = operationsFor(job);
  const currentControlStatus = controlStatus(job);
  const controlRevision = job.control_revision;
  const retryableFailure = job.state === "FAILED"
    && job.resume_state !== null
    && RETRYABLE_FAILED_STATES.has(job.resume_state)
    && allowedOperations.has("retry_failed");
  const comparisonTimeoutReview = job.state === "NEEDS_REVIEW"
    && job.resume_state === "COMPARISON"
    && isFastComparisonTimeoutReview(job.status_message);
  // An upload problem is solved on the review card: a revised selection would
  // send the finished encode back to the queue.
  const configurable = ["AWAITING_SELECTION", "NEEDS_REVIEW"].includes(job.state)
    && !comparisonTimeoutReview
    && !uploadReview
    && scan;
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(job.state);
  const canCleanup = allowedOperations.has("cleanup")
    && (storageQuery.data?.cleanup_allowed ?? (storageQuery.data?.reclaimable_bytes ?? 0) > 0);
  const releasePresent = storageQuery.data?.release_present
    ?? ((storageQuery.data?.completed_release_bytes ?? 0) > 0);
  const canDeleteRelease = job.state === "COMPLETED" && releasePresent;
  const completedOutput = artifacts.find((artifact) => artifact.kind === "OUTPUT");
  const completedOutputSha256 = completedOutput?.sha256 ?? "";
  const releaseName = (completedOutput?.name || completedOutput?.path.split(/[\\/]/).at(-1) || job.output_path?.split(/[\\/]/).at(-1) || job.name).replace(/\.mkv$/i, "");

  function openCompletedReleaseDelete() {
    const snapshot = completedReleaseDeleteSnapshot(job, completedOutput, releasePreparationsQuery.data);
    if (!snapshot) return;
    deleteRelease.reset();
    setReleaseDeleteConfirmation("");
    setForceSeededReleaseDelete(false);
    setReleaseDeleteTarget(snapshot);
  }

  return (
    <div className="page page--job-detail">
      <Link className="back-link" to={terminal ? "/archive" : "/queue"}><ArrowLeft size={16} /> {terminal ? t("Vissza az archívumhoz", "Back to the archive") : t("Vissza a várólistához", "Back to the queue")}</Link>
      <PageHeader
        eyebrow={`${contentLabel(job.content_type)} · ${job.disc_type}`}
        title={job.name}
        description={currentControlStatus.message}
        actions={
          <div className="header-actions">
            <Badge tone={currentControlStatus.tone}>{currentControlStatus.label}</Badge>
            {allowedOperations.has("resume") && <Button icon={<Play size={17} />} loading={control.isPending && control.variables?.action === "resume"} disabled={control.isPending} onClick={() => control.mutate({ action: "resume", revision: controlRevision })}>{t("Folytatás", "Resume")}</Button>}
            {allowedOperations.has("pause") && <Button icon={<Pause size={17} />} loading={control.isPending && control.variables?.action === "pause"} disabled={control.isPending} onClick={() => control.mutate({ action: "pause", revision: controlRevision })}>{t("Szüneteltetés", "Pause")}</Button>}
            {(allowedOperations.size > (allowedOperations.has("pause") || allowedOperations.has("resume") ? 1 : 0) || job.state === "UPLOAD_FAILED" || canDeleteRelease) && (
              <details ref={operationMenuRef} className="action-menu">
                <summary className="button button--secondary"><MoreHorizontal size={17} /><span>{t("Műveletek", "Actions")}</span></summary>
                <div className="action-menu__popover" aria-label={t("Munka műveletei", "Job actions")}>
                  {retryableFailure && <button type="button" onClick={() => { operationMenuRef.current?.removeAttribute("open"); openRetryConfirmation(); }}><RotateCcw size={16} />{t("Folytatás a hibától", "Continue from the error")}</button>}
                  {allowedOperations.has("restart_cancelled") && <button type="button" onClick={() => { operationMenuRef.current?.removeAttribute("open"); restartJob.reset(); setRestartOpen(true); }}><RotateCcw size={16} />{t("Újraindítás", "Restart")}</button>}
                  {job.state === "UPLOAD_FAILED" && <button type="button" disabled={retryUpload.isPending} onClick={() => { operationMenuRef.current?.removeAttribute("open"); retryUpload.mutate(); }}><RefreshCw size={16} />{t("Feltöltés újra", "Retry upload")}</button>}
                  {allowedOperations.has("prepare_release") && <button type="button" onClick={() => { operationMenuRef.current?.removeAttribute("open"); setTab("release"); }}><PackageCheck size={16} />{t("Release előkészítése", "Prepare release")}</button>}
                  {canCleanup && <button type="button" onClick={() => { operationMenuRef.current?.removeAttribute("open"); cleanupJob.reset(); setCleanupOpen(true); }}><HardDrive size={16} />{t("Ideiglenes fájlok takarítása", "Clean up temporary files")}</button>}
                  {allowedOperations.has("cancel") && <button className="action-menu__danger" type="button" onClick={() => { operationMenuRef.current?.removeAttribute("open"); control.reset(); setCancelOpen(true); }}><StopCircle size={16} />{t("Megszakítás kérése", "Request cancel")}</button>}
                  {allowedOperations.has("delete") && <button className="action-menu__danger" type="button" onClick={() => { operationMenuRef.current?.removeAttribute("open"); purgeJob.reset(); setPurgeConfirmation(""); setPurgeOpen(true); }}><Trash2 size={16} />{t("Munka törlése", "Delete job")}</button>}
                  {allowedOperations.has("delete_release") && canDeleteRelease && <button className="action-menu__danger" type="button" disabled={!completedOutputSha256 || releasePreparationsQuery.data === undefined} onClick={() => { operationMenuRef.current?.removeAttribute("open"); openCompletedReleaseDelete(); }}><Trash2 size={16} />{t("Completed release törlése", "Delete completed release")}</button>}
                </div>
              </details>
            )}
          </div>
        }
      />

      {control.isError && <Notice tone="danger" title={t("A vezérlési kérés sikertelen", "The control request failed")}>{control.error instanceof ApiError ? control.error.detail : control.error.message}</Notice>}
      {job.control_state === "PAUSE_REQUESTED" && <Notice tone="warning" title={t("A szüneteltetés kérése rögzítve", "Pause request recorded")}>{t("A worker a futó eszközt biztonságosan lezárja. A félkész szakasz folytatáskor újraindulhat.", "The worker closes the running tool safely. The half-done stage may start again on resume.")}</Notice>}
      {job.control_state === "PAUSED" && <Notice tone="info" title={t("A munka szünetel", "The job is paused")}>{t("Az ellenőrzött checkpointok és munkafájlok megmaradtak. A Folytatás visszaadja a munkát a workernek.", "The verified checkpoints and work files are kept. Resume hands the job back to the worker.")}</Notice>}
      {job.control_state === "CANCEL_REQUESTED" && <Notice tone="warning" title={t("Rendezett megszakítás folyamatban", "Clean cancel in progress")}>{t("A job csak a futó folyamat lezárása után kerül Megszakítva állapotba.", "The job becomes Cancelled only after the running process has closed.")}</Notice>}

      {locationState?.newlyCreated && job.state === "QUEUED" && (
        <Notice tone="success" title={t("A munka létrejött", "The job was created")}>{t("A worker hamarosan elkezdi a lemez scanjét. Ezután itt választhatod ki a playlistet és a sávokat.", "The worker will scan the disc shortly. Then you can choose the playlist and the tracks here.")}</Notice>
      )}
      {locationState?.retryStarted && !terminal && (
        <Notice tone="success" title={t("A munka folytatása elindult", "The job has resumed")}>{t("A worker az ellenőrzött checkpointok alapján folytatja a feldolgozást.", "The worker continues from the verified checkpoints.")}</Notice>
      )}
      {job.error && <Notice tone="danger" title={t("A feldolgozás hibát jelzett", "Processing reported an error")}><p>{formatWorkerError(job.error)}</p><details><summary>{t("Technikai részletek", "Technical details")}</summary><pre>{job.error}</pre></details></Notice>}
      {retryableFailure && (
        <Notice tone="warning" title={t("A munkafájlok a biztonságos folytatáshoz megmaradtak", "The work files are kept for a safe resume")}>
          {t("A takarítás szándékosan vár: a rendszer megőrzi az érvényes checkpointokat és az elkészült részeredményeket. Folytatáskor csak a hiányzó vagy érvénytelen szakaszok futnak újra. Sikeres véglegesítés után a nagyméretű ideiglenes ", "Clean-up waits on purpose: the valid checkpoints and finished partial results are kept. On resume only the missing or invalid stages run again. After a successful finish the large temporary ")}<code>work</code>{t(" mappa automatikusan törlődik; a logok, elemzések és comparison mellékletek megmaradnak.", " folder is deleted automatically; the logs, analyses and comparison attachments are kept.")}
        </Notice>
      )}
      {job.state === "COMPLETED" && workspaceCleaned && (
        <Notice tone="success" title={t("A kódolás lezárult és a munkaterület kitakarítva", "The encode is finished and the workspace cleaned up")}>
          {t("A végleges MKV és a kiadható comparison bizonyítékok a completed mappába kerültek. A belső logok, útvonalak és teljes manifest kizárólag a privát munka auditjában maradtak meg; a nagyméretű ideiglenes fájlok törlődtek.", "The final MKV and the publishable comparison evidence went to the completed folder. The internal logs, paths and full manifest stay only in the job's private audit; the large temporary files were deleted.")}
        </Notice>
      )}
      {job.state === "COMPLETED" && workspaceCleanupWarning && (
        <Notice tone="warning" title={t("A kódolás elkészült, de maradtak ideiglenes fájlok", "The encode is finished, but temporary files remain")}>
          {t("A végleges MKV biztonságban van. A munkaterület takarítása nem sikerült; a részletek az eseménynaplóban találhatók.", "The final MKV is safe. Cleaning up the workspace failed; the details are in the event log.")}
        </Notice>
      )}
      {comparisonTimeoutReview && (
        <Notice tone="warning" title={t("A gyors comparison időkorlátja lejárt", "The fast comparison timed out")}>
          <p>{formatStatusMessage(job.status_message, t("A comparison biztonságosan folytatható.", "The comparison can be resumed safely."))}</p>
          <p>{t("A már elkészült képpárok és ellenőrzött checkpointok megmaradtak; a kódolást és a muxot nem kell újrafuttatni.", "The finished image pairs and verified checkpoints are kept; the encode and the mux do not need to run again.")}</p>
          <Button icon={<RefreshCw size={17} />} loading={resumeComparison.isPending} onClick={() => resumeComparison.mutate()}>{t("Folytatás a comparisontól", "Continue from the comparison")}</Button>
          {resumeComparison.isError && <p>{resumeComparison.error instanceof ApiError ? resumeComparison.error.detail : resumeComparison.error.message}</p>}
        </Notice>
      )}
      {retryUpload.isError && <Notice tone="danger" title={t("A feltöltés nem indítható újra", "The upload cannot be restarted")}>{retryUpload.error instanceof ApiError ? retryUpload.error.detail : retryUpload.error.message}</Notice>}
      {reviewKind === "language" && reviewQuery.data?.language && <LanguageReviewCard key={`language-${job.version}`} job={job} review={reviewQuery.data} />}
      {reviewKind === "video_metrics" && reviewQuery.data?.video_metrics && <VideoMetricsReviewCard key={`metrics-${job.version}`} job={job} review={reviewQuery.data} />}
      {uploadReview && reviewQuery.data && <UploadReviewCard key={`upload-${job.version}`} job={job} review={reviewQuery.data} credentials={runtimeQuery.data?.image_upload_credentials} />}
      {job.state === "NEEDS_REVIEW" && !comparisonTimeoutReview && reviewKind !== "language" && reviewKind !== "video_metrics" && !uploadReview && <Notice tone="warning" title={t("Operátori ellenőrzés szükséges", "Operator review needed")}>{formatStatusMessage(job.status_message, t("A munkafolyamat csak a beállítások felülvizsgálata után folytatható.", "The workflow can continue only after the settings are reviewed."))}</Notice>}

      <Card className="job-progress-card">
        <div className="job-progress-card__top">
          <div><span className="job-progress-card__disc"><Disc3 size={23} /></span><div><strong>{currentControlStatus.label}</strong><span>{currentControlStatus.message}</span>{job.control_requested_at && job.control_state !== "RUNNING" && <small>{t("Kérés ideje", "Requested at")}: {formatDate(job.control_requested_at)}</small>}</div></div>
          <div className="job-progress-card__percent"><strong>{Math.round(stageProgress(job) * 100)}%</strong><small>{t("teljes folyamat", "overall")}</small></div>
        </div>
        <ProgressBar value={stageProgress(job)} label={`${Math.round(stageProgress(job) * 100)}% · ${currentControlStatus.label}`} />
        {running && liveQuery.data?.step && <LiveStepPanel live={liveQuery.data} />}
        <PipelineSteps job={job} />
      </Card>

      <StorageCard
        report={storageQuery.data}
        loading={storageQuery.isLoading}
        error={storageQuery.isError ? storageQuery.error : null}
        canCleanup={canCleanup}
        cleanupPending={cleanupJob.isPending}
        onCleanup={() => { cleanupJob.reset(); setCleanupOpen(true); }}
        onRefresh={() => void storageQuery.refetch()}
      />

      <div className="tabs" role="tablist">
        {visibleTabs.map(({ value, label, icon: Icon }, index) => (
          <button
            ref={(element) => { tabRefs.current[index] = element; }}
            id={`job-tab-${value}`}
            key={value}
            role="tab"
            aria-selected={tab === value}
            aria-controls={`job-panel-${value}`}
            tabIndex={tab === value ? 0 : -1}
            className={tab === value ? "tab tab--active" : "tab"}
            onClick={() => setTab(value)}
            onKeyDown={(event) => {
              let next = index;
              if (event.key === "ArrowRight") next = (index + 1) % visibleTabs.length;
              else if (event.key === "ArrowLeft") next = (index - 1 + visibleTabs.length) % visibleTabs.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = visibleTabs.length - 1;
              else return;
              event.preventDefault();
              setTab(visibleTabs[next].value);
              tabRefs.current[next]?.focus();
            }}
          >
            <Icon size={17} />{label}
            {value === "files" && artifacts.length > 0 && <span>{artifacts.length}</span>}
          </button>
        ))}
      </div>

      <div id={`job-panel-${tab}`} className="tab-panel" role="tabpanel" aria-labelledby={`job-tab-${tab}`}>
        {tab === "overview" && (
          <Overview job={job} scan={scan} events={events} artifacts={artifacts} live={liveQuery.data} running={running} reviewCardShown={reviewKind === "language" || uploadReview} onConfigure={() => setTab("settings")} />
        )}
        {tab === "settings" && (
          configurable ? (
            <SelectionWizard job={job} scan={scan} onComplete={() => setTab("overview")} />
          ) : job.selection ? (
            <SavedSelection job={job} scan={scan} />
          ) : (
            <EmptyState icon={job.state === "SCANNING" ? <LoaderCircle className="spin" size={28} /> : <Settings2 size={28} />} title={job.state === "SCANNING" ? t("A scan folyamatban van", "The scan is in progress") : t("Még nincs jóváhagyott beállítás", "No approved settings yet")} description={t("A playlist- és sávválasztó a scan befejezése után jelenik meg.", "The playlist and track picker appears once the scan is finished.")} />
          )
        )}
        {tab === "comparison" && <ComparisonPanel artifacts={artifacts} />}
        {tab === "player" && job.state === "COMPLETED" && <PlayerPanel jobId={job.id} />}
        {tab === "release" && <ReleasePanel job={job} outputArtifact={completedOutput} />}
        {tab === "events" && <EventTimeline events={events} loading={eventsQuery.isLoading} />}
        {tab === "files" && <ArtifactsPanel artifacts={artifacts} />}
      </div>

      <Modal
        open={cancelOpen}
        title={t("Biztosan megszakítod?", "Cancel this job?")}
        busy={control.isPending}
        ariaDescribedBy="cancel-job-description"
        onClose={() => { if (!control.isPending) setCancelOpen(false); }}
        footer={<><Button variant="ghost" disabled={control.isPending} onClick={() => setCancelOpen(false)}>{t("Mégse", "Close")}</Button><Button variant="danger" icon={<StopCircle size={17} />} loading={control.isPending} onClick={() => control.mutate({ action: "cancel", revision: controlRevision })}>{t("Megszakítás kérése", "Request cancel")}</Button></>}
      >
        <div id="cancel-job-description"><Notice tone="warning">{t("A worker rendezetten lezárja a futó programot; a job csak ezután lesz Megszakítva. A már elkészült munkafájlok és naplók megmaradnak.", "The worker shuts the running program down cleanly; only then is the job Cancelled. The finished work files and logs are kept.")}</Notice></div>
        {control.isError && <Notice tone="danger">{control.error instanceof ApiError ? control.error.detail : control.error.message}</Notice>}
      </Modal>

      <Modal
        open={retryOpen}
        title={t("Folytatod a hibától?", "Continue from the error?")}
        busy={retryJob.isPending}
        onClose={closeRetryConfirmation}
        footer={<><Button variant="ghost" disabled={retryJob.isPending} onClick={closeRetryConfirmation}>{t("Mégse", "Cancel")}</Button><Button icon={<RotateCcw size={17} />} loading={retryJob.isPending} onClick={() => retryJob.mutate(job.version)}>{t("Folytatás a hibától", "Continue from the error")}</Button></>}
      >
        <Notice tone="warning" title={t("A kész munka nem vész el", "Finished work is not lost")}>
          {t("Az újraindítás az érvényes szakasz-checkpointokat és a már elkészült munkafájlokat újrahasználja. A worker az első hiányzó vagy érvénytelen szakasztól folytatja, a hibás szakaszt pedig szükség szerint újrafuttatja.", "The restart reuses the valid stage checkpoints and the finished work files. The worker continues from the first missing or invalid stage and reruns the failed stage as needed.")}
        </Notice>
        {retryJob.isError && <Notice tone="danger" title={t("A folytatás nem indítható", "Cannot continue")}>{retryJob.error instanceof ApiError ? retryJob.error.detail : retryJob.error.message}</Notice>}
      </Modal>

      <Modal
        open={restartOpen}
        title={t("Újraindítod a megszakított munkát?", "Restart the cancelled job?")}
        busy={restartJob.isPending}
        onClose={() => { if (!restartJob.isPending) setRestartOpen(false); }}
        footer={<>
          <Button variant="ghost" disabled={restartJob.isPending} onClick={() => setRestartOpen(false)}>{t("Mégse", "Cancel")}</Button>
          {job.selection && <Button variant="secondary" icon={<Settings2 size={17} />} disabled={restartJob.isPending} onClick={() => restartJob.mutate({ expectedVersion: job.version, reconfigure: true })}>{t("Beállítások módosítása", "Change settings")}</Button>}
          <Button icon={<RotateCcw size={17} />} loading={restartJob.isPending} onClick={() => restartJob.mutate({ expectedVersion: job.version, reconfigure: false })}>{job.selection ? t("Újraindítás ugyanígy", "Restart unchanged") : t("Újraindítás", "Restart")}</Button>
        </>}
      >
        {job.selection ? (
          <Notice tone="info" title={t("Ugyanígy vagy módosított beállításokkal", "Unchanged or with changed settings")}>
            <strong>{t("Újraindítás ugyanígy:", "Restart unchanged:")}</strong>{t(" a munka a jóváhagyott beállításokkal visszakerül a várólistára. ", " the job goes back to the queue with the approved settings. ")}<strong>{t("Beállítások módosítása:", "Change settings:")}</strong>{t(" a beállítóvarázsló nyílik meg a korábbi beállításokkal kitöltve; a kódolás csak az új beállítások jóváhagyása után indul. Mindkét esetben megmarad, amit a változás nem érint (remux, crop, forrás-ellenőrzés); amit érint, az újrafut.", " the setup wizard opens filled in with the earlier settings; the encode starts only after the new settings are approved. Either way, whatever the change does not affect is kept (remux, crop, source check); whatever it affects runs again.")}
          </Notice>
        ) : (
          <Notice tone="info" title={t("A korábbi eredmények megmaradnak", "Earlier results are kept")}>
            {t("Ha a scan már elkészült, a munka a beállítóvarázslóhoz kerül vissza. Korábbi megszakításnál a scan indul újra.", "If the scan was finished, the job goes back to the setup wizard. If it was cancelled earlier, the scan starts again.")}
          </Notice>
        )}
        {restartJob.isError && <Notice tone="danger" title={t("A munka nem indítható újra", "The job cannot be restarted")}>{restartJob.error instanceof ApiError ? restartJob.error.detail : restartJob.error.message}</Notice>}
      </Modal>

      <Modal
        open={purgeOpen}
        title={t("Végleg törlöd ezt a munkát?", "Delete this job permanently?")}
        busy={purgeJob.isPending}
        ariaDescribedBy="purge-job-description"
        onClose={() => { if (!purgeJob.isPending) setPurgeOpen(false); }}
        footer={<><Button variant="ghost" disabled={purgeJob.isPending} onClick={() => setPurgeOpen(false)}>{t("Mégse", "Cancel")}</Button><Button variant="danger" icon={<Trash2 size={17} />} loading={purgeJob.isPending} disabled={purgeConfirmation !== job.name} onClick={() => purgeJob.mutate(job.version)}>{t("Munka végleges törlése", "Delete job permanently")}</Button></>}
      >
        <div id="purge-job-description"><Notice tone="danger" title={t("Ez nem vonható vissza", "This cannot be undone")}>{t("A privát jobrekord, munkafájlok, checkpointok, logok és mellékletek törlődnek. A forráslemezhez és a completed release-hez a rendszer nem nyúl.", "The private job record, work files, checkpoints, logs and attachments are deleted. The source disc and the completed release are not touched.")}</Notice></div>
        <label className="field confirmation-field">{t("A megerősítéshez írd be a munka nevét:", "Type the job name to confirm:")}<input autoComplete="off" value={purgeConfirmation} onChange={(event) => setPurgeConfirmation(event.target.value)} /><small><code>{job.name}</code></small></label>
        {purgeJob.isError && <Notice tone="danger" title={t("A munka nem törölhető", "The job cannot be deleted")}>{purgeJob.error instanceof ApiError ? purgeJob.error.detail : purgeJob.error.message}</Notice>}
      </Modal>

      <Modal
        open={cleanupOpen}
        title={t("Kitakarítod az ideiglenes fájlokat?", "Clean up the temporary files?")}
        busy={cleanupJob.isPending}
        ariaDescribedBy="cleanup-job-description"
        onClose={() => { if (!cleanupJob.isPending) setCleanupOpen(false); }}
        footer={<><Button variant="ghost" disabled={cleanupJob.isPending} onClick={() => setCleanupOpen(false)}>{t("Mégse", "Cancel")}</Button><Button icon={<HardDrive size={17} />} loading={cleanupJob.isPending} disabled={(storageQuery.data?.reclaimable_bytes ?? 0) <= 0} onClick={() => cleanupJob.mutate(job.version)}>{t("Takarítás", "Clean up")}</Button></>}
      >
        <div id="cleanup-job-description"><Notice tone="info" title={t(`${formatBytes(storageQuery.data?.reclaimable_bytes)} szabadítható fel`, `${formatBytes(storageQuery.data?.reclaimable_bytes)} can be freed`)}>{t("Csak a sikeresen lezárt munka nagyméretű ideiglenes ", "Only the large temporary ")}<code>work</code>{t(" tartalma törlődik. A jobrekord, logok, audit, comparison és completed release megmarad.", " contents of a successfully closed job are deleted. The job record, logs, audit, comparison and completed release are kept.")}</Notice></div>
        {cleanupJob.isError && <Notice tone="danger" title={t("A takarítás sikertelen", "Clean-up failed")}>{cleanupJob.error instanceof ApiError ? cleanupJob.error.detail : cleanupJob.error.message}</Notice>}
      </Modal>

      <Modal
        open={releaseDeleteTarget !== null}
        title={t("Végleg törlöd a completed release-t?", "Delete the completed release permanently?")}
        busy={deleteRelease.isPending}
        ariaDescribedBy="delete-release-description"
        onClose={() => { if (!deleteRelease.isPending) setReleaseDeleteTarget(null); }}
        footer={<><Button variant="ghost" disabled={deleteRelease.isPending} onClick={() => setReleaseDeleteTarget(null)}>{t("Mégse", "Cancel")}</Button><Button variant="danger" icon={<Trash2 size={17} />} loading={deleteRelease.isPending} disabled={!releaseDeleteTarget || releaseDeleteConfirmation !== releaseDeleteTarget.manifest.releaseName || !canDeleteRelease} onClick={() => releaseDeleteTarget && deleteRelease.mutate({ confirmation: releaseDeleteTarget.manifest.releaseName, expected_sha256: releaseDeleteTarget.manifest.sha256, force_if_seeded: forceSeededReleaseDelete, preparation_versions: releaseDeleteTarget.preparationVersions })}>{t("Release végleges törlése", "Delete release permanently")}</Button></>}
      >
        <div id="delete-release-description"><Notice tone="danger" title={t("Ez a kész MKV-t is törli", "This also deletes the finished MKV")}>{t("A completed release teljes publikus csomagja eltűnik. A forráslemez és a privát job auditja megmarad; a korábbi release-előkészítések érvénytelenné válhatnak.", "The whole public package of the completed release is removed. The source disc and the job's private audit are kept; earlier release preparations may become invalid.")}</Notice></div>
        {releaseDeleteTarget && <dl className="summary-list summary-list--stacked"><div><dt>{t("Rögzített release", "Recorded release")}</dt><dd>{releaseDeleteTarget.manifest.releaseName}</dd></div><div><dt>{t("Állapot / job revízió", "State / job revision")}</dt><dd>{releaseDeleteTarget.state} · v{releaseDeleteTarget.version}</dd></div><div><dt>OUTPUT SHA-256</dt><dd><code>{releaseDeleteTarget.manifest.sha256}</code></dd></div><div><dt>{t("Rögzített előkészítések", "Recorded preparations")}</dt><dd><code>{JSON.stringify(releaseDeleteTarget.preparationVersions)}</code></dd></div></dl>}
        <label className="field confirmation-field">{t("A megerősítéshez írd be a release nevét:", "Type the release name to confirm:")}<input autoComplete="off" value={releaseDeleteConfirmation} onChange={(event) => setReleaseDeleteConfirmation(event.target.value)} /><small><code>{releaseDeleteTarget?.manifest.releaseName ?? releaseName}</code></small></label>
        <label className="toggle-row toggle-row--compact"><span><strong>{t("Kényszerített törlés külső vagy seedelt eredmény ellenére", "Force delete despite an external or seeded result")}</strong><small>{t("Csak akkor kapcsold be, ha a bizonytalan dupe check vagy egy 3.0 előtti qBittorrent-/trackerművelet eredményét ellenőrizted, és a külső példányokat is tudatosan kezeled.", "Turn this on only if you have checked the uncertain dupe check or the result of a pre-3.0 qBittorrent/tracker action, and you handle the external copies deliberately.")}</small></span><input type="checkbox" checked={forceSeededReleaseDelete} onChange={(event) => setForceSeededReleaseDelete(event.target.checked)} /><span className="toggle" aria-hidden="true" /></label>
        {!storageQuery.isLoading && !canDeleteRelease && <Notice tone="warning">{t("A completed release már nem található, ezért nincs törölhető cél.", "The completed release is no longer there, so there is nothing to delete.")}</Notice>}
        {!releaseDeleteTarget?.manifest.sha256 && <Notice tone="warning">{t("A törlés le van tiltva, mert a kimeneti MKV elvárt SHA-256 értéke nem érhető el.", "Deletion is blocked because the expected SHA-256 of the output MKV is not available.")}</Notice>}
        {deleteRelease.isError && <Notice tone="danger" title={t("A release nem törölhető", "The release cannot be deleted")}>{deleteRelease.error instanceof ApiError ? deleteRelease.error.detail : deleteRelease.error.message}</Notice>}
      </Modal>
    </div>
  );
}

function StorageCard({
  report,
  loading,
  error,
  canCleanup,
  cleanupPending,
  onCleanup,
  onRefresh,
}: {
  report?: JobStorageReport;
  loading: boolean;
  error: Error | null;
  canCleanup: boolean;
  cleanupPending: boolean;
  onCleanup: () => void;
  onRefresh: () => void;
}) {
  return (
    <Card className="job-storage-card">
      <div className="section-heading">
        <div><span className="section-heading__icon"><HardDrive size={19} /></span><div><h2>{t("Tárhely és takarítás", "Storage and clean-up")}</h2><p>{t("A job privát munkaterülete és a külön kezelt completed release", "The job's private workspace and the separately kept completed release")}</p></div></div>
        {report && <Badge tone={report.reclaimable_bytes > 0 ? "warning" : "success"}>{report.reclaimable_bytes > 0 ? t(`${formatBytes(report.reclaimable_bytes)} felszabadítható`, `${formatBytes(report.reclaimable_bytes)} reclaimable`) : t("Nincs maradék", "Nothing left over")}</Badge>}
      </div>
      {loading ? <LoadingPanel label={t("Tárhely számítása…", "Measuring storage…")} /> : error ? (
        <Notice tone="warning" title={t("A tárhelyadat nem olvasható", "The storage data cannot be read")}><Button variant="ghost" icon={<RefreshCw size={15} />} onClick={onRefresh}>{t("Újrapróbálás", "Retry")}</Button></Notice>
      ) : report ? (
        <>
          <div className="storage-facts">
            <div><small>{t("Privát munkaterület", "Private workspace")}</small><strong>{formatBytes(report.workspace_bytes)}</strong></div>
            <div><small>{t("Ideiglenes, törölhető", "Temporary, deletable")}</small><strong>{formatBytes(report.reclaimable_bytes)}</strong></div>
            <div><small>Completed release</small><strong>{formatBytes(report.completed_release_bytes)}</strong></div>
          </div>
          <div className="storage-category-list" aria-label={t("Munkaterület kategóriái", "Workspace categories")}>
            {report.categories.filter((item) => item.present).map((item) => <span key={item.name}><strong>{humanize(item.name)}</strong><small>{formatBytes(item.bytes)} · {item.file_count} {t("fájl", "files")}{item.reclaimable ? ` · ${t("takarítható", "can be cleaned")}` : ""}</small></span>)}
          </div>
          {canCleanup && <Button variant="secondary" icon={<HardDrive size={16} />} loading={cleanupPending} disabled={report.reclaimable_bytes <= 0} onClick={onCleanup}>{t("Ideiglenes fájlok takarítása", "Clean up temporary files")}</Button>}
        </>
      ) : null}
    </Card>
  );
}

function Overview({ job, scan, events, artifacts, live, running, reviewCardShown, onConfigure }: { job: Job; scan: DiscScanResult | null; events: EventRecord[]; artifacts: Artifact[]; live: JobLive | undefined; running: boolean; reviewCardShown: boolean; onConfigure: () => void }) {
  const newest = events.slice(-4).reverse();
  return (
    <div className="overview-grid">
      <div className="overview-main">
        {["AWAITING_SELECTION", "NEEDS_REVIEW"].includes(job.state) && !isFastComparisonTimeoutReview(job.status_message) && !reviewCardShown && scan && (
          <Card className="action-callout">
            <span className="action-callout__icon"><ListChecks size={25} /></span>
            <div><span className="eyebrow">{t("Te következel", "Your turn")}</span><h2>{job.state === "AWAITING_SELECTION" ? t("Válaszd ki a filmet és a sávokat", "Choose the film and the tracks") : t("Vizsgáld felül a beállításokat", "Review the settings")}</h2><p>{t(`${scan.playlists.length} playlistet találtam. A kódolás addig nem indul el, amíg a tervet jóvá nem hagyod.`, `Found ${scan.playlists.length} playlists. The encode does not start until you approve the plan.`)}</p></div>
            <Button icon={<Play size={17} />} onClick={onConfigure}>{t("Beállítások megnyitása", "Open settings")}</Button>
          </Card>
        )}
        <StepTimelineCard live={live} showStep={running} />
        <Card>
          <div className="section-heading"><div><span className="section-heading__icon"><ClipboardList size={19} /></span><div><h2>{t("Legutóbbi események", "Recent events")}</h2><p>{t("Sanitizált, tartós állapotnapló", "Sanitized, durable state log")}</p></div></div></div>
          {newest.length ? <div className="mini-timeline">{newest.map((event) => <EventItem key={event.id} event={event} compact />)}</div> : <p className="muted">{t("Még nincs naplózott esemény.", "No events logged yet.")}</p>}
        </Card>
      </div>
      <aside className="overview-side">
        <Card>
          <span className="eyebrow">{t("Munka adatai", "Job details")}</span>
          <dl className="summary-list summary-list--stacked">
            <div><dt>{t("Forrás", "Source")}</dt><dd title={job.source_path}>{job.source_path}</dd></div>
            <div><dt>{t("Létrehozva", "Created")}</dt><dd>{formatDate(job.created_at)}</dd></div>
            <div><dt>{t("Frissítve", "Updated")}</dt><dd>{formatDate(job.updated_at)}</dd></div>
            <div><dt>{t("Azonosító", "ID")}</dt><dd><code>{job.id}</code></dd></div>
            <div><dt>{t("Mellékletek", "Attachments")}</dt><dd>{artifacts.length}</dd></div>
          </dl>
        </Card>
        {job.state === "COMPLETED" && <JobStatisticsCard jobId={job.id} />}
        {scan && <Card><span className="eyebrow">{t("Lemez scan", "Disc scan")}</span><dl className="summary-list summary-list--stacked"><div><dt>{t("Típus", "Type")}</dt><dd>{scan.disc_kind.toUpperCase()}</dd></div><div><dt>{t("Playlistek", "Playlists")}</dt><dd>{scan.playlists.length}</dd></div><div><dt>{t("Több változat", "Multiple editions")}</dt><dd>{scan.has_multiple_editions ? t("Igen", "Yes") : t("Nem", "No")}</dd></div><div><dt>{t("3D észlelve", "3D detected")}</dt><dd>{scan.has_three_d ? t("Igen — nem támogatott", "Yes — not supported") : t("Nem", "No")}</dd></div></dl></Card>}
      </aside>
    </div>
  );
}

function SavedSelection({ job, scan }: { job: Job; scan: DiscScanResult | null }) {
  const selection = normalizeStoredSelection(job.selection);
  if (!selection) {
    return <Notice tone="warning" title={t("A mentett selection nem olvasható", "The saved selection cannot be read")}>{t("A nyers selection JSON nem objektum. A worker operátori ellenőrzést fog kérni.", "The raw selection JSON is not an object. The worker will ask for an operator review.")}</Notice>;
  }
  const settings = selection.settings;
  return (
    <div className="saved-selection">
      <Notice tone={isFastComparisonTimeoutReview(job.status_message) ? "info" : "success"} title={isFastComparisonTimeoutReview(job.status_message) ? t("A jóváhagyott terv változatlan", "The approved plan is unchanged") : t("A terv jóváhagyva", "Plan approved")}>{isFastComparisonTimeoutReview(job.status_message) ? t("A selection módosítása nem szükséges. A comparison az áttekintő lapon folytatható az érvényes checkpointoktól.", "The selection does not need changing. The comparison can be resumed on the Overview tab from the valid checkpoints.") : t("Nincs külön indítógomb: a munka kész paraméterekkel vár a sorára, majd a worker automatikusan végigviszi. A comparison adatok külön mellékletek maradnak.", "There is no separate start button: the job waits its turn with its settings ready, then the worker runs it through automatically. The comparison data stay separate attachments.")}</Notice>
      <div className="saved-selection-grid">
        <Card><span className="eyebrow">{t("Kép és kódoló", "Picture and encoder")}</span><dl className="summary-list summary-list--stacked"><div><dt>Playlist</dt><dd>{selection.playlistId ?? "—"}</dd></div><div><dt>{t("Kódoló", "Encoder")}</dt><dd>{scan?.disc_kind === "uhd" ? "x265" : "x264"}</dd></div><div><dt>{t("Részletesség", "Detail level")}</dt><dd>{selection.detailLevel ?? "—"}</dd></div><div><dt>CRF</dt><dd>{String(settings.crf ?? t("ajánlott", "recommended"))}</dd></div><div><dt>Preset</dt><dd>{String(settings.preset ?? t("ajánlott", "recommended"))}</dd></div><div><dt>Filter</dt><dd>{selection.temporalFilter ?? "—"}</dd></div></dl></Card>
        <Card><span className="eyebrow">{t("Kimenet", "Output")}</span><dl className="summary-list summary-list--stacked"><div><dt>{t("Fájlnév", "File name")}</dt><dd>{selection.outputName ? `${selection.outputName}.mkv` : "—"}</dd></div><div><dt>{t("Sávok", "Tracks")}</dt><dd>{selection.tracks.filter((track) => track.action !== "omit").length} {t("megtartva", "kept")}</dd></div><div><dt>{t("Képfeltöltés", "Image upload")}</dt><dd>{selection.uploadImages === null ? "—" : selection.uploadImages ? `${imageUploadLabel(selection.imageUploadProvider)} · ${UPLOAD_IMAGE_SET_LABELS[selection.uploadImageSet ?? "all"]}` : t("Kikapcsolva", "Off")}</dd></div><div><dt>{t("I/P/B egyezés", "I/P/B match")}</dt><dd>{selection.dualTypeMatch === false ? t("Kötelező · régi mentés felülbírálva", "Required · old saved value overridden") : t("Kötelező", "Required")}</dd></div></dl></Card>
        <Card className="saved-json"><details><summary><Code2 size={17} /> {t("Teljes selection JSON", "Full selection JSON")}</summary><pre>{JSON.stringify(job.selection, null, 2)}</pre></details></Card>
      </div>
    </div>
  );
}

function EventTimeline({ events, loading }: { events: EventRecord[]; loading: boolean }) {
  if (loading) return <LoadingPanel />;
  if (!events.length) return <EmptyState icon={<CalendarClock size={28} />} title={t("Még nincs esemény", "No events yet")} description={t("A worker állapotváltásai és biztonságos összefoglalói itt jelennek meg.", "The worker's state changes and safe summaries appear here.")} />;
  return <div className="event-timeline">{[...events].reverse().map((event) => <EventItem key={event.id} event={event} />)}</div>;
}

function EventItem({ event, compact = false }: { event: EventRecord; compact?: boolean }) {
  const isError = event.kind.toLowerCase().includes("error") || event.state_to === "FAILED" || event.state_to === "UPLOAD_FAILED";
  const isSuccess = event.state_to === "COMPLETED";
  const uploadDetail = typeof event.payload.detail === "string" ? event.payload.detail : null;
  return (
    <article className={isError ? "event-item event-item--error" : isSuccess ? "event-item event-item--success" : "event-item"}>
      <span className="event-item__marker">{isError ? <AlertTriangle size={15} /> : isSuccess ? <CheckCircle2 size={15} /> : <Info size={14} />}</span>
      <div><div className="event-item__heading"><strong>{formatEventMessage(event.kind, event.message)}</strong><time>{formatDate(event.created_at)}</time></div>{event.state_from && event.state_to && <p>{stateLabel(event.state_from)} → {stateLabel(event.state_to)}</p>}{compact && uploadDetail && <p>{uploadDetail}</p>}{!compact && Object.keys(event.payload).length > 0 && <details><summary>{t("Részletek", "Details")}</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details>}</div>
    </article>
  );
}

function ArtifactsPanel({ artifacts }: { artifacts: Artifact[] }) {
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const output = artifacts.find((artifact) => artifact.kind === "OUTPUT");
  const analyze = useMutation({ mutationFn: () => api.analyzeMkv(output!.path), onSuccess: setAnalysis });
  const groups = useMemo(() => Object.entries(artifacts.reduce<Record<string, Artifact[]>>((result, artifact) => {
    (result[artifact.kind] ??= []).push(artifact); return result;
  }, {})), [artifacts]);
  if (!artifacts.length) return <EmptyState icon={<File size={28} />} title={t("Még nincs melléklet", "No attachments yet")} description={t("A scan manifestje, logok, elemzések és comparison képek munka közben folyamatosan jelennek meg.", "The scan manifest, logs, analyses and comparison images appear as the job runs.")} />;
  return (
    <div className="artifacts-panel">
      {output && (
        <Card className="mkv-analysis-card">
          <div><span className="mkv-analysis-card__icon"><ShieldCheck size={22} /></span><span><strong>{t("Elkészült MKV elemzése", "Analyse the finished MKV")}</strong><small>{t("A konténerből kiolvassa a trackeket és a kódoló beállításait; comparison adatot nem keres az MKV-ban.", "Reads the tracks and the encoder settings from the container; it does not look for comparison data in the MKV.")}</small></span></div>
          <Button variant="secondary" icon={<RefreshCw size={16} />} loading={analyze.isPending} onClick={() => analyze.mutate()}>{t("MKV elemzése", "Analyse MKV")}</Button>
          {analyze.isError && <Notice tone="danger">{analyze.error instanceof Error ? analyze.error.message : t("Az elemzés sikertelen", "The analysis failed")}</Notice>}
          {analysis && <details className="analysis-result" open><summary>{t("Elemzési eredmény", "Analysis result")}</summary><pre>{JSON.stringify(analysis, null, 2)}</pre></details>}
        </Card>
      )}
      {groups.map(([kind, items]) => (
        <section key={kind} className="artifact-group">
          <div className="section-heading"><div><span className="section-heading__icon">{kind === "LOG" ? <FileText size={18} /> : kind.includes("COMPARISON") || kind === "SPECTROGRAM" ? <Images size={18} /> : <FileJson size={18} />}</span><div><h3>{artifactGroupLabel(kind)}</h3><p>{items.length} {t("melléklet", "attachments")}</p></div></div></div>
          <div className="artifact-list">
            {items.map((artifact) => <ArtifactRow key={artifact.id} artifact={artifact} />)}
          </div>
        </section>
      ))}
    </div>
  );
}

function ArtifactRow({ artifact }: { artifact: Artifact }) {
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const canPreview = artifact.mime_type?.startsWith("text/") || artifact.mime_type === "application/json";
  async function loadPreview() {
    if (preview !== null) { setPreview(null); return; }
    setLoading(true);
    try { setPreview(await fetchArtifactText(artifact.id)); } finally { setLoading(false); }
  }
  return (
    <div className="artifact-row">
      <span className="artifact-row__icon">{artifact.mime_type === "image/png" ? <Images size={18} /> : artifact.kind === "LOG" ? <FileText size={18} /> : <File size={18} />}</span>
      <span className="artifact-row__name"><strong>{artifact.name}</strong><small>{artifact.mime_type || artifact.kind} · {formatBytes(artifact.size_bytes)}</small></span>
      <div className="artifact-row__actions">{canPreview && <Button variant="ghost" onClick={() => void loadPreview()} loading={loading}>{t("Előnézet", "Preview")}</Button>}<a className="icon-button" href={artifactContentUrl(artifact.id)} target="_blank" rel="noreferrer" aria-label={t(`${artifact.name} letöltése`, `Download ${artifact.name}`)}><Download size={17} /></a></div>
      {preview !== null && <pre className="artifact-preview">{preview}</pre>}
    </div>
  );
}

function artifactGroupLabel(kind: string): string {
  const labels: Record<string, string> = {
    OUTPUT: t("Kimeneti fájl", "Output file"),
    LOG: t("Logok", "Logs"),
    MANIFEST: t("Manifestek", "Manifests"),
    MEDIAINFO: "MediaInfo",
    MKVINFO: t("MKV elemzések", "MKV analyses"),
    VIDEO_COMPARISON: t("Videó comparison", "Video comparison"),
    AUDIO_COMPARISON: t("Audió comparison", "Audio comparison"),
    SPECTROGRAM: t("Spektrumképek", "Spectrograms"),
    REPORT: t("Jelentések", "Reports"),
    BBCODE: "BBCode",
    OTHER: t("Egyéb", "Other"),
  };
  return labels[kind] || kind;
}
