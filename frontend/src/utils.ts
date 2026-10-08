import type { ContentType, Job, JobState } from "./api/types";
import { locale, t } from "./i18n";

export function stateLabel(state: JobState): string {
  switch (state) {
    case "QUEUED": return t("Scanre vár", "Waiting for scan");
    case "SCANNING": return t("Lemez elemzése", "Analysing disc");
    case "AWAITING_SELECTION": return t("Beállításra vár", "Waiting for settings");
    case "READY": return t("Kódolásra vár", "Waiting to encode");
    case "ENCODING": return t("Videó kódolása", "Encoding video");
    case "MUXING": return t("MKV összeállítása", "Building MKV");
    case "QC": return t("Minőség-ellenőrzés", "Quality check");
    case "COMPARISON": return t("Kép-összehasonlítás", "Comparison");
    case "UPLOADING": return t("Képek feltöltése", "Uploading images");
    case "COMPLETED": return t("Elkészült", "Finished");
    case "FAILED": return t("Hibás", "Failed");
    case "CANCELLED": return t("Megszakítva", "Cancelled");
    case "NEEDS_REVIEW": return t("Ellenőrzést kér", "Needs review");
    case "UPLOAD_FAILED": return t("Feltöltési hiba", "Upload failed");
    default: return state;
  }
}

export function contentLabel(content: ContentType): string {
  switch (content) {
    case "FILM": return t("Film", "Film");
    case "CONCERT": return t("Koncert", "Concert");
    case "ANIME": return t("Anime", "Anime");
    case "SERIES": return t("Sorozat", "Series");
    default: return content;
  }
}

const PIPELINE_BASELINES: Partial<Record<JobState, number>> = {
  QUEUED: 0,
  SCANNING: 0.02,
  AWAITING_SELECTION: 0.10,
  READY: 0.12,
  ENCODING: 0.15,
  MUXING: 0.78,
  QC: 0.85,
  COMPARISON: 0.92,
  UPLOADING: 0.98,
  COMPLETED: 1,
};

export function stateTone(state: JobState): "neutral" | "info" | "success" | "warning" | "danger" {
  if (state === "COMPLETED") return "success";
  if (state === "FAILED" || state === "CANCELLED" || state === "UPLOAD_FAILED") return "danger";
  if (state === "NEEDS_REVIEW" || state === "AWAITING_SELECTION") return "warning";
  if (["SCANNING", "ENCODING", "MUXING", "QC", "COMPARISON", "UPLOADING"].includes(state)) {
    return "info";
  }
  return "neutral";
}

export function stageProgress(job: Job): number {
  if (typeof job.progress === "number") return Math.max(0, Math.min(1, job.progress));
  const fallbackState = job.resume_state
    ?? (job.state === "UPLOAD_FAILED" ? "UPLOADING" : job.state);
  return PIPELINE_BASELINES[fallbackState] ?? 0;
}

export function isActiveState(state: JobState): boolean {
  return ["ENCODING", "MUXING", "QC", "COMPARISON", "UPLOADING", "NEEDS_REVIEW", "UPLOAD_FAILED"].includes(state);
}

/** States in which the worker is executing a step of the job right now. */
export function isRunningState(state: JobState): boolean {
  return ["SCANNING", "ENCODING", "MUXING", "QC", "COMPARISON", "UPLOADING"].includes(state);
}

export function isTerminalState(state: JobState): boolean {
  return ["COMPLETED", "FAILED", "CANCELLED"].includes(state);
}

