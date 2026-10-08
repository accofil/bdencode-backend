import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, ImageOff, Languages, Music, RefreshCw, Subtitles } from "lucide-react";
import { useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  ImageUploadProvider,
  Job,
  JobReview,
  LanguageReviewTrack,
  RuntimeCredentialCapability,
  UploadImageSet,
  UploadResetRequest,
} from "../api/types";
import { IMAGE_HOST_NAMES, IMAGE_UPLOAD_PROVIDER_LABELS, UPLOAD_IMAGE_SET_LABELS, uploadImageSet } from "../uploads";
import { getLanguage, t, useLanguage } from "../i18n";
import type { Language } from "../i18n";
import { formatBytes, formatStatusMessage } from "../utils";
import { Badge, Button, Card, Notice } from "./ui";

const languageNames = new Map<Language, Intl.DisplayNames | null>();

/** Language names in the interface language (built once per language). */
function languageNamesFor(language: Language): Intl.DisplayNames | null {
  if (!languageNames.has(language)) {
    let names: Intl.DisplayNames | null = null;
    try {
      names = new Intl.DisplayNames([language], { type: "language" });
    } catch {
      names = null;
    }
    languageNames.set(language, names);
  }
  return languageNames.get(language) ?? null;
}

/** "magyar (hun)" from an ISO 639-2 code and its BCP 47 form. */
export function languageLabel(code: string, bcp47: string | null | undefined): string {
  const names = languageNamesFor(getLanguage());
  if (bcp47 && names) {
    try {
      const name = names.of(bcp47);
      if (name && name.toLowerCase() !== bcp47.toLowerCase()) return `${name} (${code})`;
    } catch {
      // An unknown tag keeps its code.
    }
  }
  return code;
}

const CODEC_LABELS: Record<string, string> = {
  truehd: "TrueHD",
  dts: "DTS",
  ac3: "AC-3",
  eac3: "E-AC-3",
  pcm_bluray: "LPCM",
  flac: "FLAC",
  aac: "AAC",
  hdmv_pgs_subtitle: "PGS",
  pgs: "PGS",
};

function channelLayout(channels: number | null): string | null {
  if (!channels) return null;
  const layouts: Record<number, string> = { 1: "1.0", 2: "2.0", 6: "5.1", 7: "6.1", 8: "7.1" };
  return layouts[channels] ?? t(`${channels} csatorna`, `${channels} channels`);
}

function trackTitle(track: LanguageReviewTrack): string {
  const codec = track.codec ? CODEC_LABELS[track.codec.toLowerCase()] ?? track.codec.toUpperCase() : null;
  return [
    track.kind === "subtitle" ? t("Felirat", "Subtitle") : t("Hang", "Audio"),
    codec,
    track.kind === "subtitle" ? null : channelLayout(track.channels),
    track.title,
  ].filter(Boolean).join(" · ");
}

function reasonText(track: LanguageReviewTrack): string | null {
  if (!track.needs_confirmation) return null;
  if (track.reason === "language_conflict_or_low_confidence") {
    return t("A lemez jelölése és a hangfelismerés eltér, vagy a felismerés bizonytalan.", "The disc's tag and the speech detection disagree, or the detection is uncertain.");
  }
  if (track.reason === "subtitle_ocr_or_manual_override_required") {
    return t("A felirat nyelve a lemezről nem olvasható ki biztosan.", "The subtitle language cannot be read reliably from the disc.");
  }
  const reason = track.reason ?? t("ismeretlen ok", "unknown reason");
  return t(`A hangfelismerés nem futott le (${reason}).`, `Speech detection did not run (${reason}).`);
}

function errorText(error: Error): string {
  return error instanceof ApiError ? error.detail : error.message;
}

