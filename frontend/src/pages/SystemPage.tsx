import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  CircleHelp,
  Cpu,
  Database,
  Gauge,
  HardDrive,
  RefreshCw,
  Server,
  ShieldCheck,
  Wrench,
  XCircle,
} from "lucide-react";
import { api } from "../api/client";
import { AIAdviserPanel } from "../components/AIAdviserPanel";
import { BackupsPanel } from "../components/BackupsPanel";
import { cpuShareInForce, CpuPolicyPanel, useCpuPolicy } from "../components/CpuPolicyPanel";
import { ReleaseUpdatePanel } from "../components/ReleaseUpdatePanel";
import { Badge, Button, Card, LoadingPanel, Notice, PageHeader, ProgressBar } from "../components/ui";
import { t } from "../i18n";
import { formatBytes, humanize } from "../utils";

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanLabel(value: boolean | undefined): string {
  if (value === true) return t("Igen", "Yes");
  if (value === false) return t("Nem", "No");
  return t("Ismeretlen", "Unknown");
}

const imageCredentialLabels: Record<string, string> = {
  imgbb: "ImgBB",
  catbox: "Catbox",
  freeimage: "Freeimage",
};

export function SystemPage() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5000 });
  const runtime = useQuery({ queryKey: ["runtime-capabilities"], queryFn: api.runtimeCapabilities, refetchInterval: 60_000 });
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities, staleTime: 60_000 });
  const host = runtime.data?.host;
  const tools = runtime.data?.tools ?? {};
  const dataPath = runtime.data?.paths?.data;
  const free = finiteNumber(dataPath?.free_bytes);
  const total = finiteNumber(dataPath?.total_bytes);
  const hasStorageUsage = free !== null && total !== null;
  const usedFraction = hasStorageUsage && total > 0
    ? Math.max(0, Math.min(1, 1 - free / total))
    : 0;
  const storageLabel = hasStorageUsage
    ? t(
      `${formatBytes(Math.max(0, total - free))} használatban · ${formatBytes(total)} összesen`,
      `${formatBytes(Math.max(0, total - free))} in use · ${formatBytes(total)} total`,
    )
    : t("Tárhelyadatok: Ismeretlen", "Storage data: Unknown");
  const vapourSynthOk = typeof runtime.data?.vapoursynth?.ok === "boolean"
    ? runtime.data.vapoursynth.ok
    : null;
  const cpuPolicy = useCpuPolicy();
  const cpuInForce = cpuShareInForce(cpuPolicy.data);
  const cpuPercentFromRuntime = finiteNumber(runtime.data?.worker_cpu_policy?.requested_percent);
  const cpuFraction = finiteNumber(capabilities.data?.constraints.cpu_budget_fraction);
  const cpuPercent = cpuInForce?.percent ?? cpuPercentFromRuntime ?? (cpuFraction === null ? null : cpuFraction * 100);
  const workerGpu = runtime.data?.worker_gpu;
  const gpuLabel = !workerGpu
    ? t("GPU: Ismeretlen", "GPU: Unknown")
    : workerGpu.crop_decode === "cpu"
      ? workerGpu.crop_hwaccel === "none"
        ? t("GPU kikapcsolva: a crop-keresés CPU-n fut", "GPU turned off: the crop scan runs on the CPU")
        : t("Nincs GPU: a crop-keresés CPU-n fut", "No GPU: the crop scan runs on the CPU")
      : t(
        `GPU a crop-kereséshez (${(workerGpu.devices ?? []).join(", ") || "beállítva"})`,
        `GPU for the crop scan (${(workerGpu.devices ?? []).join(", ") || "configured"})`,
      );
  const imageCredentials = runtime.data?.image_upload_credentials ?? {};

  function refresh() {
    void Promise.all([health.refetch(), runtime.refetch(), capabilities.refetch()]);
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow={t("Rendszer", "System")}
        title={t("Szerver és képességek", "Server and capabilities")}
        description={t("A telepített eszközök, a backend biztonsági korlátai és az adatbázis mentései.", "The installed tools, the backend's safety limits and the database backups.")}
        actions={<Button variant="secondary" icon={<RefreshCw size={17} />} onClick={refresh} loading={health.isFetching || runtime.isFetching}>{t("Frissítés", "Refresh")}</Button>}
      />
      {(health.isLoading || runtime.isLoading) ? <LoadingPanel label={t("Rendszeradatok betöltése…", "Loading system data…")} /> : health.isError || runtime.isError ? <Notice tone="danger" title={t("A rendszerállapot nem olvasható", "The system state cannot be read")}>{t("Az API vagy a runtime-capabilities endpoint nem elérhető.", "The API or the runtime-capabilities endpoint is not available.")}</Notice> : (
        <>
          <div className="system-overview-grid">
            <Card className="status-stat-card"><span className="status-stat-card__icon status-stat-card__icon--green"><Server size={22} /></span><div><small>Backend</small><strong>{health.data?.status === "ok" ? "Online" : t("Hiba", "Error")}</strong><span>BDEncode {capabilities.data?.backend_version ?? "—"} · API v{capabilities.data?.api_version ?? "—"}</span></div><CheckCircle2 size={18} className="success-icon" /></Card>
            <Card className="status-stat-card"><span className="status-stat-card__icon"><Cpu size={22} /></span><div><small>{t("Processzor", "Processor")}</small><strong>{host?.logical_cpus ?? t("Ismeretlen", "Unknown")} {t("logikai CPU", "logical CPUs")}</strong><span>{cpuPercent === null ? t("CPU-keret: Ismeretlen", "CPU share: Unknown") : t(`${Math.round(cpuPercent)}% teljes keret`, `${Math.round(cpuPercent)}% total share`)}</span><span>{gpuLabel}</span></div><ShieldCheck size={18} /></Card>
            <Card className="status-stat-card"><span className="status-stat-card__icon"><Database size={22} /></span><div><small>{t("Adatbázis", "Database")}</small><strong>Schema {health.data?.schema_version ?? "—"}</strong><span>{health.data?.active_job_id ? t("1 aktív encode", "1 active encode") : t(`${health.data?.ready_jobs ?? 0} kódolásra kész`, `${health.data?.ready_jobs ?? 0} ready to encode`)}{health.data?.preparing_job_id ? t(" · scan fut", " · scan running") : ""}</span></div><Gauge size={18} /></Card>
            <Card className="status-stat-card"><span className="status-stat-card__icon"><HardDrive size={22} /></span><div><small>{t("Tárhely", "Storage")}</small><strong>{free === null ? t("Ismeretlen", "Unknown") : t(`${formatBytes(free)} szabad`, `${formatBytes(free)} free`)}</strong><span>{dataPath?.path || t("Ismeretlen", "Unknown")}</span></div><HardDrive size={18} /></Card>
          </div>

          <div className="system-content-grid">
            <Card className="tools-card">
              <div className="section-heading"><div><span className="section-heading__icon"><Wrench size={19} /></span><div><h2>{t("Telepített programok", "Installed programs")}</h2><p>{t("Az encode és QC tényleges végrehajtói", "The programs that actually run the encode and QC")}</p></div></div><Badge tone={vapourSynthOk === null ? "neutral" : vapourSynthOk ? "success" : "danger"}>VapourSynth {vapourSynthOk === null ? t("Ismeretlen", "Unknown") : vapourSynthOk ? "OK" : t("hiba", "error")}</Badge></div>
              <div className="tool-table">
                {Object.entries(tools).map(([name, tool]) => {
                  const available = typeof tool.available === "boolean" ? tool.available : null;
                  return (
                    <div key={name} className="tool-row">
                      <span className={available === null ? "tool-row__status" : available ? "tool-row__status tool-row__status--ok" : "tool-row__status tool-row__status--error"}>{available === null ? <CircleHelp size={16} /> : available ? <CheckCircle2 size={16} /> : <XCircle size={16} />}</span>
                      <span><strong>{name}</strong><small>{String(tool.version ?? t("Nincs verzióadat", "No version data"))}</small></span>
                      <Badge tone={available === null ? "neutral" : available ? "success" : "danger"}>{available === null ? t("Ismeretlen", "Unknown") : available ? t("Elérhető", "Available") : t("Hiányzik", "Missing")}</Badge>
                    </div>
                  );
                })}
              </div>
            </Card>

            <div className="system-side-stack">
              <Card>
                <span className="eyebrow">{t("Tárhely", "Storage")}</span><h2>{t("Encode munkaterület", "Encode workspace")}</h2>
                <ProgressBar value={usedFraction} label={storageLabel} />
                <dl className="summary-list summary-list--stacked"><div><dt>{t("Útvonal", "Path")}</dt><dd>{dataPath?.path || t("Ismeretlen", "Unknown")}</dd></div><div><dt>{t("Olvasható", "Readable")}</dt><dd>{booleanLabel(dataPath?.readable)}</dd></div><div><dt>{t("Írható", "Writable")}</dt><dd>{booleanLabel(dataPath?.writable)}</dd></div></dl>
              </Card>
              <Card>
                <span className="eyebrow">{t("Biztonsági politika", "Safety policy")}</span><h2>{t("Rögzített korlátok", "Fixed limits")}</h2>
                <ul className="policy-list">
                  <li><CheckCircle2 size={16} /> {t("Egyszerre legfeljebb egy aktív encode", "At most one active encode at a time")}</li>
                  <li><CheckCircle2 size={16} /> {t("Scan és beállítás a futó encode mellett is", "Scan and setup even while an encode is running")}</li>
                  <li><CheckCircle2 size={16} /> {cpuPercent === null ? t("Korlátozott CPU-keret", "Limited CPU share") : t(`CPU-kapacitás legfeljebb ${Math.round(cpuPercent)}%-a`, `At most ${Math.round(cpuPercent)}% of CPU capacity`)}</li>
                  <li><CheckCircle2 size={16} /> {t("3D kimenet tiltva", "3D output disabled")}</li>
                  <li><CheckCircle2 size={16} /> {t("Alapból csak statikus HDR10; a dinamikus HDR megtartása opcionális és ellenőrzött", "Static HDR10 only by default; keeping dynamic HDR is optional and verified")}</li>
                  <li><CheckCircle2 size={16} /> {t("Comparison képek veszteségmentes PNG-ben", "Comparison images as lossless PNG")}</li>
                </ul>
              </Card>
              <Card>
                <span className="eyebrow">{t("Képfeltöltés", "Image upload")}</span><h2>{t("Worker credentialök", "Worker credentials")}</h2>
                <div className="tool-table">
                  {Object.entries(imageCredentialLabels).map(([name, label]) => {
                    const credential = imageCredentials[name];
                    const active = credential?.service_active;
                    let state = t("Ismeretlen", "Unknown");
                    let tone: "neutral" | "info" | "success" | "warning" | "danger" = "neutral";
                    if (credential?.configured === false) {
                      state = t("Nincs beállítva", "Not configured");
                      tone = "danger";
                    } else if (credential?.configured === true && credential.ready_for_consumer === false) {
                      state = t("Nincs a workerhez kötve", "Not bound to the worker");
                      tone = "danger";
                    } else if (credential?.configured === true && credential.ready_for_consumer === true) {
                      state = active === false
                        ? t("Bekötve, a worker áll", "Bound, the worker is stopped")
                        : active === true ? t("Használatra kész", "Ready to use") : t("A workerhez kötve", "Bound to the worker");
                      tone = active === false ? "warning" : "success";
                    } else if (credential?.configured === true) {
                      state = t("Beállítva, workerállapot nélkül", "Configured, no worker state");
                      tone = "info";
                    }
                    const statusClass = tone === "neutral"
                      ? "tool-row__status"
                      : tone === "danger"
                        ? "tool-row__status tool-row__status--error"
                        : "tool-row__status tool-row__status--ok";
                    return (
                      <div key={name} className="tool-row">
                        <span className={statusClass}>{tone === "neutral" || tone === "info" ? <CircleHelp size={16} /> : tone === "danger" ? <XCircle size={16} /> : <CheckCircle2 size={16} />}</span>
                        <span><strong>{label}</strong><small>{credential?.consumer_service ?? "bdencode-worker.service"}</small></span>
                        <Badge tone={tone}>{state}</Badge>
                      </div>
                    );
                  })}
                </div>
              </Card>
            </div>
          </div>

          <CpuPolicyPanel />
          <AIAdviserPanel />
          <ReleaseUpdatePanel />
          <BackupsPanel />

          {runtime.data?.warnings && runtime.data.warnings.length > 0 && <Notice tone="warning" title={t("Runtime figyelmeztetések", "Runtime warnings")}><ul>{runtime.data.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></Notice>}
          <details className="runtime-raw"><summary>{humanize("runtime_capabilities")} JSON</summary><pre>{JSON.stringify(runtime.data, null, 2)}</pre></details>
        </>
      )}
    </div>
  );
}
