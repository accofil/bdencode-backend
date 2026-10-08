import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  CirclePlus,
  Clock3,
  Cpu,
  Disc3,
  HardDrive,
  ListOrdered,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { JobCard } from "../components/JobCard";
import { cpuShareInForce, useCpuPolicy } from "../components/CpuPolicyPanel";
import { LiveStepLine } from "../components/LiveStep";
import { t } from "../i18n";
import { Badge, Card, EmptyState, LoadingPanel, PageHeader, ProgressBar } from "../components/ui";
import { formatDate, formatStatusMessage, isActiveState, isRunningState, stageProgress, stateLabel, stateTone } from "../utils";

function nestedNumber(value: unknown, ...keys: string[]): number | null {
  let current: unknown = value;
  for (const key of keys) {
    if (!current || typeof current !== "object" || !(key in current)) return null;
    current = (current as Record<string, unknown>)[key];
  }
  return typeof current === "number" ? current : null;
}

function findActive(jobs: Job[], activeId: string | null | undefined): Job | undefined {
  return jobs.find((job) => job.id === activeId) ?? jobs.find((job) => isActiveState(job.state));
}

export function DashboardPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5000 });
  const jobs = useQuery({ queryKey: ["jobs", "dashboard"], queryFn: () => api.jobs(undefined, 100), refetchInterval: 5000 });
  const runtime = useQuery({ queryKey: ["runtime-capabilities"], queryFn: api.runtimeCapabilities, staleTime: 60_000 });
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities, staleTime: 60_000 });

  const allJobs = jobs.data?.items ?? [];
  const active = findActive(allJobs, health.data?.active_job_id);
  const queued = allJobs.filter((job) => ["QUEUED", "SCANNING", "AWAITING_SELECTION", "READY"].includes(job.state));
  const recent = allJobs.filter((job) => ["COMPLETED", "FAILED", "CANCELLED"].includes(job.state)).slice(0, 4);
  const logicalCpus = nestedNumber(runtime.data, "host", "logical_cpus");
  const freeBytes = nestedNumber(runtime.data, "paths", "data", "free_bytes");
  const cpuFraction = capabilities.data?.constraints.cpu_budget_fraction;
  const cpuShare = cpuShareInForce(useCpuPolicy().data);

  return (
    <div className="page page--dashboard">
      <PageHeader
        eyebrow={t("Kezelőpult", "Dashboard")}
        title={t("Mit kódolunk ma?", "What are we encoding today?")}
        description={t("A teljes Blu-ray munkafolyamat egyetlen áttekinthető felületen.", "The whole Blu-ray workflow on one clear screen.")}
        actions={
          <Link className="button button--primary" to="/new">
            <CirclePlus size={18} />
            <span>{t("Új kódolás", "New encode")}</span>
          </Link>
        }
      />

      <div className="dashboard-grid dashboard-grid--top">
        <Link to="/new" className="hero-action-card">
          <span className="hero-action-card__orb"><Disc3 size={30} /></span>
          <div>
            <span className="eyebrow">{t("Új munka", "New job")}</span>
            <h2>{t("Blu-ray hozzáadása", "Add a Blu-ray")}</h2>
            <p>{t("Válassz forrást, majd a rendszer végigvezet a lemezen, sávokon és beállításokon.", "Choose a source and the app walks you through the disc, tracks and settings.")}</p>
          </div>
          <span className="hero-action-card__link">{t("Kezdés", "Start")} <ArrowRight size={17} /></span>
        </Link>

        <Card className="active-card">
          <div className="card-heading">
            <div>
              <span className="eyebrow">{t("Aktív munka", "Active job")}</span>
              <h2>{active ? active.name : t("A kódoló szabad", "The encoder is free")}</h2>
            </div>
            {active ? <Badge tone={stateTone(active.state)}>{stateLabel(active.state)}</Badge> : <Badge tone="success">{t("Készen áll", "Ready")}</Badge>}
          </div>
          {jobs.isLoading || health.isLoading ? (
            <LoadingPanel />
          ) : active ? (
            <>
              <div className="active-card__progress-number">{Math.round(stageProgress(active) * 100)}<small>% · {t("teljes", "overall")}</small></div>
              <ProgressBar value={stageProgress(active)} label={formatStatusMessage(active.status_message, stateLabel(active.state))} />
              <LiveStepLine jobId={active.id} running={isRunningState(active.state) && active.control_state !== "PAUSED"} />
              <Link to={`/jobs/${active.id}`} className="text-link">{t("Részletek megnyitása", "Open details")} <ArrowRight size={15} /></Link>
            </>
          ) : (
            <div className="active-card__idle">
              <CheckCircle2 size={28} />
              <div><strong>{t("Nincs futó feladat", "Nothing running")}</strong><span>{t("A következő várólistás munka automatikusan indul.", "The next job in the queue starts automatically.")}</span></div>
            </div>
          )}
        </Card>

        <Card className="system-card">
          <div className="card-heading">
            <div>
              <span className="eyebrow">{t("Szerver", "Server")}</span>
              <h2>{t("Rendszerállapot", "System status")}</h2>
            </div>
            <span
              className={health.isSuccess
                ? "live-indicator"
                : health.isError
                  ? "live-indicator live-indicator--error"
                  : "live-indicator live-indicator--pending"}
              role="status"
            >
              {health.isSuccess ? "Online" : health.isError ? t("Nem elérhető", "Unreachable") : t("Kapcsolódás…", "Connecting…")}
            </span>
          </div>
          <div className="system-metrics">
            <div><Cpu size={18} /><span><strong>{cpuShare ? `${cpuShare.percent}%` : typeof cpuFraction === "number" ? `${Math.round(cpuFraction * 100)}%` : "—"}</strong>{cpuShare?.mode === "night" ? t("CPU-keret · éjjel", "CPU budget · night") : t("CPU-keret", "CPU budget")}</span></div>
            <div><ShieldCheck size={18} /><span><strong>{logicalCpus ?? "—"}</strong>{t("logikai CPU", "logical CPUs")}</span></div>
            <div><HardDrive size={18} /><span><strong>{freeBytes !== null ? `${(freeBytes / 1024 ** 4).toFixed(1)} TiB` : "—"}</strong>{t("szabad hely", "free space")}</span></div>
          </div>
          <Link to="/settings" className="text-link">{t("Rendszer részletei", "System details")} <ArrowRight size={15} /></Link>
        </Card>
      </div>

      <div className="dashboard-grid dashboard-grid--content">
        <Card className="queue-panel">
          <div className="section-heading">
            <div>
              <span className="section-heading__icon"><ListOrdered size={19} /></span>
              <div><h2>{t("Várólista", "Queue")}</h2><p>{t(`${queued.length} munka előkészítés alatt vagy kódolásra kész`, `${queued.length} jobs being prepared or ready to encode`)}</p></div>
            </div>
            <Link to="/queue" className="text-link">{t("Összes megnyitása", "Open all")} <ArrowRight size={15} /></Link>
          </div>
          {jobs.isLoading ? <LoadingPanel /> : queued.length ? (
            <div className="job-list job-list--compact">
              {queued.slice(0, 5).map((job) => <JobCard key={job.id} job={job} compact />)}
            </div>
          ) : (
            <EmptyState
              icon={<Clock3 size={25} />}
              title={t("A várólista üres", "The queue is empty")}
              description={t("Adj hozzá több filmet; a scan és a beállítás előre elkészülhet, az encode-ok pedig egymás után futnak.", "Add several films; scans and settings can be done ahead, and the encodes run one after another.")}
              action={<Link className="button button--secondary" to="/new">{t("Munka hozzáadása", "Add a job")}</Link>}
            />
          )}
        </Card>

        <Card className="recent-panel">
          <div className="section-heading">
            <div><h2>{t("Legutóbbi munkák", "Recent jobs")}</h2><p>{t("Elkészült és lezárt kódolások", "Finished and closed encodes")}</p></div>
            <Link to="/archive" className="text-link">{t("Archívum", "Archive")} <ArrowRight size={15} /></Link>
          </div>
          {recent.length ? (
            <div className="recent-list">
              {recent.map((job) => (
                <Link key={job.id} to={`/jobs/${job.id}`} className="recent-item">
                  <span className="recent-item__icon"><Disc3 size={18} /></span>
                  <span><strong>{job.name}</strong><small>{formatDate(job.finished_at || job.updated_at)}</small></span>
                  <Badge tone={stateTone(job.state)}>{stateLabel(job.state)}</Badge>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState title={t("Még nincs előzmény", "No history yet")} description={t("Az első lezárt kódolás itt fog megjelenni.", "The first closed encode will appear here.")} />
          )}
        </Card>
      </div>
    </div>
  );
}
