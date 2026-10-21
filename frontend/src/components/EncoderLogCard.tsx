import { useQuery } from "@tanstack/react-query";
import { Copy, Download, FileText } from "lucide-react";
import { useState } from "react";
import { api, encoderLogDownloadUrl } from "../api/client";
import type { Job } from "../api/types";
import { t, useLanguage } from "../i18n";
import { copyText, formatBytes } from "../utils";
import { Badge, Button, Card } from "./ui";

/** States in which the video encoder has started, is running or has run. */
const ENCODE_STARTED = new Set(["ENCODING", "MUXING", "QC", "COMPARISON", "UPLOADING", "UPLOAD_FAILED", "COMPLETED", "NEEDS_REVIEW", "FAILED", "CANCELLED"]);

/**
 * The x264/x265 log: its settings at the start and, at the end, the statistics
 * (frame types with average QP and size, bitrate). The ffmpeg progress noise
 * and host paths are already left out by the server.
 */
export function EncoderLogCard({ job }: { job: Job }) {
  useLanguage();
  const [copied, setCopied] = useState(false);
  const query = useQuery({
    queryKey: ["encoder-log", job.id, job.state],
    queryFn: () => api.encoderLog(job.id),
    enabled: ENCODE_STARTED.has(job.state),
    // The log grows while the encode runs; afterwards it is read once.
    refetchInterval: job.state === "ENCODING" ? 15_000 : false,
    retry: false,
  });
  const log = query.data;
  if (!log?.available) return null;

  const encoder = log.encoder ?? "x264";
  const summary = (log.summary ?? []).join("\n");
  const fullText = log.text ?? "";
  const copy = () => {
    void copyText(fullText).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <Card className="encoder-log">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><FileText size={19} /></span>
          <div>
            <h2>{t(`Kódoló log · ${encoder}`, `Encoder log · ${encoder}`)} <Badge tone={log.finished ? "success" : "info"}>{log.finished ? t("kész", "finished") : t("fut", "running")}</Badge></h2>
            <p>{t("A beállítások és a záró összegzés; a folyamatjelzés és a belső útvonalak ki vannak szűrve.", "The settings and the closing summary; the progress noise and internal paths are left out.")}</p>
          </div>
        </div>
        <div className="encoder-log__actions">
          <Button variant="secondary" icon={<Copy size={16} />} onClick={copy}>{copied ? t("Másolva", "Copied") : t("Másolás", "Copy")}</Button>
          <a className="button button--secondary" href={encoderLogDownloadUrl(job.id)} download>
            <Download size={16} aria-hidden="true" /><span>{t("Letöltés", "Download")}</span>
          </a>
        </div>
      </div>
      {log.finished
        ? <pre aria-label={t("Záró összegzés", "Closing summary")}>{summary}</pre>
        : <p className="muted">{t("A záró összegzés a kódolás végén jelenik meg.", "The closing summary appears when the encode ends.")}</p>}
      <details>
        <summary>{t(`Teljes tisztított log (${log.line_count ?? 0} sor, az eredeti ${formatBytes(log.raw_bytes ?? 0)})`, `Full cleaned log (${log.line_count ?? 0} lines, the original is ${formatBytes(log.raw_bytes ?? 0)})`)}{log.truncated ? t(" · csonkolva", " · truncated") : ""}</summary>
        <pre aria-label={t("Teljes log", "Full log")}>{fullText}</pre>
      </details>
    </Card>
  );
}
