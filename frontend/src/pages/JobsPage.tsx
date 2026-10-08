import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, CirclePlus, HardDrive, ListOrdered, Search, StopCircle, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, ApiError } from "../api/client";
import type { Job, JobState } from "../api/types";
import { JobCard } from "../components/JobCard";
import { Button, EmptyState, LoadingPanel, Modal, Notice, PageHeader } from "../components/ui";
import { locale, t } from "../i18n";

const QUEUE_STATES: JobState[] = [
  "QUEUED", "SCANNING", "AWAITING_SELECTION", "READY", "ENCODING", "MUXING", "QC", "COMPARISON", "UPLOADING", "NEEDS_REVIEW", "UPLOAD_FAILED",
];
const ARCHIVE_STATES: JobState[] = ["COMPLETED", "FAILED", "CANCELLED"];

export function JobsPage({ mode }: { mode: "queue" | "archive" }) {
  const [search, setSearch] = useState("");
  const [confirmation, setConfirmation] = useState<{ action: string; job: Job } | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const states = mode === "queue" ? QUEUE_STATES : ARCHIVE_STATES;
  const query = useQuery({
    queryKey: ["jobs", mode],
    queryFn: () => api.jobs(states, 500),
    refetchInterval: mode === "queue" ? 5000 : 15_000,
  });
  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase(locale());
    if (!needle) return query.data?.items ?? [];
    return (query.data?.items ?? []).filter((job) =>
      [job.name, job.source_path, job.state].some((value) => value.toLocaleLowerCase(locale()).includes(needle)),
    );
  }, [query.data, search]);
  const operation = useMutation({
    mutationFn: async ({ action, job }: { action: string; job: Job }) => {
      const revision = job.control_revision;
      if (action === "pause") return api.pauseJob(job.id, revision);
      if (action === "resume") return api.continueJob(job.id, revision);
      if (action === "cancel") return api.requestCancelJob(job.id, revision);
      if (action === "retry_failed") return api.retryJob(job.id, job.version);
      if (action === "restart_cancelled") return api.restartJob(job.id, job.version);
      if (action === "cleanup") return api.cleanupJob(job.id, job.version);
      if (action === "delete") return api.purgeJob(job.id, job.version);
      throw new Error(t(`Nem támogatott művelet: ${action}`, `Unsupported action: ${action}`));
    },
    onSuccess: (_result, variables) => {
      setConfirmation(null);
      setDeleteConfirmation("");
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["job", variables.job.id] }),
        queryClient.invalidateQueries({ queryKey: ["job-storage", variables.job.id] }),
      ]);
    },
  });

  function requestAction(action: string, job: Job) {
    operation.reset();
    if (action === "prepare_release") {
      navigate(`/jobs/${encodeURIComponent(job.id)}?tab=release`);
      return;
    }
    if (action === "delete_release") {
      navigate(`/jobs/${encodeURIComponent(job.id)}?action=delete-release`);
      return;
    }
    if (["cancel", "cleanup", "delete"].includes(action)) {
      setDeleteConfirmation("");
      setConfirmation({ action, job });
      return;
    }
    operation.mutate({ action, job });
  }

  const confirmationLabel = confirmation?.action === "cancel"
    ? t("Megszakítás kérése", "Request cancel")
    : confirmation?.action === "cleanup"
      ? t("Ideiglenes fájlok takarítása", "Clean up temporary files")
      : t("Munka végleges törlése", "Delete job permanently");

  return (
    <div className="page">
      <PageHeader
        eyebrow={mode === "queue" ? t("Munkafolyamat", "Workflow") : t("Előzmények", "History")}
        title={mode === "queue" ? t("Várólista", "Queue") : t("Elkészült munkák", "Finished jobs")}
        description={mode === "queue" ? t("Az új lemezek scanje és beállítása a futó encode mellett is elkészülhet. Kódolni mindig csak az első jóváhagyott munka fog; a többi kész paraméterekkel várakozik.", "New discs can be scanned and set up while an encode runs. Only the first approved job encodes; the others wait with their settings ready.") : t("Kész, hibás és megszakított kódolások visszakereshető mellékletekkel.", "Finished, failed and cancelled encodes with searchable attachments.")}
        actions={<Link className="button button--primary" to="/new"><CirclePlus size={18} /><span>{t("Új kódolás", "New encode")}</span></Link>}
      />

      <div className="toolbar">
        <label className="search-field">
          <Search size={18} aria-hidden="true" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Keresés név, útvonal vagy állapot alapján…", "Search by name, path or state…")} />
        </label>
        <span className="toolbar__count">{t(`${filtered.length} találat`, `${filtered.length} results`)}</span>
      </div>

      {query.isError && <Notice tone="danger" title={t("A munkák nem tölthetők be", "The jobs cannot be loaded")}>{t("Ellenőrizd a szerverkapcsolatot, majd próbáld újra.", "Check the server connection and try again.")}</Notice>}
      {operation.isError && !confirmation && <Notice tone="danger" title={t("A művelet sikertelen", "The action failed")}>{operation.error instanceof ApiError ? operation.error.detail : operation.error.message}</Notice>}
      {query.isLoading ? <LoadingPanel label={t("Munkák betöltése…", "Loading jobs…")} /> : filtered.length ? (
        <div className="job-grid">
          {filtered.map((job) => <JobCard key={job.id} job={job} onAction={requestAction} pendingAction={operation.isPending && operation.variables?.job.id === job.id ? operation.variables.action : null} />)}
        </div>
      ) : (
        <EmptyState
          icon={mode === "queue" ? <ListOrdered size={28} /> : <Archive size={28} />}
          title={search ? t("Nincs ilyen munka", "No such job") : mode === "queue" ? t("A várólista üres", "The queue is empty") : t("Az archívum még üres", "The archive is empty")}
          description={search ? t("Próbálj más keresőkifejezést.", "Try another search term.") : mode === "queue" ? t("Az első forrás hozzáadásával itt jelenik meg a munkafolyamat.", "Add the first source and the workflow appears here.") : t("A lezárt kódolások automatikusan ide kerülnek.", "Closed encodes land here automatically.")}
          action={!search && mode === "queue" ? <Link className="button button--secondary" to="/new">{t("Első munka hozzáadása", "Add the first job")}</Link> : undefined}
        />
      )}

      <Modal
        open={Boolean(confirmation)}
        title={confirmationLabel}
        busy={operation.isPending}
        onClose={() => { if (!operation.isPending) setConfirmation(null); }}
        footer={<><Button variant="ghost" disabled={operation.isPending} onClick={() => setConfirmation(null)}>{confirmation?.action === "cancel" ? t("Mégse", "Close") : t("Mégse", "Cancel")}</Button><Button variant={confirmation?.action === "delete" || confirmation?.action === "cancel" ? "danger" : "primary"} icon={confirmation?.action === "cancel" ? <StopCircle size={17} /> : confirmation?.action === "cleanup" ? <HardDrive size={17} /> : <Trash2 size={17} />} loading={operation.isPending} disabled={confirmation?.action === "delete" && deleteConfirmation !== confirmation.job.name} onClick={() => confirmation && operation.mutate(confirmation)}>{confirmationLabel}</Button></>}
      >
        {confirmation?.action === "cancel" && <Notice tone="warning">{t("A worker rendezetten zárja le a futó folyamatot; a job csak ezután kerül Megszakítva állapotba.", "The worker shuts the running process down cleanly; only then does the job become Cancelled.")}</Notice>}
        {confirmation?.action === "cleanup" && <Notice tone="info">{t("Csak a sikeresen lezárt munka nagyméretű ideiglenes fájljai törlődnek. A job, a logok, a comparison és a completed release megmarad.", "Only the large temporary files of a successfully closed job are deleted. The job, logs, comparison and completed release are kept.")}</Notice>}
        {confirmation?.action === "delete" && <><Notice tone="danger" title={t("Ez nem vonható vissza", "This cannot be undone")}>{t("A privát jobrekord, munkaterület, logok és mellékletek törlődnek. A forrás és az elkészült release megmarad.", "The private job record, workspace, logs and attachments are deleted. The source and the finished release are kept.")}</Notice><label className="field confirmation-field">{t("Írd be a munka nevét:", "Type the job name:")}<input value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} /><small><code>{confirmation.job.name}</code></small></label></>}
        {operation.isError && <Notice tone="danger">{operation.error instanceof ApiError ? operation.error.detail : operation.error.message}</Notice>}
      </Modal>
    </div>
  );
}
