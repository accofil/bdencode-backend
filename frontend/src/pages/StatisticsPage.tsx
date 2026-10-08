import { useQuery } from "@tanstack/react-query";
import { BarChart3, Download } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { JobStatistics } from "../api/types";
import { Badge, Button, Card, EmptyState, LoadingPanel, Notice, PageHeader } from "../components/ui";
import { t } from "../i18n";
import { formatBytes, formatDate, formatDuration, formatGiB, formatNumber, formatPercent } from "../utils";

type SortKey = "finished_at" | "name" | "saved_percent" | "saved_bytes" | "vmaf" | "fps";

function sortLabels(): Record<SortKey, string> {
  return {
    finished_at: t("Legutóbbi elöl", "Most recent first"),
    name: t("Név", "Name"),
    saved_percent: t("Megtakarítás (%)", "Savings (%)"),
    saved_bytes: t("Megtakarítás (GiB)", "Savings (GiB)"),
    vmaf: "VMAF",
    fps: t("Kódolási sebesség", "Encode speed"),
  };
}

function sortValue(row: JobStatistics, key: SortKey): number | string {
  switch (key) {
    case "name": return row.name.toLowerCase();
    case "saved_percent": return row.saved_percent ?? Number.NEGATIVE_INFINITY;
    case "saved_bytes": return row.saved_bytes ?? Number.NEGATIVE_INFINITY;
    case "vmaf": return row.quality.vmaf_sample ?? Number.NEGATIVE_INFINITY;
    case "fps": return row.encode_fps ?? Number.NEGATIVE_INFINITY;
    default: return row.finished_at ?? "";
  }
}

/** CSV with a UTF-8 BOM so spreadsheet programs open the accents correctly. */
export function statisticsCsv(rows: JobStatistics[]): string {
  const header = [
    "nev", "kodolo", "crf", "preset", "forras_bajt", "kimenet_bajt", "megtakaritas_bajt",
    "megtakaritas_szazalek", "vmaf_minta", "ssim", "psnr_db", "kodolasi_fps", "kodolas_masodperc", "befejezve",
  ];
  const escape = (value: unknown) => {
    const text = value == null ? "" : String(value);
    return /[",\n;]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const lines = rows.map((row) => [
    row.name, row.encoder, row.crf, row.preset, row.source_bytes, row.output_bytes, row.saved_bytes,
    row.saved_percent, row.quality.vmaf_sample, row.quality.ssim_mean, row.quality.psnr_mean_db,
    row.encode_fps, row.encode_seconds, row.finished_at,
  ].map(escape).join(","));
  return `﻿${[header.join(","), ...lines].join("\r\n")}\r\n`;
}