export function formatDate(value: string | null, withTime = true): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale(), {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

export function formatBytes(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value < 1024) return `${value} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let number = value;
  let index = -1;
  do {
    number /= 1024;
    index += 1;
  } while (number >= 1024 && index < units.length - 1);
  return `${number.toFixed(number >= 10 ? 1 : 2)} ${units[index]}`;
}

export function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventKindLabel(kind: string): string | undefined {
  const labels: Record<string, [string, string]> = {
    "job.created": ["Munka létrehozva", "Job created"],
    "job.state": ["Állapotváltozás", "State change"],
    "job.selection": ["Beállítások jóváhagyva", "Settings approved"],
    "job.progress": ["Előrehaladás", "Progress"],
    "job.retry": ["Folytatás elindítva", "Continuation started"],
    "job.workspace-cleaned": ["Ideiglenes munkafájlok törölve", "Temporary work files removed"],
    "job.workspace-cleanup-warning": ["Az ideiglenes munkafájlok takarítása nem sikerült", "Cleaning up the temporary work files failed"],
    "scan.created": ["Lemezvizsgálat létrehozva", "Disc scan created"],
    "scan.state": ["Lemezvizsgálat állapota", "Disc scan state"],
    "artifact.created": ["Melléklet létrehozva", "Attachment created"],
    "worker.auto-crf-probe": ["CRF-próba", "CRF probe"],
    "worker.auto-crf": ["Automatikus CRF kiválasztva", "Automatic CRF chosen"],
    "worker.dynamic-hdr": ["Dinamikus HDR", "Dynamic HDR"],
    "worker.variable-aspect": ["Változó képarány", "Variable aspect ratio"],
    "worker.final-vmaf": ["Mintavett VMAF a kész fájlon", "Sampled VMAF of the final file"],
    "job.upload-reset": ["Képfeltöltés elölről", "Image upload restarted"],
  };
  const pair = labels[kind];
  return pair ? t(pair[0], pair[1]) : undefined;
}

function eventMessageLabel(message: string): string | undefined {
  const labels: Record<string, [string, string]> = {
    "claimed by worker": ["A worker megkezdte a lemezvizsgálatot", "The worker started the disc scan"],
    "scan complete; playlist, processing and tracks require confirmation": ["A lemezvizsgálat elkészült; a playlist, a feldolgozás és a sávok jóváhagyásra várnak", "Disc scan complete; the playlist, processing and tracks wait for approval"],
    "selection accepted": ["A beállítások elfogadva", "Settings accepted"],
    "reference timeline prepared": ["A referencia-idővonal elkészült", "Reference timeline prepared"],
    "video encode complete": ["A videókódolás elkészült", "Video encode complete"],
    "final Matroska mux complete": ["A végleges Matroska összeállítása elkészült", "Final Matroska mux complete"],
    "container and audio QC passed": ["A konténer- és hangellenőrzés sikeres", "Container and audio checks passed"],
    "I/P/B comparison complete": ["Az I/P/B összehasonlítás elkészült", "I/P/B comparison complete"],
    "encode, QC and comparison completed": ["A kódolás, az ellenőrzés és az összehasonlítás elkészült", "Encode, checks and comparison complete"],
    "image upload failed; retry is safe": ["A képfeltöltés sikertelen; biztonságosan újrapróbálható", "Image upload failed; a retry is safe"],
    "one or more retained tracks need a confirmed language before encoding": ["Egy vagy több megtartott sáv nyelvét meg kell erősíteni a kódolás előtt", "One or more kept tracks need a confirmed language before encoding"],
    "track languages confirmed by operator": ["A sávok nyelve megerősítve", "Track languages confirmed"],
    "image upload reset by operator": ["A képfeltöltés elölről indul", "Image upload starts over"],
    "image upload restarted after a reset": ["A képfeltöltés újraindult", "Image upload restarted"],
    "finishing without image upload": ["Befejezés képfeltöltés nélkül", "Finishing without image upload"],
  };
  const pair = labels[message];
  return pair ? t(pair[0], pair[1]) : undefined;
}

/**
 * The encode progress line.  Since 3.6 the worker writes it in English
 * ("Encoding video: 12.3% · … · projected video size ~19.2 GB"); earlier
 * releases wrote it in Hungarian.  Both are shown in the interface language.
 */
function encodeProgressLabel(message: string): string | undefined {
  const match = /^(?:Encoding video|Videó kódolása): (.*)$/.exec(message);
  if (!match) return undefined;
  const rest = match[1]
    .replace(/(?:ETA számítása…|computing ETA…)/, t("ETA számítása…", "computing ETA…"))
    .replace(/(?:várható videóméret|projected video size) ~/, t("várható videóméret ~", "projected video size ~"));
  return `${t("Videó kódolása", "Encoding video")}: ${rest}`;
}

export function isFastComparisonTimeoutReview(message: string | null): boolean {
  if (!message) return false;
  return message === "fast comparison exceeded its five-minute time budget"
    || message === "fast comparison exceeded its bounded command/time budget";
}

export function formatStatusMessage(message: string | null, fallback: string): string {
  if (!message) return fallback;
  const retry = /^retrying failed ([A-Z_]+) stage$/.exec(message);
  if (retry) {
    const state = retry[1] as JobState;
    return `${stateLabel(state)}: ${t("biztonságos folytatás", "safe continuation")}`;
  }
  if (isFastComparisonTimeoutReview(message)) {
    return t("A gyors videó-comparison elérte az ötperces időkorlátot. Az elkészült minták megmaradtak, a folyamat biztonságosan folytatható.", "The fast video comparison hit its five-minute limit. The finished samples are kept; the job can safely continue.");
  }
  const selected = /^fast comparison: (\d+) I\/P\/B pairs selected$/.exec(message);
  if (selected) return t(`Gyors comparison: ${selected[1]} I/P/B képpár kiválasztva`, `Fast comparison: ${selected[1]} I/P/B pairs selected`);
  const pair = /^fast comparison: pair (\d+)\/(\d+) complete$/.exec(message);
  if (pair) return t(`Gyors comparison: ${pair[1]}/${pair[2]} képpár elkészült`, `Fast comparison: pair ${pair[1]}/${pair[2]} complete`);
  const complete = /^(\d+) sampled I\/P\/B comparison pairs complete$/.exec(message);
  if (complete) return t(`A gyors comparison ${complete[1]} I/P/B képpárja elkészült`, `${complete[1]} sampled I/P/B comparison pairs complete`);
  if (message === "fast comparison: preparing bounded samples") {
    return t("Gyors comparison: a rövid videóminták előkészítése", "Fast comparison: preparing the short samples");
  }
  if (message.startsWith("bounded comparison sampling could not find")) {
    return t("A rövid mintákban nem található elegendő, azonos típusú I/P/B képpár. Operátori ellenőrzés szükséges.", "The short samples hold too few same-type I/P/B pairs. Please review.");
  }
  if (message.startsWith("encoded comparison sample is invalid")) {
    return t("A kész videó mintájának időzítése nem ellenőrizhető biztonságosan.", "The timing of the encoded sample cannot be verified safely.");
  }
  if (message.startsWith("source comparison sample is invalid")) {
    return t("A source videóminta időzítése nem ellenőrizhető biztonságosan.", "The timing of the source sample cannot be verified safely.");
  }
  const probe = /^CRF (\S+) scored VMAF (\S+)$/.exec(message);
  if (probe) return t(`CRF ${probe[1]} próba: VMAF ${probe[2]}`, `CRF ${probe[1]} probe: VMAF ${probe[2]}`);
  const chosen = /^automatic CRF search selected CRF (\S+)$/.exec(message);
  if (chosen) return t(`Az automatikus CRF-keresés a CRF ${chosen[1]} értéket választotta`, `The automatic CRF search chose CRF ${chosen[1]}`);
  const verified = /^(hdr10plus|dolby_vision) metadata verified for (\d+) frames$/.exec(message);
  if (verified) {
    const format = verified[1] === "hdr10plus" ? "HDR10+" : "Dolby Vision";
    return t(`${format} metaadat ellenőrizve ${verified[2]} képkockára`, `${format} metadata verified for ${verified[2]} frames`);
  }
  if (message.startsWith("dynamic HDR is discarded")) {
    return t("A dinamikus HDR nem marad meg (csak a statikus HDR10)", "Dynamic HDR is not kept (static HDR10 only)");
  }
  if (message.startsWith("variable aspect ratio")) {
    return t("Változó képarányú film: a legszélesebb vászon marad meg, semmi sem vágódik le", "Variable aspect ratio: the widest frame is kept, nothing is cut off");
  }
  if (message.startsWith("the image host rejected the upload")) {
    return t("A képtárhely végleg elutasította a feltöltést: másik tárhely vagy képkészlet kell, vagy befejezhető képek nélkül.", "The image host refused the upload for good: choose another host or image set, or finish without images.");
  }
  const tooLarge = /^comparison image (\S+) \(([\d.]+) MB\) exceeds the upload limit/.exec(message);
  if (tooLarge) {
    return t(`A(z) ${tooLarge[1]} kép (${tooLarge[2]} MB) nagyobb a képtárhely korlátjánál: másik tárhellyel kell elölről kezdeni a feltöltést.`, `Image ${tooLarge[1]} (${tooLarge[2]} MB) exceeds the host's limit: restart the upload with another host.`);
  }
  const sampledVmaf = /^sampled VMAF of the final file: mean (\S+), 1% low (\S+) \((\d+) frames\)$/.exec(message);
  if (sampledVmaf) return t(`Mintavett VMAF a kész fájlon: átlag ${sampledVmaf[1]}, 1% low ${sampledVmaf[2]} (${sampledVmaf[3]} képkocka)`, `Sampled VMAF of the final file: mean ${sampledVmaf[1]}, 1% low ${sampledVmaf[2]} (${sampledVmaf[3]} frames)`);
  return encodeProgressLabel(message) ?? eventMessageLabel(message) ?? formatWorkerError(message);
}

