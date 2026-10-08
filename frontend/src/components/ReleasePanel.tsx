import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Clipboard,
  FileCheck2,
  PackageCheck,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  Artifact,
  Job,
  ReleaseMetadataPayload,
  ReleasePreparation,
  ReleaseProfileList,
  ReleaseValidationResult,
  TrackerReleaseProfile,
} from "../api/types";
import { t } from "../i18n";
import { formatBytes, humanize } from "../utils";
import { Badge, Button, Card, EmptyState, LoadingPanel, Modal, Notice } from "./ui";

// Since 3.0 BDEncode creates no torrent, seeds nothing and uploads nothing.
type ReleaseAction = "validate" | "build" | "dupe-check";
type PreparationAction = Exclude<ReleaseAction, "validate">;

interface PreparationApprovalSnapshot {
  id: string;
  version: number;
  manifestSha256: string;
  payloadSha256: string;
  releaseName: string;
  state: string;
  preparationVersions: Record<string, number>;
}

interface ReleaseDraft {
  profileId: string;
  releaseName: string;
  title: string;
  year: string;
  edition: string;
  imdbId: string;
  tmdbId: string;
  category: string;
  sourceMedia: string;
  resolution: string;
  videoCodec: string;
  audioCodecs: string;
  languages: string;
}

