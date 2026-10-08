import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { t } from "../i18n";
import { formatBytes, formatDuration, formatNumber, formatPercent } from "../utils";
import { Card } from "./ui";

/** Size, speed and quality of one completed job (overview sidebar). */
export function JobStatisticsCard({ jobId }: { jobId: string }) {
  const query = useQuery({ queryKey: ["job-statistics", jobId], queryFn: () => api.jobStatistics(jobId), retry: false });
  const stats = query.data;
  if (!stats) return null;
  return (
    <Card>
      <span className="eyebrow">{t("Statisztika", "Statistics")}</span>
      <dl className="summary-list summary-list--stacked">
        <div><dt>{t("Forrás → kimenet", "Source → output")}</dt><dd>{formatBytes(stats.source_bytes)} → {formatBytes(stats.output_bytes)}</dd></div>
        <div><dt>{t("Megtakarítás", "Saved")}</dt><dd>{stats.saved_percent == null ? "—" : `${formatPercent(stats.saved_percent)} (${formatBytes(stats.saved_bytes)})`}</dd></div>
        <div><dt>{t("Átlagos bitráta", "Average bitrate")}</dt><dd>{stats.bitrate_kbps == null ? "—" : `${formatNumber(stats.bitrate_kbps, 0)} kb/s`}</dd></div>
        <div><dt>{t("Kódoló", "Encoder")}</dt><dd>{stats.encoder ?? "—"} · CRF {formatNumber(stats.crf)}{stats.preset ? ` · ${stats.preset}` : ""}</dd></div>
        <div><dt>{t("Kódolási sebesség", "Encoding speed")}</dt><dd>{stats.encode_fps == null ? "—" : `${formatNumber(stats.encode_fps)} fps (${formatNumber(stats.realtime_factor)}× ${t("valós idő", "real time")})`}</dd></div>
        <div><dt>{t("Kódolás ideje", "Encoding time")}</dt><dd>{formatDuration(stats.encode_seconds)}</dd></div>
        <div><dt>{t("VMAF (minta)", "VMAF (sample)")}</dt><dd>{stats.quality.vmaf_sample == null ? "—" : `${formatNumber(stats.quality.vmaf_sample)}${stats.quality.vmaf_target ? ` / ${t("cél", "target")} ${formatNumber(stats.quality.vmaf_target, 1)}` : ""}`}</dd></div>
        <div><dt>SSIM / PSNR</dt><dd>{formatNumber(stats.quality.ssim_mean, 4)} / {formatNumber(stats.quality.psnr_mean_db)} dB</dd></div>
      </dl>
    </Card>
  );
}