export function formatWorkerError(error: string): string {
  if (error.includes("showspectrumpic") || error.includes("-spectrum.png")) {
    return t("A hang spektrumképének elkészítése sikertelen volt. A kész kódolás és az ellenőrzési eredmények megmaradtak; a javítás után a QC szakasztól biztonságosan folytatható.", "Making the audio spectrum image failed. The finished encode and the check results are kept; after the fix the job can safely continue from the QC stage.");
  }
  if (error.includes("chapters.xml")) {
    return t("A fejezetlista létrehozása sikertelen volt. A kész videó- és hangsávok megmaradtak; a javítás után biztonságosan folytatható.", "Creating the chapter list failed. The finished video and audio tracks are kept; after the fix the job can safely continue.");
  }
  if (error.includes("subtitle.mks") || error.includes("-subtitle.mks")) {
    return t("Egy feliratsáv Matroska-fájlja nem készült el. A kész videó- és hangsávok megmaradtak; a javítás után biztonságosan folytatható.", "A subtitle track's Matroska file was not created. The finished video and audio tracks are kept; after the fix the job can safely continue.");
  }
  return error;
}

export function formatEventMessage(kind: string, message: string | null): string {
  if (message && message !== kind) return formatStatusMessage(message, "");
  return eventKindLabel(kind) ?? humanize(kind.replaceAll(".", "_"));
}