function useJobRefresh(job: Job) {
  const queryClient = useQueryClient();
  return (updated: Job) => {
    queryClient.setQueryData(["job", job.id], updated);
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["job", job.id] }),
      queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      queryClient.invalidateQueries({ queryKey: ["events", job.id] }),
      queryClient.invalidateQueries({ queryKey: ["job-review", job.id] }),
      queryClient.invalidateQueries({ queryKey: ["job-live", job.id] }),
    ]);
  };
}

/** Confirm the language of every retained audio and subtitle track. */
export function LanguageReviewCard({ job, review }: { job: Job; review: JobReview }) {
  const refresh = useJobRefresh(job);
  const language = useLanguage();
  const tracks = useMemo(() => review.language?.tracks ?? [], [review.language]);
  const options = useMemo(() => {
    const items = (review.language?.languages ?? []).map((item) => ({ code: item.code, label: languageLabel(item.code, item.bcp47) }));
    return items.sort((left, right) => left.label.localeCompare(right.label, language));
  }, [review.language, language]);
  const labels = useMemo(() => new Map(options.map((item) => [item.code, item.label])), [options]);
  const [choices, setChoices] = useState<Record<string, string>>(
    () => Object.fromEntries(tracks.map((track) => [track.stream_id, track.suggested ?? ""])),
  );
  const missing = tracks.filter((track) => !choices[track.stream_id]);
  const confirm = useMutation({
    mutationFn: () => api.confirmTrackLanguages(
      job.id,
      Object.fromEntries(Object.entries(choices).filter(([, code]) => code)),
      job.version,
    ),
    onSuccess: refresh,
  });
  const label = (code: string | null) => (code ? labels.get(code) ?? code : null);

  return (
    <Card className="operator-review">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Languages size={19} /></span>
          <div>
            <h2>{t("Erősítsd meg a sávok nyelvét", "Confirm the track languages")}</h2>
            <p>{t("A kódolás addig vár, amíg minden megtartott hang- és feliratsáv nyelve biztos.", "The encode waits until the language of every kept audio and subtitle track is certain.")}</p>
          </div>
        </div>
        <Badge tone="warning">{t(`${tracks.filter((track) => track.needs_confirmation).length} sáv kér döntést`, `${tracks.filter((track) => track.needs_confirmation).length} tracks need a decision`)}</Badge>
      </div>
      <div className="language-review">
        {tracks.map((track) => {
          const title = trackTitle(track);
          const clues = [
            track.declared && `${t("lemez", "disc")}: ${label(track.declared)}`,
            track.detected && `${t("felismerés", "detected")}: ${label(track.detected)}${track.detected_confidence != null ? ` · ${Math.round(track.detected_confidence * 100)}%` : ""}`,
            !track.needs_confirmation && track.resolved && t("automatikusan elfogadva", "accepted automatically"),
          ].filter(Boolean).join(" · ");
          const reason = reasonText(track);
          return (
            <div key={track.stream_id} className={track.needs_confirmation ? "language-review__row language-review__row--attention" : "language-review__row"}>
              <span className="language-review__icon" aria-hidden="true">{track.kind === "subtitle" ? <Subtitles size={17} /> : <Music size={17} />}</span>
              <div className="language-review__track">
                <strong>{title}</strong>
                {clues && <small>{clues}</small>}
                {reason && <small className="language-review__reason">{reason}</small>}
              </div>
              <select
                aria-label={`${title}: ${t("nyelv", "language")}`}
                value={choices[track.stream_id] ?? ""}
                onChange={(event) => setChoices((current) => ({ ...current, [track.stream_id]: event.target.value }))}
              >
                <option value="" disabled>{t("Válassz nyelvet…", "Choose a language…")}</option>
                {options.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
              </select>
            </div>
          );
        })}
      </div>
      <div className="operator-review__actions">
        <Button icon={<Languages size={17} />} loading={confirm.isPending} disabled={missing.length > 0 || tracks.length === 0} onClick={() => confirm.mutate()}>
          {t("Nyelvek megerősítése és folytatás", "Confirm languages and continue")}
        </Button>
        <small>{t("A munka visszakerül a kódolási sorba; a már elkészült előkészítő lépések (helyi másolat, remux, crop) újrahasznosulnak.", "The job goes back to the encoding queue; the finished preparation steps (local copy, remux, crop) are reused.")}</small>
      </div>
      {confirm.isError && <Notice tone="danger" title={t("A nyelvek mentése nem sikerült", "Saving the languages failed")}>{errorText(confirm.error)}</Notice>}
    </Card>
  );
}

/** Retry, move to another image host or image set, or finish without images. */
export function UploadReviewCard({
  job,
  review,
  credentials,
}: {
  job: Job;
  review: JobReview;
  credentials?: Record<string, RuntimeCredentialCapability>;
}) {
  const refresh = useJobRefresh(job);
  const info = review.upload;
  const largest = info?.largest_image_bytes ?? null;
  const hosts = (info?.hosts ?? []).map((host) => ({
    ...host,
    fits: largest === null || largest <= host.max_upload_bytes,
    configured: credentials?.[host.provider]?.configured,
  }));
  const lockedHostTooSmall = hosts.some((host) => host.provider === info?.provider && !host.fits);
  const [provider, setProvider] = useState<ImageUploadProvider>(() => {
    const chosen = info?.override.provider;
    if (chosen === "auto" || chosen === "imgbb" || chosen === "catbox" || chosen === "freeimage") return chosen;
    return "auto";
  });
  const [imageSet, setImageSet] = useState<UploadImageSet>(
    () => uploadImageSet(info?.override.image_set ?? job.selection?.upload_image_set),
  );
  const [confirmSkip, setConfirmSkip] = useState(false);
  const retry = useMutation({ mutationFn: () => api.retryUpload(job.id), onSuccess: refresh });
  const reset = useMutation({
    mutationFn: (request: UploadResetRequest) => api.resetUpload(job.id, { ...request, expected_version: job.version }),
    onSuccess: refresh,
  });
  const busy = retry.isPending || reset.isPending;
  const failed = job.state === "UPLOAD_FAILED";
  const lockedHost = info?.provider ? IMAGE_HOST_NAMES[info.provider] ?? info.provider : null;

  return (
    <Card className="operator-review">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><CloudUpload size={19} /></span>
          <div>
            <h2>{failed ? t("A képfeltöltés megszakadt", "The image upload stopped") : t("A képtárhely nem fogadta a feltöltést", "The image host refused the upload")}</h2>
            <p>{formatStatusMessage(job.status_message, t("A comparison képek feltöltése nem fejeződött be.", "The comparison image upload did not finish."))}</p>
          </div>
        </div>
      </div>
      {!failed && job.status_message && <details className="operator-review__raw"><summary>{t("Technikai részletek", "Technical details")}</summary><code>{job.status_message}</code></details>}
      <dl className="operator-review__facts">
        <div><dt>{t("Rögzített tárhely", "Locked host")}</dt><dd>{lockedHost ?? t("még nincs", "none yet")}</dd></div>
        <div><dt>{t("Már feltöltve", "Already uploaded")}</dt><dd>{t(`${info?.uploaded_images ?? 0} kép`, `${info?.uploaded_images ?? 0} images`)}</dd></div>
        <div><dt>{t("Legnagyobb kép", "Largest image")}</dt><dd>{formatBytes(largest)}</dd></div>
      </dl>
      {hosts.length > 0 && (
        <ul className="operator-review__hosts" aria-label={t("Képtárhelyek korlátai", "Image host limits")}>
          {hosts.map((host) => (
            <li key={host.provider}>
              <strong>{IMAGE_HOST_NAMES[host.provider] ?? host.provider}</strong>
              <small>{t(`legfeljebb ${formatBytes(host.max_upload_bytes)} / kép`, `at most ${formatBytes(host.max_upload_bytes)} / image`)}</small>
              <Badge tone={host.fits ? "success" : "danger"}>{host.fits ? t("a képek elférnek", "the images fit") : t("a legnagyobb kép túl nagy", "the largest image is too big")}</Badge>
              {host.configured === false && host.provider !== "catbox" && <Badge tone="warning">{t("nincs beállított kulcs", "no key set")}</Badge>}
            </li>
          ))}
        </ul>
      )}
      {failed && (
        <div className="operator-review__option">
          <div>
            <strong>{t("Újrapróbálás ugyanoda", "Retry the same host")}</strong>
            <small>{t("Átmeneti hálózati vagy szolgáltatói hibánál elég ennyi; a már feltöltött képek megmaradnak.", "Enough for a passing network or host error; the images already uploaded are kept.")}</small>
          </div>
          <Button variant="secondary" icon={<RefreshCw size={16} />} loading={retry.isPending} disabled={busy || lockedHostTooSmall} onClick={() => retry.mutate()}>{t("Újrapróbálás", "Retry")}</Button>
        </div>
      )}
      <div className="operator-review__option operator-review__option--form">
        <div>
          <strong>{t("Újrakezdés más beállítással", "Start over with other settings")}</strong>
          <small>{t("A munka elfelejti az eddig feltöltött képeket (azok a régi tárhelyen maradnak), és elölről tölt fel.", "The job forgets the images uploaded so far (they stay on the old host) and uploads from the start.")}</small>
        </div>
        <label className="field">
          <span>{t("Képtárhely", "Image host")}</span>
          <select aria-label={t("Új képtárhely", "New image host")} value={provider} onChange={(event) => setProvider(event.target.value as ImageUploadProvider)}>
            {Object.entries(IMAGE_UPLOAD_PROVIDER_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
        </label>
        <label className="field">
          <span>{t("Feltöltött képek", "Uploaded images")}</span>
          <select aria-label={t("Feltöltött képek köre", "Set of uploaded images")} value={imageSet} onChange={(event) => setImageSet(event.target.value as UploadImageSet)}>
            {Object.entries(UPLOAD_IMAGE_SET_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
        </label>
        <Button icon={<CloudUpload size={16} />} loading={reset.isPending && reset.variables?.upload_images !== false} disabled={busy} onClick={() => reset.mutate({ provider, image_set: imageSet, upload_images: true })}>
          {t("Újrakezdés ezzel a beállítással", "Start over with these settings")}
        </Button>
      </div>
      <div className="operator-review__option">
        <div>
          <strong>{t("Befejezés képfeltöltés nélkül", "Finish without image upload")}</strong>
          <small>{t("A kész MKV és a veszteségmentes PNG-k megmaradnak; a BBCode képhivatkozás nélkül készül el.", "The finished MKV and the lossless PNGs are kept; the BBCode is made without image links.")}</small>
        </div>
        {confirmSkip ? (
          <div className="operator-review__confirm">
            <Button variant="danger" icon={<ImageOff size={16} />} loading={reset.isPending && reset.variables?.upload_images === false} disabled={busy} onClick={() => reset.mutate({ upload_images: false })}>{t("Igen, befejezés képek nélkül", "Yes, finish without images")}</Button>
            <Button variant="ghost" disabled={busy} onClick={() => setConfirmSkip(false)}>{t("Mégse", "Cancel")}</Button>
          </div>
        ) : (
          <Button variant="ghost" icon={<ImageOff size={16} />} disabled={busy} onClick={() => setConfirmSkip(true)}>{t("Befejezés képek nélkül…", "Finish without images…")}</Button>
        )}
      </div>
      {retry.isError && <Notice tone="danger" title={t("Az újrapróbálás nem indult el", "The retry did not start")}>{errorText(retry.error)}</Notice>}
      {reset.isError && <Notice tone="danger" title={t("A feltöltés újrakezdése nem sikerült", "Restarting the upload failed")}>{errorText(reset.error)}</Notice>}
    </Card>
  );
}