export function StatisticsPage() {
  const query = useQuery({ queryKey: ["statistics"], queryFn: () => api.statistics(500), retry: false });
  const [sortKey, setSortKey] = useState<SortKey>("finished_at");
  const [descending, setDescending] = useState(true);

  const rows = useMemo(() => {
    const items = [...(query.data?.jobs ?? [])];
    items.sort((left, right) => {
      const a = sortValue(left, sortKey);
      const b = sortValue(right, sortKey);
      const order = a < b ? -1 : a > b ? 1 : 0;
      return descending ? -order : order;
    });
    return items;
  }, [query.data, sortKey, descending]);

  function downloadCsv() {
    const blob = new Blob([statisticsCsv(rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = t("bdencode-statisztika.csv", "bdencode-statistics.csv");
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  const summary = query.data?.summary;
  return (
    <div className="page">
      <PageHeader
        eyebrow={t("Statisztika", "Statistics")}
        title={t("Elkészült kódolások", "Finished encodes")}
        description={t("Helymegtakarítás, minőség és kódolási sebesség fájlonként és összesítve.", "Space savings, quality and encode speed per file and in total.")}
        actions={<Button variant="secondary" icon={<Download size={17} />} onClick={downloadCsv} disabled={rows.length === 0}>{t("CSV letöltése", "Download CSV")}</Button>}
      />

      {query.isLoading ? <LoadingPanel label={t("Statisztika betöltése…", "Loading statistics…")} /> : query.isError || !summary ? (
        <Notice tone="danger" title={t("A statisztika nem tölthető be", "The statistics cannot be loaded")}>{query.error instanceof Error ? query.error.message : t("Ismeretlen hiba", "Unknown error")}</Notice>
      ) : summary.jobs === 0 ? (
        <EmptyState icon={<BarChart3 size={30} />} title={t("Még nincs elkészült munka", "No finished jobs yet")} description={t("A statisztika az első befejezett kódolás után jelenik meg.", "Statistics appear after the first finished encode.")} />
      ) : (
        <>
          <div className="stat-grid" aria-label={t("Összesítés", "Summary")}>
            <Card className="stat-card">
              <span className="eyebrow">{t("Megtakarított hely", "Space saved")}</span>
              <strong>{formatGiB(summary.saved_gib)}</strong>
              <small>{t(
                `${formatPercent(summary.saved_percent)} · ${summary.jobs_with_size_evidence} mérhető munka · forrás ${formatGiB(summary.source_gib)} → kimenet ${formatGiB(summary.output_gib)}`,
                `${formatPercent(summary.saved_percent)} · ${summary.jobs_with_size_evidence} measurable job(s) · source ${formatGiB(summary.source_gib)} → output ${formatGiB(summary.output_gib)}`,
              )}</small>
            </Card>
            <Card className="stat-card">
              <span className="eyebrow">{t("Átlagos VMAF", "Average VMAF")}</span>
              <strong>{formatNumber(summary.average_vmaf_sample)}</strong>
              <small>{t("az automatikus CRF mintakódolásaiból", "from the automatic CRF sample encodes")} · SSIM {formatNumber(summary.average_ssim, 4)} · PSNR {formatNumber(summary.average_psnr_db)} dB</small>
            </Card>
            <Card className="stat-card">
              <span className="eyebrow">{t("Kódolási sebesség", "Encode speed")}</span>
              <strong>{formatNumber(summary.average_encode_fps)} fps</strong>
              <small>{t(
                `${formatNumber(summary.average_realtime_factor)}× valós idő · összesen ${formatNumber(summary.encode_hours, 1)} óra kódolás`,
                `${formatNumber(summary.average_realtime_factor)}× real time · ${formatNumber(summary.encode_hours, 1)} hours of encoding in total`,
              )}</small>
            </Card>
            <Card className="stat-card">
              <span className="eyebrow">{t("Munkák", "Jobs")}</span>
              <strong>{summary.jobs}</strong>
              <small>{t("átlagos CRF", "average CRF")} {formatNumber(summary.average_crf)} · {Object.entries(summary.encoders).map(([name, count]) => `${name}: ${count}`).join(" · ") || "—"}</small>
            </Card>
          </div>

          <Card className="stats-table-card">
            <div className="stats-toolbar">
              <label className="field">
                <span>{t("Rendezés", "Sort by")}</span>
                <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} aria-label={t("Rendezés", "Sort by")}>
                  {Object.entries(sortLabels()).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <Button variant="ghost" onClick={() => setDescending((value) => !value)} aria-pressed={descending}>{descending ? t("Csökkenő", "Descending") : t("Növekvő", "Ascending")}</Button>
            </div>
            <div className="table-scroll">
              <table className="stats-table">
                <thead>
                  <tr>
                    <th scope="col">{t("Munka", "Job")}</th>
                    <th scope="col">{t("Kodek", "Codec")}</th>
                    <th scope="col">CRF</th>
                    <th scope="col">{t("Forrás → kimenet", "Source → output")}</th>
                    <th scope="col">{t("Megtakarítás", "Savings")}</th>
                    <th scope="col">VMAF</th>
                    <th scope="col">SSIM / PSNR</th>
                    <th scope="col">{t("Sebesség", "Speed")}</th>
                    <th scope="col">{t("Idő", "Time")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.job_id}>
                      <th scope="row"><Link to={`/jobs/${encodeURIComponent(row.job_id)}`}>{row.name}</Link><small>{formatDate(row.finished_at)}</small></th>
                      <td>{row.encoder ?? "—"}{row.preset ? <small>{row.preset}</small> : null}</td>
                      <td>{formatNumber(row.crf)}{row.auto_crf ? <Badge tone="info">auto</Badge> : null}</td>
                      <td>{formatBytes(row.source_bytes)} → {formatBytes(row.output_bytes)}</td>
                      <td>{row.saved_percent == null ? "—" : <>{formatPercent(row.saved_percent)}<small>{formatBytes(row.saved_bytes)}</small></>}</td>
                      <td>{formatNumber(row.quality.vmaf_sample)}</td>
                      <td>{formatNumber(row.quality.ssim_mean, 4)} / {formatNumber(row.quality.psnr_mean_db)} dB</td>
                      <td>{row.encode_fps == null ? "—" : <>{formatNumber(row.encode_fps)} fps<small>{formatNumber(row.realtime_factor)}×</small></>}</td>
                      <td>{formatDuration(row.encode_seconds)}<small>{t("összesen", "total")} {formatDuration(row.total_seconds)}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">{t(
              "A „—” hiányzó bizonyítékot jelent (például régebbi kiadással készült munka); a rendszer nem becsül. A VMAF csak az automatikus CRF mintakódolásaira vonatkozik, nem a teljes filmre.",
              "A “—” means missing evidence (for example a job made with an older version); the system does not estimate. VMAF covers only the automatic CRF sample encodes, not the whole film.",
            )}</p>
          </Card>
        </>
      )}
    </div>
  );
}