export function basename(path: string): string {
  return path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || path;
}

export function suggestedOutputName(name: string, encoder: "x264" | "x265"): string {
  const suffix = encoder === "x265" ? "2160p.UHD.BluRay.x265" : "1080p.BluRay.x264";
  return `${releaseTitleBase(name)}.${suffix}`;
}

/** The title (and year) part of a release name, without inherited technical tags. */
export function releaseTitleBase(name: string): string {
  const safe = name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/_/g, ".")
    .replace(/[^A-Za-z0-9. -]+/g, "")
    .trim()
    .replace(/[ .]+/g, ".")
    .replace(/^\.+|\.+$/g, "");
  const tokens = safe.split(".").filter(Boolean);
  const technical = /^(?:complete|blu-?ray|uhd|bd|bdmv|remux|1080[pi]|2160p|720p|avc|hevc|h\.?26[45]|x26[45]|dts(?:-hd)?|truehd|atmos|ddp?(?:\d)?|e-?ac-?3|ac-?3|flac|lpcm|hdr(?:10)?|dv|dovi)$/i;
  const cutAt = tokens.findIndex((token, index) => index >= 2 && technical.test(token));
  const titleTokens = (cutAt >= 0 ? tokens.slice(0, cutAt) : tokens).filter(Boolean);
  // MULTi/GERMAN are output properties, not title data.  If they immediately
  // precede the source-format tail, never inherit them into a new release.
  while (titleTokens.length > 1 && /^(?:multi|german|french|italian|spanish|dual)$/i.test(titleTokens.at(-1) || "")) {
    titleTokens.pop();
  }
  return titleTokens.join(".") || "Encode";
}

export function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
  return Promise.resolve();
}

export function downloadJson(filename: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename.replace(/[^A-Za-z0-9._-]+/g, "_");
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Decimal gigabytes, the unit of the size target. */
export function formatGB(bytes: number | null | undefined, digits = 1): string {
  return bytes == null || !Number.isFinite(bytes) ? "—" : `${(bytes / 1e9).toFixed(digits)} GB`;
}

export function formatGiB(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? "—" : `${value.toFixed(digits)} GiB`;
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? "—" : `${value.toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}