function releaseStateLabel(state: string): string | undefined {
  switch (state) {
    case "NOT_PREPARED": return t("Nincs előkészítve", "Not prepared");
    case "PREPARING": return t("Előkészítés folyamatban", "Preparing");
    case "NEEDS_REVIEW": return t("Ellenőrzést kér", "Needs review");
    case "READY": return t("Csomag elkészült", "Kit ready");
    case "SEEDING_CHECK": return t("Dupe check folyamatban", "Dupe check running");
    case "READY_TO_PUBLISH": return t("Dupe check: tiszta", "Dupe check: clean");
    // Seeding and publishing states only occur in records made before 3.0.
    case "SEEDING": return t("qBittorrent művelet folyamatban", "qBittorrent action running");
    case "PUBLISHING": return t("Publikálás folyamatban", "Publishing");
    case "PUBLISHED": return t("Publikálva", "Published");
    case "FAILED": return t("Hibás", "Failed");
    case "UNKNOWN": return t("Ismeretlen eredmény", "Unknown result");
    default: return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function profilesFrom(value: ReleaseProfileList | TrackerReleaseProfile[] | undefined): TrackerReleaseProfile[] {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  if (Array.isArray(value.items)) return value.items;
  return Array.isArray(value.profiles) ? value.profiles : [];
}

function preparationsFrom(value: unknown): ReleasePreparation[] {
  if (Array.isArray(value)) return value.filter(isRecord) as ReleasePreparation[];
  if (!isRecord(value)) return [];
  const items = Array.isArray(value.items)
    ? value.items
    : Array.isArray(value.preparations)
      ? value.preparations
      : [];
  return items.filter(isRecord) as ReleasePreparation[];
}

function preparationId(value: ReleasePreparation | undefined): string | null {
  if (!value) return null;
  if (typeof value.id === "string") return value.id;
  return typeof value.preparation_id === "string" ? value.preparation_id : null;
}

function preparationState(value: ReleasePreparation | undefined): string {
  if (!value) return "NOT_PREPARED";
  if (typeof value.state === "string") return value.state;
  return typeof value.status === "string" ? value.status : "UNKNOWN";
}

function releaseTone(state: string): "neutral" | "info" | "success" | "warning" | "danger" {
  if (["READY", "READY_TO_PUBLISH", "PUBLISHED"].includes(state)) return "success";
  if (["NEEDS_REVIEW", "UNKNOWN"].includes(state)) return "warning";
  if (state === "FAILED") return "danger";
  if (["PREPARING", "SEEDING_CHECK", "SEEDING", "PUBLISHING"].includes(state)) return "info";
  return "neutral";
}

function csv(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function selectionRecord(job: Job): Record<string, unknown> {
  return isRecord(job.selection) ? job.selection : {};
}

function trackerProfileOf(job: Job): string {
  const value = selectionRecord(job).tracker_profile;
  return typeof value === "string" ? value : "";
}

function outputStem(job: Job, outputArtifact?: Artifact): string {
  const source = outputArtifact?.name
    ?? outputArtifact?.path?.split(/[\\/]/).at(-1)
    ?? job.output_path?.split(/[\\/]/).at(-1)
    ?? job.name;
  return source.replace(/\.mkv$/i, "");
}

function defaultDraft(job: Job, releaseName: string): ReleaseDraft {
  const selection = selectionRecord(job);
  const yearMatch = /(?:^|[. (])(19\d{2}|20\d{2}|21\d{2})(?:[. )]|$)/.exec(releaseName);
  const tracks = Array.isArray(selection.tracks) ? selection.tracks.filter(isRecord) : [];
  const audioCodecs = [...new Set(tracks.flatMap((track) => {
    const action = typeof track.action === "string" ? track.action : "";
    return action && action !== "omit" && action !== "copy" ? [action.toUpperCase()] : [];
  }))];
  const languages = [...new Set(tracks.flatMap((track) => {
    const language = typeof track.language === "string" ? track.language : "";
    return language ? [language] : [];
  }))];
  const encoder = isRecord(selection.video) && isRecord(selection.video.settings)
    && typeof selection.video.settings.encoder === "string"
    ? selection.video.settings.encoder
    : typeof job.settings.encoder === "string"
      ? job.settings.encoder
      : "x264";
  // ``job.disc_type`` is the operator's request and defaults to AUTO; the real
  // disc kind decides the encoder (UHD is always x265), so use that as well.
  const uhd = job.disc_type === "UHD" || (job.disc_type !== "BD" && encoder === "x265");
  return {
    profileId: "",
    releaseName,
    title: job.name,
    year: yearMatch?.[1] ?? String(new Date().getFullYear()),
    edition: "",
    imdbId: "",
    tmdbId: "",
    category: job.content_type === "SERIES" ? "TV" : "Movie",
    sourceMedia: uhd ? "UHD Blu-ray" : "Blu-ray",
    resolution: uhd ? "2160p" : "1080p",
    videoCodec: encoder === "x265" ? "H.265" : "H.264",
    audioCodecs: audioCodecs.join(", ") || "Unknown",
    languages: languages.join(", ") || "und",
  };
}

function metadataFrom(draft: ReleaseDraft): ReleaseMetadataPayload {
  return {
    schema_version: 1,
    release_name: draft.releaseName.trim(),
    title: draft.title.trim(),
    year: Number(draft.year),
    edition: draft.edition.trim() || null,
    imdb_id: draft.imdbId.trim() || null,
    tmdb_id: draft.tmdbId.trim() ? Number(draft.tmdbId) : null,
    category: draft.category.trim(),
    source_media: draft.sourceMedia.trim(),
    resolution: draft.resolution.trim(),
    video_codec: draft.videoCodec.trim(),
    audio_codecs: csv(draft.audioCodecs),
    languages: csv(draft.languages),
  };
}

function errorText(error: Error): string {
  return error instanceof ApiError ? error.detail : error.message;
}

function safeEvidence(value: unknown, key = "value"): unknown {
  if (/announce|credential|passkey|token|secret/i.test(key)) return t("Rejtett érték", "Hidden value");
  if (Array.isArray(value)) return value.map((item) => safeEvidence(item));
  if (!isRecord(value)) return value;
  return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, safeEvidence(item, name)]));
}

function EvidenceList({ value, empty }: { value: unknown; empty: string }) {
  if (value == null) return <p className="muted">{empty}</p>;
  const rows = Array.isArray(value)
    ? value.slice(0, 24).map((item, index) => [String(index + 1), item] as const)
    : isRecord(value)
      ? Object.entries(value).slice(0, 24)
      : [[t("Állapot", "Status"), value] as const];
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <ul className="release-check-list">
      {rows.map(([name, raw]) => {
        const item = safeEvidence(raw, name);
        const passed = item === true || (isRecord(item) && ["ok", "passed", "ready", "success"].includes(String(item.status ?? item.result).toLowerCase()));
        const failed = item === false || (isRecord(item) && ["failed", "error", "blocked"].includes(String(item.status ?? item.result).toLowerCase()));
        const display = isRecord(item) || Array.isArray(item) ? JSON.stringify(item) : String(item);
        return (
          <li key={`${name}-${display}`} className={failed ? "release-check release-check--failed" : passed ? "release-check release-check--passed" : "release-check"}>
            <span aria-hidden="true">{failed ? "!" : passed ? "✓" : "•"}</span>
            <span><strong>{humanize(name)}</strong><small>{display}</small></span>
          </li>
        );
      })}
    </ul>
  );
}

function manifestFact(manifest: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    const value = manifest[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return null;
}

function versionSnapshot(
  preparations: ReleasePreparation[],
  current: ReleasePreparation | undefined,
): Record<string, number> {
  const entries = preparations.flatMap((item) => {
    const id = preparationId(item);
    return id && typeof item.version === "number" ? [[id, item.version] as const] : [];
  });
  const currentId = preparationId(current);
  if (currentId && typeof current?.version === "number") entries.push([currentId, current.version]);
  return Object.fromEntries(entries.sort(([left], [right]) => left.localeCompare(right)));
}

function approvalSnapshot(
  current: ReleasePreparation | undefined,
  preparations: ReleasePreparation[],
): PreparationApprovalSnapshot | null {
  const id = preparationId(current);
  if (!id || typeof current?.version !== "number") return null;
  return {
    id,
    version: current.version,
    manifestSha256: typeof current.manifest_sha256 === "string" ? current.manifest_sha256 : "",
    payloadSha256: typeof current.payload_sha256 === "string" ? current.payload_sha256 : "",
    releaseName: typeof current.metadata?.release_name === "string" ? current.metadata.release_name : id,
    state: preparationState(current),
    preparationVersions: versionSnapshot(preparations, current),
  };
}

function receiptOutcome(value: unknown): string | null {
  return isRecord(value) && typeof value.outcome === "string" ? value.outcome : null;
}

function actionNeedsReview(value: ReleasePreparation | undefined): boolean {
  if (!value) return false;
  const resultState = preparationState(value);
  if (["NEEDS_REVIEW", "UNKNOWN", "FAILED"].includes(resultState)) return true;
  return [value.dupe_receipt, value.qbittorrent_receipt, value.publication_receipt]
    .some((receipt) => ["REJECTED", "UNKNOWN"].includes(receiptOutcome(receipt) ?? ""));
}

export function ReleasePanel({ job, outputArtifact }: { job: Job; outputArtifact?: Artifact }) {
  const queryClient = useQueryClient();
  const releaseName = outputStem(job, outputArtifact);
  const [draft, setDraft] = useState<ReleaseDraft>(() => defaultDraft(job, releaseName));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<ReleaseValidationResult | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PreparationApprovalSnapshot | null>(null);
  const profilesQuery = useQuery({
    queryKey: ["release-profiles"],
    queryFn: api.releaseProfiles,
    enabled: job.state === "COMPLETED",
    staleTime: 5 * 60_000,
  });
  const preparationsQuery = useQuery({
    queryKey: ["release-preparations", job.id],
    queryFn: () => api.releasePreparations(job.id),
    enabled: job.state === "COMPLETED",
    refetchInterval: 10_000,
  });
  const profiles = profilesFrom(profilesQuery.data);
  // The job's own tracker profile (Aither/nCore) is the default release profile.
  const trackerProfile = trackerProfileOf(job);
  const profileId = draft.profileId
    || (profiles.some((item) => item.profile_id === trackerProfile) ? trackerProfile : "");
  const preparations = preparationsFrom(preparationsQuery.data);
  const currentSummary = preparations.find((item) => preparationId(item) === selectedId) ?? preparations[0];
  const currentId = selectedId ?? preparationId(currentSummary);
  const detailQuery = useQuery({
    queryKey: ["release-preparation", currentId],
    queryFn: () => api.releasePreparation(currentId!),
    enabled: Boolean(currentId),
    refetchInterval: 5000,
  });
  const current = detailQuery.data ?? currentSummary;
  const state = preparationState(current);
  const manifest = {
    ...(isRecord(current?.manifest) ? current.manifest : {}),
    ...(current?.payload_path ? { payload_path: current.payload_path } : {}),
    ...(typeof current?.payload_size === "number" ? { payload_size: current.payload_size } : {}),
    ...(current?.payload_sha256 ? { payload_sha256: current.payload_sha256 } : {}),
    ...(current?.manifest_sha256 ? { manifest_sha256: current.manifest_sha256 } : {}),
    ...(current?.torrent_infohash ? { torrent_infohash: current.torrent_infohash } : {}),
    ...(current?.torrent_sha256 ? { torrent_sha256: current.torrent_sha256 } : {}),
    ...(typeof current?.kit_ready === "boolean" ? { kit_ready: current.kit_ready } : {}),
  };
  const receiptEvidence = current && [
    ["dupe_check", current.dupe_receipt],
    ["qbittorrent", current.qbittorrent_receipt],
    ["publication", current.publication_receipt],
  ].some(([, value]) => value != null)
    ? {
        dupe_check: current.dupe_receipt,
        qbittorrent: current.qbittorrent_receipt,
        publication: current.publication_receipt,
      }
    : current?.receipts;
  const preflight = validationResult ?? current?.preflight ?? current?.validation ?? receiptEvidence;
  const preview = current?.preview ?? (Object.keys(manifest).length ? manifest : null);

  const create = useMutation({
    mutationFn: () => api.createReleasePreparation(job.id, {
      profile_id: profileId,
      metadata: metadataFrom({ ...draft, releaseName }),
    }),
    onSuccess: (preparation) => {
      setValidationResult(null);
      const id = preparationId(preparation);
      setSelectedId(id);
      if (id) queryClient.setQueryData(["release-preparation", id], preparation);
      void queryClient.invalidateQueries({ queryKey: ["release-preparations", job.id] });
    },
  });
  const action = useMutation({
    mutationFn: ({ name, id, version }: { name: PreparationAction; id: string; version: number }) =>
      api.releasePreparationAction(id, name, version),
    onSuccess: (preparation) => {
      setValidationResult(null);
      const id = preparationId(preparation) ?? currentId;
      if (id) queryClient.setQueryData(["release-preparation", id], preparation);
      void queryClient.invalidateQueries({ queryKey: ["release-preparations", job.id] });
    },
  });
  const validate = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      api.validateReleasePreparation(id, version),
    onSuccess: setValidationResult,
  });
  const remove = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) => api.deleteReleasePreparation(id, version),
    onSuccess: () => {
      const removedId = deleteTarget?.id;
      setDeleteTarget(null);
      setSelectedId((selected) => selected === removedId ? null : selected);
      setValidationResult(null);
      if (removedId) queryClient.removeQueries({ queryKey: ["release-preparation", removedId] });
      void queryClient.invalidateQueries({ queryKey: ["release-preparations", job.id] });
    },
  });

  const invalidDraft = useMemo(() => {
    const year = Number(draft.year);
    return !profileId || !releaseName || !draft.title.trim()
      || !Number.isInteger(year) || year < 1878 || year > 2200
      || csv(draft.audioCodecs).length === 0 || csv(draft.languages).length === 0;
  }, [draft, profileId, releaseName]);

  function run(name: ReleaseAction) {
    if (!currentId || typeof current?.version !== "number" || validate.isPending || action.isPending) return;
    if (name === "validate") {
      validate.reset();
      validate.mutate({ id: currentId, version: current.version });
      return;
    }
    action.reset();
    action.mutate({ name, id: currentId, version: current.version });
  }

  async function copyValue(value: unknown) {
    if (typeof value === "string" && value) await navigator.clipboard.writeText(value);
  }

  if (job.state !== "COMPLETED") {
    return <EmptyState icon={<PackageCheck size={28} />} title={t("A release még nem készíthető elő", "The release cannot be prepared yet")} description={t("A release-csomag (NFO, leírás, MediaInfo, képek) csak sikeres encode és QC után építhető fel.", "The release kit (NFO, description, MediaInfo, images) can only be built after a successful encode and QC.")} />;
  }
  if (profilesQuery.isLoading || preparationsQuery.isLoading) return <LoadingPanel label={t("Release-adatok betöltése…", "Loading release data…")} />;

  const profile = profiles.find((item) => item.profile_id === (current?.profile_id ?? profileId));
  const description = manifestFact(manifest, "description_bbcode", "description", "bbcode");
  const payloadSize = manifestFact(manifest, "payload_size", "size_bytes");
  const hasVersion = typeof current?.version === "number";
  const busy = create.isPending || validate.isPending || action.isPending || remove.isPending;
  const canBuild = ["NOT_PREPARED", "NEEDS_REVIEW", "FAILED"].includes(state) && current?.kit_ready !== true;
  const activeState = ["PREPARING", "SEEDING_CHECK", "SEEDING", "PUBLISHING"].includes(state);
  const preservedAuditState = ["UNKNOWN", "PUBLISHED"].includes(state);
  const supportsDupeCheck = profile?.supports_dupe_check === true;
  const actionRequiresReview = actionNeedsReview(action.data);

  return (
    <div className="release-panel">
      {(profilesQuery.isError || preparationsQuery.isError) && (
        <Notice tone="danger" title={t("A release-kezelő nem érhető el", "The release manager is not available")}>
          {errorText((profilesQuery.error ?? preparationsQuery.error) as Error)}
        </Notice>
      )}
      {!profiles.length && !profilesQuery.isError && (
        <Notice tone="warning" title={t("Nincs használható trackerprofil", "No usable tracker profile")}>{t("A szerveren előbb egy védett release-profilt kell engedélyezni.", "A protected release profile must first be enabled on the server.")}</Notice>
      )}

      <div className="release-layout">
        <Card className="release-form-card">
          <div className="section-heading">
            <div><span className="section-heading__icon"><PackageCheck size={19} /></span><div><h2>{t("Release-terv", "Release plan")}</h2><p>{t("A release-csomag nyilvános metaadatai", "The public metadata of the release kit")}</p></div></div>
            {current && <Badge tone={releaseTone(state)}>{releaseStateLabel(state) ?? humanize(state)}</Badge>}
          </div>

          {preparations.length > 0 && (
            <label className="field">
              {t("Korábbi előkészítés", "Earlier preparation")}
              <select value={currentId ?? ""} onChange={(event) => { setSelectedId(event.target.value); setValidationResult(null); }}>
                {preparations.map((item, index) => {
                  const id = preparationId(item);
                  return id ? <option value={id} key={id}>{item.metadata?.release_name ?? t(`Előkészítés ${index + 1}`, `Preparation ${index + 1}`)} · {releaseStateLabel(preparationState(item)) ?? preparationState(item)}</option> : null;
                })}
              </select>
            </label>
          )}

          <form onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
            <div className="release-form-grid">
              <label className="field">{t("Trackerprofil", "Tracker profile")}<select required value={profileId} onChange={(event) => setDraft((value) => ({ ...value, profileId: event.target.value }))}><option value="">{t("Válassz profilt…", "Choose a profile…")}</option>{profiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.display_name}</option>)}</select></label>
              <label className="field">{t("Év", "Year")}<input required inputMode="numeric" min="1878" max="2200" type="number" value={draft.year} onChange={(event) => setDraft((value) => ({ ...value, year: event.target.value }))} /></label>
              <label className="field release-field--wide">{t("Release-név", "Release name")}<input required readOnly aria-readonly="true" maxLength={240} value={releaseName} /><small>{t("Az ellenőrzött OUTPUT MKV fájlnevéből származik.", "Taken from the file name of the verified OUTPUT MKV.")}</small></label>
              <label className="field release-field--wide">{t("Cím", "Title")}<input required maxLength={300} value={draft.title} onChange={(event) => setDraft((value) => ({ ...value, title: event.target.value }))} /></label>
              <label className="field">Edition<input maxLength={160} value={draft.edition} onChange={(event) => setDraft((value) => ({ ...value, edition: event.target.value }))} /></label>
              <label className="field">{t("Kategória", "Category")}<input required value={draft.category} onChange={(event) => setDraft((value) => ({ ...value, category: event.target.value }))} /></label>
              <label className="field">IMDb ID<input pattern="tt[0-9]{7,10}" placeholder="tt1234567" value={draft.imdbId} onChange={(event) => setDraft((value) => ({ ...value, imdbId: event.target.value }))} /></label>
              <label className="field">TMDb ID<input min="1" type="number" value={draft.tmdbId} onChange={(event) => setDraft((value) => ({ ...value, tmdbId: event.target.value }))} /></label>
              <label className="field">{t("Forrás", "Source")}<input required value={draft.sourceMedia} onChange={(event) => setDraft((value) => ({ ...value, sourceMedia: event.target.value }))} /></label>
              <label className="field">{t("Felbontás", "Resolution")}<input required value={draft.resolution} onChange={(event) => setDraft((value) => ({ ...value, resolution: event.target.value }))} /></label>
              <label className="field">{t("Videokodek", "Video codec")}<input required value={draft.videoCodec} onChange={(event) => setDraft((value) => ({ ...value, videoCodec: event.target.value }))} /></label>
              <label className="field">{t("Audiókodekek", "Audio codecs")}<input required value={draft.audioCodecs} onChange={(event) => setDraft((value) => ({ ...value, audioCodecs: event.target.value }))} /><small>{t("Vesszővel elválasztva.", "Comma-separated.")}</small></label>
              <label className="field release-field--wide">{t("Nyelvek", "Languages")}<input required value={draft.languages} onChange={(event) => setDraft((value) => ({ ...value, languages: event.target.value }))} /><small>{t("Normalizált BCP-47 kódok, vesszővel elválasztva.", "Normalized BCP-47 codes, comma-separated.")}</small></label>
            </div>
            <Button className="release-create-button" type="submit" icon={<PackageCheck size={17} />} loading={create.isPending} disabled={invalidDraft || !profiles.length}>{t("Új előkészítés létrehozása", "Create new preparation")}</Button>
          </form>
          {create.isError && <Notice tone="danger" title={t("Az előkészítés nem hozható létre", "The preparation could not be created")}>{errorText(create.error)}</Notice>}
        </Card>

        <div className="release-side-stack">
          <Card className="release-status-card">
            <span className="eyebrow">{t("Kiválasztott terv", "Selected plan")}</span>
            <h2>{current?.metadata?.release_name ?? releaseName}</h2>
            <dl className="summary-list summary-list--stacked">
              <div><dt>{t("Állapot", "Status")}</dt><dd>{releaseStateLabel(state) ?? humanize(state)}</dd></div>
              <div><dt>Tracker</dt><dd>{profile?.display_name ?? current?.profile_id ?? "—"}</dd></div>
              <div><dt>Payload</dt><dd>{String(manifestFact(manifest, "payload_path", "release_name") ?? "—")}</dd></div>
              <div><dt>{t("Méret", "Size")}</dt><dd>{typeof payloadSize === "number" ? formatBytes(payloadSize) : "—"}</dd></div>
            </dl>
          </Card>
          <Card className="release-payload-card">
            <span className="eyebrow">Payload</span><h2>{t("Egy ellenőrzött MKV", "One verified MKV")}</h2>
            <p>{t("A csomag ezt az egy MKV-t írja le; a comparison, az analysis és a tulajdonosi rekord nem része. Torrentet a BDEncode 3.0-tól nem készít.", "The kit describes this one MKV; the comparison, the analysis and the ownership record are not part of it. Since 3.0, BDEncode creates no torrent.")}</p>
            <div className="release-payload-path"><FileCheck2 size={18} /><code>{String(manifestFact(manifest, "payload_path") ?? `${releaseName}/${releaseName}.mkv`)}</code></div>
          </Card>
        </div>
      </div>

      {current && (
        <>
          <div className="release-evidence-grid">
            <Card className="release-evidence-card"><div className="section-heading"><div><span className="section-heading__icon"><ShieldCheck size={18} /></span><div><h2>Preflight</h2><p>{t("Blokkoló és tájékoztató ellenőrzések", "Blocking and informational checks")}</p></div></div></div><EvidenceList value={preflight} empty={t("A validáció még nem futott le.", "Validation has not run yet.")} /></Card>
            <Card className="release-evidence-card"><div className="section-heading"><div><span className="section-heading__icon"><SearchCheck size={18} /></span><div><h2>{t("Csomag-előnézet", "Kit preview")}</h2><p>{t("Hash-pinnelt payload és publikus sidecarok", "Hash-pinned payload and public sidecars")}</p></div></div></div><EvidenceList value={preview} empty={t("A csomag még nem épült fel.", "The kit has not been built yet.")} /></Card>
          </div>

          <Card className="release-actions-card" aria-busy={busy}>
            <div><span className="eyebrow">{t("Műveletek", "Actions")}</span><h2>{t("Validálás, csomag és dupe check", "Validation, kit and dupe check")}</h2><p>{t("Torrentet és trackerfeltöltést a BDEncode 3.0-tól nem végez: a kész csomag alapján kézzel töltesz fel.", "Since 3.0, BDEncode makes no torrent and no tracker upload: you upload by hand from the finished kit.")}</p></div>
            <div className="release-actions">
              <Button variant="secondary" icon={<ShieldCheck size={16} />} loading={validate.isPending} disabled={busy || !hasVersion} onClick={() => run("validate")}>{t("Validálás", "Validate")}</Button>
              <Button icon={<PackageCheck size={16} />} loading={action.isPending && action.variables?.name === "build"} disabled={busy || !hasVersion || !canBuild} onClick={() => run("build")}>{t("Csomag építése", "Build kit")}</Button>
              <Button title={!supportsDupeCheck ? t("A trackerprofil nem támogat dupe checket.", "The tracker profile does not support a dupe check.") : undefined} variant="secondary" icon={<SearchCheck size={16} />} loading={action.isPending && action.variables?.name === "dupe-check"} disabled={busy || !hasVersion || state !== "READY" || !supportsDupeCheck} onClick={() => run("dupe-check")}>Dupe check</Button>
              {typeof description === "string" && <Button variant="ghost" icon={<Clipboard size={16} />} disabled={busy} onClick={() => void copyValue(description)}>{t("Leírás másolása", "Copy description")}</Button>}
              <Button variant="danger" icon={<Trash2 size={16} />} disabled={busy || !hasVersion || activeState || preservedAuditState} onClick={() => setDeleteTarget(approvalSnapshot(current, preparations))}>{t("Terv törlése", "Delete plan")}</Button>
            </div>
          </Card>
          {validate.isError && <Notice tone="danger" title={t("A validáció sikertelen", "Validation failed")}>{errorText(validate.error)}</Notice>}
          {action.isError && <Notice tone="danger" title={t("A release-művelet sikertelen", "The release action failed")}>{errorText(action.error)}</Notice>}
          {current?.error && <Notice tone="danger" title={t("Tartós release-hiba", "Persistent release error")}>{current.error}</Notice>}
          {validate.isSuccess && <Notice tone={validationResult?.valid ? "success" : "warning"} title={validationResult?.valid ? t("A preflight sikeres", "Preflight passed") : t("A preflight javítást kér", "Preflight needs fixes")}><CheckCircle2 size={16} /> {validationResult?.valid ? t("A payload, a trackerprofil és a bizonyítékok érvényesek.", "The payload, the tracker profile and the evidence are valid.") : t(`${validationResult?.failures.length ?? 0} blokkoló eltérés található.`, `${validationResult?.failures.length ?? 0} blocking issue(s) found.`)}</Notice>}
          {action.isSuccess && <Notice tone={actionRequiresReview ? "warning" : "success"} title={actionRequiresReview ? t("A release-művelet ellenőrzést kér", "The release action needs review") : t("A release-művelet elkészült", "The release action finished")}><CheckCircle2 size={16} /> {actionRequiresReview ? t("A művelet lezárult, de a receipt vagy az új állapot operátori ellenőrzést igényel.", "The action finished, but the receipt or the new state needs operator review.") : t("A friss állapot és bizonyítékok betöltve.", "The fresh state and evidence are loaded.")}</Notice>}
          {detailQuery.isError && <Notice tone="warning" title={t("A részletes állapot nem frissíthető", "The detailed state cannot be refreshed")}><Button variant="ghost" icon={<RefreshCw size={15} />} onClick={() => void detailQuery.refetch()}>{t("Újrapróbálás", "Retry")}</Button></Notice>}
        </>
      )}

      <Modal open={deleteTarget !== null} title={t("Törlöd ezt az előkészítést?", "Delete this preparation?")} busy={remove.isPending} onClose={() => { if (!remove.isPending) setDeleteTarget(null); }} footer={<><Button variant="ghost" disabled={remove.isPending} onClick={() => setDeleteTarget(null)}>{t("Mégse", "Cancel")}</Button><Button variant="danger" icon={<Trash2 size={17} />} loading={remove.isPending} disabled={!deleteTarget} onClick={() => deleteTarget && remove.mutate({ id: deleteTarget.id, version: deleteTarget.version })}>{t("Előkészítés törlése", "Delete preparation")}</Button></>}>
        <Notice tone="warning">{t("A release-terv és a csomag revíziója törlődik. Az elkészült MKV-hoz és a jobhoz a rendszer nem nyúl.", "The release plan and the kit revision are deleted. The finished MKV and the job are left untouched.")}</Notice>
        {deleteTarget && <dl className="summary-list summary-list--stacked"><div><dt>{t("Rögzített terv", "Recorded plan")}</dt><dd>{deleteTarget.releaseName}</dd></div><div><dt>{t("Állapot / revízió", "Status / revision")}</dt><dd>{releaseStateLabel(deleteTarget.state) ?? humanize(deleteTarget.state)} · v{deleteTarget.version}</dd></div><div><dt>Manifest SHA-256</dt><dd><code>{deleteTarget.manifestSha256 || "—"}</code></dd></div><div><dt>Payload SHA-256</dt><dd><code>{deleteTarget.payloadSha256 || "—"}</code></dd></div><div><dt>{t("Előkészítés-revíziók", "Preparation revisions")}</dt><dd><code>{JSON.stringify(deleteTarget.preparationVersions)}</code></dd></div></dl>}
        {remove.isError && <Notice tone="danger">{errorText(remove.error)}</Notice>}
      </Modal>
    </div>
  );
}
