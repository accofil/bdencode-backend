import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Clapperboard,
  Copy,
  Film,
  Languages,
  ListVideo,
  Music,
  Palette,
  ScanLine,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Subtitles,
  Tag,
  Trophy,
  WandSparkles,
} from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import type {
  AIProvider,
  AIQualityPriority,
  AutoCrfConfig,
  DetailLevel,
  DiscScanResult,
  DynamicHdrMode,
  FieldSpec,
  ImageUploadProvider,
  Job,
  MediaStream,
  Playlist,
  SelectionPayload,
  SelectionValidation,
  TrackAction,
  TrackSelection,
  UploadImageSet,
} from "../api/types";
import { api, ApiError } from "../api/client";
import { t, tx } from "../i18n";
import type { LocalText } from "../i18n";
import {
  blockingSourceColorFields,
  hasSafeSourceColorRecommendation,
  missingSourceColorFields,
  parseSourceColor,
  SOURCE_COLOR_FIELD_LABELS,
  sourceColorIssueFromPayload,
  suggestedSourceColor,
} from "../colorMetadata";
import type { SourceColorField, SourceColorMetadata } from "../colorMetadata";
import { normalizeStoredSelection } from "../selection";
import type { StoredTrackSelection } from "../selection";
import { encoderHelp } from "../encoderHelp";
import { IMAGE_UPLOAD_PROVIDER_LABELS, UPLOAD_IMAGE_SET_LABELS, uploadImageSet } from "../uploads";
import { basename, formatDuration, humanize, suggestedOutputName } from "../utils";
import {
  buildReleaseName,
  channelLayout,
  namingStyle,
  plannedDynamicRange,
  releaseAudio,
  rememberedReleaseTag,
  rememberReleaseTag,
  sanitizeReleaseTag,
  titleBaseOf,
  TRACKER_PROFILE_LABELS,
} from "../releaseName";
import type { TrackerProfile } from "../releaseName";
import { arrangeForTracker, plannedOrder } from "../trackerArrangement";
import { FieldHelpButton } from "./EncoderHelp";
import { ProfileLibraryPanel } from "./ProfileLibraryPanel";
import { QualityOptions } from "./QualityOptions";
import { Badge, Button, Card, Notice, ProgressBar } from "./ui";

const GROUP_LABELS: Record<string, LocalText> = {
  rate_control: { hu: "Minőség és sebesség", en: "Quality and speed" },
  format: { hu: "Formátum és színtér", en: "Format and colour space" },
  gop: { hu: "GOP és képtípusok", en: "GOP and frame types" },
  motion: { hu: "Mozgásbecslés", en: "Motion estimation" },
  psychovisual: { hu: "Pszichovizuális finomhangolás", en: "Psychovisual tuning" },
  filter: { hu: "Képszűrés", en: "Filtering" },
  hdr: { hu: "HDR10", en: "HDR10" },
  bitstream: { hu: "Bitstream", en: "Bitstream" },
  x264: { hu: "x264-specifikus", en: "x264-specific" },
  x265: { hu: "x265-specifikus", en: "x265-specific" },
};

function groupLabel(group: string): string {
  const label = GROUP_LABELS[group];
  return label ? tx(label) : humanize(group);
}

const AUDIO_TRACK_ACTIONS: TrackAction[] = ["copy", "flac", "ac3", "eac3", "dts", "omit"];
function audioActionDetails(action: TrackAction): { label: string; description: string } {
  switch (action) {
    case "copy":
      return { label: "Copy", description: t("Az eredeti hangsáv változtatás nélkül", "The original audio track, unchanged") };
    case "flac":
      return { label: "FLAC", description: t("Veszteségmentes PCM-konverzió, eredeti csatornaszám", "Lossless PCM conversion, original channel count") };
    case "ac3":
      return { label: "AC-3", description: t("640 kb/s · 48 kHz · legfeljebb 5.1", "640 kb/s · 48 kHz · up to 5.1") };
    case "eac3":
      return { label: "E-AC-3", description: t("1024 kb/s · 48 kHz · legfeljebb 5.1", "1024 kb/s · 48 kHz · up to 5.1") };
    case "dts":
      return { label: "DTS", description: t("DTS core · 1536 kb/s · 48 kHz · legfeljebb 5.1", "DTS core · 1536 kb/s · 48 kHz · up to 5.1") };
    case "omit":
      return { label: t("Kihagyás", "Omit"), description: t("A sáv nem kerül a kész MKV-ba", "The track is left out of the finished MKV") };
  }
}

const AUDIO_TRANSCODE_ACTIONS = new Set<TrackAction>(["flac", "ac3", "eac3", "dts"]);

function imageUploadProvider(value: unknown): ImageUploadProvider {
  return value === "imgbb" || value === "catbox" || value === "freeimage"
    ? value
    : "auto";
}

const FIELD_LABELS: Record<string, LocalText> = {
  encoder: { hu: "Kódoló", en: "Encoder" },
  crf: { hu: "CRF minőség", en: "CRF quality" },
  preset: { hu: "Preset", en: "Preset" },
  tune: { hu: "Tartalmi hangolás", en: "Content tuning" },
  profile: { hu: "Profil", en: "Profile" },
  level: { hu: "Dekóderszint", en: "Decoder level" },
  bit_depth: { hu: "Bitmélység", en: "Bit depth" },
  pixel_format: { hu: "Pixelformátum", en: "Pixel format" },
  color: { hu: "Színtér", en: "Colour space" },
  vbv: { hu: "VBV korlátozás", en: "VBV limit" },
  keyint: { hu: "Maximális GOP-hossz", en: "Maximum GOP length" },
  min_keyint: { hu: "Minimális GOP-hossz", en: "Minimum GOP length" },
  scenecut: { hu: "Jelenetváltás-érzékenység", en: "Scene-cut sensitivity" },
  open_gop: { hu: "Nyitott GOP", en: "Open GOP" },
  bframes: { hu: "B-framek száma", en: "Number of B-frames" },
  b_adapt: { hu: "Adaptív B-frame", en: "Adaptive B-frames" },
  b_pyramid: { hu: "B-piramis", en: "B-pyramid" },
  ref: { hu: "Referenciaképek", en: "Reference frames" },
  rc_lookahead: { hu: "Előretekintés", en: "Lookahead" },
  weightp: { hu: "Súlyozott P-predikció", en: "Weighted P-prediction" },
  weightb: { hu: "Súlyozott B-predikció", en: "Weighted B-prediction" },
  me: { hu: "Mozgásbecslési mód", en: "Motion estimation method" },
  merange: { hu: "Keresési tartomány", en: "Search range" },
  subme: { hu: "Részpixeles finomság", en: "Subpixel refinement" },
  trellis: { hu: "Trellis", en: "Trellis" },
  partitions: { hu: "Partíciók", en: "Partitions" },
  direct: { hu: "Direkt predikció", en: "Direct prediction" },
  aq_mode: { hu: "AQ mód", en: "AQ mode" },
  aq_strength: { hu: "AQ erősség", en: "AQ strength" },
  qcomp: { hu: "Kvantálási görbe", en: "Quantizer curve" },
  psy_rd: { hu: "Psy-RD", en: "Psy-RD" },
  psy_rdoq: { hu: "Psy-RDOQ", en: "Psy-RDOQ" },
  deblock_alpha: { hu: "Deblock alpha", en: "Deblock alpha" },
  deblock_beta: { hu: "Deblock beta", en: "Deblock beta" },
  chroma_qp_offset: { hu: "Chroma QP eltérés", en: "Chroma QP offset" },
  sao: { hu: "SAO", en: "SAO" },
  limit_sao: { hu: "Korlátozott SAO", en: "Limited SAO" },
  strong_intra_smoothing: { hu: "Erős intra simítás", en: "Strong intra smoothing" },
  rect: { hu: "Négyszögletes partíciók", en: "Rectangular partitions" },
  amp: { hu: "Aszimmetrikus partíciók", en: "Asymmetric partitions" },
  early_skip: { hu: "Korai skip", en: "Early skip" },
  rskip: { hu: "Rekurzív skip", en: "Recursive skip" },
  aud: { hu: "AUD NAL egységek", en: "AUD NAL units" },
  repeat_headers: { hu: "Fejlécek ismétlése", en: "Repeat headers" },
  annexb: { hu: "Annex B", en: "Annex B" },
};

const FIELD_HELP: Record<string, LocalText> = {
  crf: {
    hu: "Alacsonyabb érték: jobb kép és nagyobb fájl. A javaslat jó kiindulópont.",
    en: "Lower value: better picture and a larger file. The suggestion is a good starting point.",
  },
  preset: {
    hu: "Lassabb preset általában jobb tömörítést ad, de jelentősen tovább tart.",
    en: "A slower preset usually compresses better but takes considerably longer.",
  },
  tune: {
    hu: "A kép jellegéhez igazítja a pszichovizuális döntéseket.",
    en: "Adapts the psychovisual decisions to the character of the picture.",
  },
  bframes: {
    hu: "Legalább 1 kötelező az I/P/B összehasonlítás miatt.",
    en: "At least 1 is required for the I/P/B comparison.",
  },
  aq_strength: {
    hu: "A részletgazdag és sötét területek bitelosztását szabályozza.",
    en: "Controls how bits are spread over detailed and dark areas.",
  },
  ref: {
    hu: "Több referenciakép javíthatja a tömörítést, de lassabb és memóriaigényesebb.",
    en: "More reference frames can improve compression but are slower and use more memory.",
  },
  rc_lookahead: {
    hu: "Több jövőbeli képkocka elemzése jobb döntéseket, de nagyobb memóriaigényt jelent.",
    en: "Analysing more future frames means better decisions but more memory use.",
  },
};

const LOCKED_FIELDS = new Set(["encoder", "profile", "bit_depth", "pixel_format", "color", "hdr10"]);

function detectedLanguage(stream: MediaStream): string | null {
  return stream.language?.iso639_2t || stream.language?.bcp47 || null;
}

function initialTrackSelections(playlist: Playlist): TrackSelection[] {
  const media = playlist.streams.filter((stream) => stream.kind !== "video");
  const firstAudio = media.find((stream) => stream.kind === "audio")?.id;
  return media.map((stream, index) => {
    const keep = stream.kind === "audio"
      ? stream.default || stream.id === firstAudio
      : stream.forced || stream.default;
    return {
      stream_id: stream.id,
      action: keep ? "copy" : "omit",
      // A scan-derived declaration is evidence, not a manual override.  Leave
      // this null so the backend can validate it against sampled speech before
      // treating it as authoritative.
      language: null,
      name: stream.title,
      default: stream.kind === "audio" && stream.id === firstAudio ? true : stream.default,
      forced: stream.forced,
      subtitle_kind: stream.kind === "subtitle" ? "unknown" : null,
      order: index,
    };
  });
}

function mergeTrackSelections(playlist: Playlist, saved: StoredTrackSelection[] = []): TrackSelection[] {
  const savedById = new Map(saved.map((selection) => [selection.stream_id, selection]));
  return initialTrackSelections(playlist).map((fallback, order) => {
    const existing = savedById.get(fallback.stream_id);
    return existing
      ? { ...fallback, ...existing, stream_id: fallback.stream_id, order: typeof existing.order === "number" ? existing.order : order }
      : fallback;
  });
}

function normalizeDetailLevel(value: unknown): DetailLevel {
  return value === "advanced" || value === "pro" || value === "beginner" ? value : "beginner";
}

function editableRecommendation(
  fields: FieldSpec[],
  recommendation: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const field of fields) {
    if (LOCKED_FIELDS.has(field.name) || field.name === "vbv") continue;
    if (field.name in recommendation) result[field.name] = recommendation[field.name];
  }
  return result;
}

function suggestedTemporalFilter(playlist: Playlist): string {
  const order = playlist.streams.find((stream) => stream.kind === "video")?.video?.field_order;
  if (!order || order === "progressive" || order === "unknown") return "progressive";
  return order.toLowerCase().includes("bb") || order.toLowerCase().includes("bottom") ? "bwdif_bff" : "bwdif_tff";
}

function fieldLabel(name: string): string {
  const label = FIELD_LABELS[name];
  return encoderHelp(name)?.title || (label ? tx(label) : "") || humanize(name);
}

function isSubtitleClassificationError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return /retained subtitles?/i.test(error.detail)
    && /full\s*\/\s*forced|full.*forced/i.test(error.detail);
}

function isAudioSubtitleFieldsError(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return /audio tracks?/i.test(error.detail)
    && /forced/i.test(error.detail)
    && /subtitle_kind/i.test(error.detail);
}

function tracksForPayload(tracks: TrackSelection[], playlist: Playlist | undefined): TrackSelection[] {
  const subtitleIds = new Set(
    playlist?.streams.filter((stream) => stream.kind === "subtitle").map((stream) => stream.id) ?? [],
  );
  return tracks.map((track) => {
    if (subtitleIds.has(track.stream_id)) return track;
    const { forced: _forced, subtitle_kind: _subtitleKind, ...audioTrack } = track;
    return audioTrack;
  });
}

export function SelectionWizard({
  job,
  scan,
  onComplete,
}: {
  job: Job;
  scan: DiscScanResult;
  onComplete: () => void;
}) {
  const initial = normalizeStoredSelection(job.selection);
  const initialPlaylist = initial?.playlistId
    ? scan.playlists.find((item) => item.playlist_id === initial.playlistId)
    : undefined;
  const defaultPlaylist = initialPlaylist
    ?? scan.playlists.find((item) => item.recommended)
    ?? scan.playlists[0];
  const [step, setStep] = useState(1);
  const [playlistId, setPlaylistId] = useState(defaultPlaylist?.playlist_id ?? "");
  const [angle, setAngle] = useState(
    initialPlaylist ? Math.min(initial?.angle ?? 1, initialPlaylist.angle_count) : 1,
  );
  const [tracks, setTracks] = useState<TrackSelection[]>(
    defaultPlaylist ? mergeTrackSelections(defaultPlaylist, initialPlaylist ? initial?.tracks : []) : [],
  );
  const initialDetail = normalizeDetailLevel(initial?.detailLevel ?? job.settings.detail_level);
  const [detailLevel, setDetailLevel] = useState<DetailLevel>(initialDetail);
  const [temporalFilter, setTemporalFilter] = useState(
    initial?.temporalFilter ?? (defaultPlaylist ? suggestedTemporalFilter(defaultPlaylist) : "progressive"),
  );
  const [crop, setCrop] = useState(initial?.crop ?? { left: 0, top: 0, right: 0, bottom: 0 });
  const encoder = scan.disc_kind === "uhd" ? "x265" : "x264";
  const [outputName, setOutputName] = useState(
    initial?.outputName ?? suggestedOutputName(job.name || basename(scan.source), encoder),
  );
  const [uploadImages, setUploadImages] = useState(
    initial?.uploadImages ?? Boolean(job.settings.upload_images ?? true),
  );
  const [selectedImageProvider, setSelectedImageProvider] = useState<ImageUploadProvider>(
    initial?.imageUploadProvider ?? imageUploadProvider(job.settings.image_upload_provider),
  );
  const [selectedImageSet, setSelectedImageSet] = useState<UploadImageSet>(
    initial?.uploadImageSet ?? uploadImageSet(job.settings.upload_image_set),
  );
  const [settings, setSettings] = useState<Record<string, unknown>>(initial?.settings ?? {});
  const [settingsSearch, setSettingsSearch] = useState("");
  const [autoCrf, setAutoCrf] = useState<AutoCrfConfig | null>(initial?.autoCrf ?? null);
  const [dynamicHdr, setDynamicHdr] = useState<DynamicHdrMode>(initial?.dynamicHdr ?? "discard");
  const [trackerProfile, setTrackerProfile] = useState<TrackerProfile>(initial?.trackerProfile ?? "none");
  const [arrangementNotes, setArrangementNotes] = useState<string[]>([]);
  const [releaseTag, setReleaseTag] = useState(() => rememberedReleaseTag());
  const [aiQualityPriority, setAiQualityPriority] = useState<AIQualityPriority>("balanced");
  const [aiTargetSize, setAiTargetSize] = useState("");
  const [aiGenre, setAiGenre] = useState("");
  const [aiPrompt, setAiPrompt] = useState(() => t(
    "Őrizze meg a forrás részleteit és textúráját, ésszerű fájlméret mellett.",
    "Keep the source's detail and texture at a reasonable file size.",
  ));
  const [aiApplied, setAiApplied] = useState(false);
  const [validation, setValidation] = useState<SelectionValidation | null>(null);
  const initialVideo = defaultPlaylist?.streams.find((stream) => stream.kind === "video")?.video;
  const initialConfirmedColor = parseSourceColor(initial?.settings.color);
  const [colorDraft, setColorDraft] = useState<SourceColorMetadata>(
    initialConfirmedColor ?? suggestedSourceColor(initialVideo, scan.disc_kind),
  );
  const [colorConfirmed, setColorConfirmed] = useState(Boolean(initialConfirmedColor));
  const initializedRecommendation = useRef(
    initial && Object.keys(initial.settings).length > 0 ? `${encoder}:${detailLevel}` : "",
  );
  const queryClient = useQueryClient();

  const playlist = scan.playlists.find((item) => item.playlist_id === playlistId) ?? scan.playlists[0];
  const schema = useQuery({
    queryKey: ["profile-schema", encoder, detailLevel],
    queryFn: () => api.profileSchema(encoder, detailLevel),
  });
  const recommendation = useQuery({
    queryKey: ["profile-recommendation", encoder, detailLevel, job.content_type],
    queryFn: () => api.profileRecommendation(encoder, detailLevel, job.content_type),
  });
  const aiStatus = useQuery({
    queryKey: ["ai-recommendation-status"],
    queryFn: api.aiRecommendationStatus,
    enabled: step === 3,
  });
  const [aiProviderChoice, setAiProvider] = useState<AIProvider | null>(null);
  const aiProvider = aiProviderChoice ?? aiStatus.data?.provider ?? null;
  const aiConfigured = (aiStatus.data?.providers ?? []).filter((item) => item.configured);
  // Older backends report one provider without the list.
  const aiChosen = aiStatus.data?.providers?.find((item) => item.id === aiProvider)
    ?? (aiStatus.data ? { id: aiStatus.data.provider, label: "OpenAI", configured: aiStatus.data.configured, model: aiStatus.data.model } : undefined);

  useEffect(() => {
    const key = `${encoder}:${detailLevel}`;
    if (!schema.data || !recommendation.data || initializedRecommendation.current === key) return;
    setSettings((current) => ({
      ...editableRecommendation(schema.data.fields, recommendation.data.settings),
      ...(parseSourceColor(current.color) ? { color: current.color } : {}),
    }));
    initializedRecommendation.current = key;
  }, [detailLevel, encoder, recommendation.data, schema.data]);

  const payload = useMemo<SelectionPayload>(() => ({
    schema_version: 2,
    playlist_id: playlistId,
    angle,
    output_name: outputName.trim().replace(/\.mkv$/i, ""),
    video: {
      detail_level: detailLevel,
      temporal_filter: temporalFilter,
      crop,
      settings,
      ...(autoCrf?.enabled ? { auto_crf: autoCrf } : {}),
      ...(dynamicHdr !== "discard" ? { dynamic_hdr: dynamicHdr } : {}),
    },
    tracks: tracksForPayload(tracks, playlist),
    upload_images: uploadImages,
    image_upload_provider: selectedImageProvider,
    upload_image_set: selectedImageSet,
    dual_type_match: true,
    ...(trackerProfile !== "none" ? { tracker_profile: trackerProfile } : {}),
  }), [angle, autoCrf, crop, detailLevel, dynamicHdr, outputName, playlist, playlistId, selectedImageProvider, selectedImageSet, settings, temporalFilter, trackerProfile, tracks, uploadImages]);

  const validate = useMutation({
    mutationFn: () => api.validateSelection(job.id, payload, job.version),
    onSuccess: (result) => setValidation(result),
  });
  const aiRecommendation = useMutation({
    mutationFn: () => {
      const parsedSize = aiTargetSize.trim() ? Number.parseFloat(aiTargetSize) : null;
      return api.aiRecommendation(job.id, {
        playlist_id: playlistId,
        detail_level: detailLevel,
        quality_priority: aiQualityPriority,
        target_size_gib: parsedSize !== null && Number.isFinite(parsedSize) ? parsedSize : null,
        genre: aiGenre.trim() || null,
        prompt: aiPrompt.trim(),
        provider: aiProvider,
      });
    },
    onSuccess: () => setAiApplied(false),
  });
  const save = useMutation({
    mutationFn: () => api.saveSelection(job.id, payload, job.version),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["job", job.id] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      onComplete();
    },
  });

  function clearPlanFeedback() {
    setValidation(null);
    validate.reset();
    save.reset();
  }

  function confirmSourceColor() {
    setSettings((current) => ({ ...current, color: colorDraft }));
    setColorConfirmed(true);
    clearPlanFeedback();
  }

  function choosePlaylist(id: string) {
    const selected = scan.playlists.find((item) => item.playlist_id === id);
    if (!selected) return;
    setPlaylistId(id);
    setAngle(1);
    setTracks(initialTrackSelections(selected));
    setTemporalFilter(suggestedTemporalFilter(selected));
    const selectedVideo = selected.streams.find((stream) => stream.kind === "video")?.video;
    setColorDraft(suggestedSourceColor(selectedVideo, scan.disc_kind));
    setColorConfirmed(false);
    setSettings((current) => {
      const next = { ...current };
      delete next.color;
      return next;
    });
    clearPlanFeedback();
    aiRecommendation.reset();
    setAiApplied(false);
  }

  function applyAIRecommendation() {
    if (!aiRecommendation.data || !schema.data) return;
    const editable = editableRecommendation(
      schema.data.fields,
      aiRecommendation.data.settings,
    );
    setSettings((current) => ({ ...current, ...editable }));
    if ([
      "progressive",
      "ivtc_tff",
      "ivtc_bff",
      "bwdif_tff",
      "bwdif_bff",
      "hybrid_safe_bob_tff",
      "hybrid_safe_bob_bff",
    ].includes(aiRecommendation.data.temporal_filter)) {
      setTemporalFilter(aiRecommendation.data.temporal_filter);
    }
    clearPlanFeedback();
    setAiApplied(true);
  }

  function applyTrackerArrangement(profile: TrackerProfile) {
    if (!playlist) return;
    const result = arrangeForTracker(profile, tracks, playlist, encoder);
    setTracks(result.tracks);
    setArrangementNotes(result.notes.length ? result.notes : [t("A sávterv már megfelel a szabályoknak.", "The track plan already meets the rules.")]);
    setValidation(null);
  }

  function suggestReleaseName() {
    if (!playlist) return;
    const tag = sanitizeReleaseTag(releaseTag);
    rememberReleaseTag(tag);
    setReleaseTag(tag);
    setOutputName(buildReleaseName({
      base: titleBaseOf(outputName || job.name || basename(scan.source)),
      encoder,
      style: namingStyle(trackerProfile),
      audio: releaseAudio(tracks, playlist),
      dynamicRange: plannedDynamicRange(encoder, videoStream?.video, dynamicHdr, temporalFilter),
      tag,
    }));
    setValidation(null);
  }

  function updateTrack(streamId: string, update: Partial<TrackSelection>) {
    setTracks((current) => current.map((item) => item.stream_id === streamId ? { ...item, ...update } : item));
    setValidation(null);
  }

  function updateSetting(field: FieldSpec, raw: string | boolean) {
    const numeric = field.value_type === "integer" || field.value_type === "number";
    if ((numeric || field.optional) && String(raw).trim() === "") {
      setSettings((current) => {
        const next = { ...current };
        delete next[field.name];
        return next;
      });
      setValidation(null);
      return;
    }
    const value = field.value_type === "boolean"
      ? typeof raw === "string" ? raw === "true" : raw
      : field.value_type === "integer"
        ? Number.parseInt(String(raw), 10)
        : field.value_type === "number"
          ? Number.parseFloat(String(raw))
          : raw;
    if (numeric && typeof value === "number" && !Number.isFinite(value)) return;
    setSettings((current) => ({ ...current, [field.name]: value }));
    setValidation(null);
  }

  function applyNoiseProfile(patch: Record<string, unknown>) {
    setSettings((current) => ({ ...current, ...patch }));
    clearPlanFeedback();
  }

  function applyLibraryProfile(selection: { settings: Record<string, unknown>; auto_crf?: AutoCrfConfig; dynamic_hdr?: DynamicHdrMode }) {
    setSettings((current) => ({ ...current, ...selection.settings }));
    setAutoCrf(selection.auto_crf?.enabled ? selection.auto_crf : null);
    setDynamicHdr(selection.dynamic_hdr ?? "discard");
    clearPlanFeedback();
  }

  function updateSettings(next: SetStateAction<Record<string, unknown>>) {
    setSettings(next);
    setValidation(null);
  }

  const retainedTracks = tracks.filter((item) => item.action !== "omit");
  const unresolvedTracks = retainedTracks.filter((item) => !item.language);
  const videoStream = playlist?.streams.find((stream) => stream.kind === "video");
  const missingColorFields = missingSourceColorFields(videoStream?.video);
  const colorApiIssue = validate.error instanceof ApiError
    ? sourceColorIssueFromPayload(validate.error.payload)
    : null;
  const subtitleClassificationApiIssue = isSubtitleClassificationError(validate.error);
  const audioSubtitleFieldsApiIssue = isAudioSubtitleFieldsError(validate.error);
  const needsColorConfirmation = blockingSourceColorFields(videoStream?.video).length > 0
    || Boolean(colorApiIssue);
  const safeColorRecommendation = hasSafeSourceColorRecommendation(videoStream?.video, scan.disc_kind);
  const reportedMissingColorFields = colorApiIssue?.missing.length
    ? colorApiIssue.missing
    : missingColorFields;
  const sourceInterlaced = videoStream?.video?.field_order && !["progressive", "unknown"].includes(videoStream.video.field_order);
  const expectedTrackIds = playlist?.streams.filter((stream) => stream.kind !== "video").map((stream) => stream.id) ?? [];
  const selectedTrackIds = new Set(tracks.map((track) => track.stream_id));
  const hasCompleteTrackPlan = expectedTrackIds.every((streamId) => selectedTrackIds.has(streamId));
  const subtitleTrackIds = new Set(playlist?.streams.filter((stream) => stream.kind === "subtitle").map((stream) => stream.id) ?? []);
  const unclassifiedRetainedSubtitles = retainedTracks.filter((track) =>
    subtitleTrackIds.has(track.stream_id)
    && track.subtitle_kind !== "full"
    && track.subtitle_kind !== "forced",
  );
  const canNext = step === 1
    ? Boolean(playlist)
    : step === 2
      ? hasCompleteTrackPlan && unclassifiedRetainedSubtitles.length === 0
      : step === 3
        ? Boolean(outputName.trim())
        : true;

  return (
    <div className="selection-wizard">
      <div className="selection-wizard__header">
        <div>
          <span className="eyebrow">{t("Scan elkészült", "Scan complete")}</span>
          <h2>{t("Kódolási beállítások", "Encoding settings")}</h2>
          <p>{t("Jóváhagyás után a szerveroldalon ellenőrzött terv kódolásra kész állapotban vár a sorára; külön indítógomb nincs.", "Once approved, the server-checked plan waits in the queue ready to encode; there is no separate start button.")}</p>
        </div>
        <div className="codec-lockup">
          <span>{scan.disc_kind === "uhd" ? "UHD" : "BD"}</span>
          <strong>{encoder}</strong>
          <small>{scan.disc_kind === "uhd" ? t("HDR10 megtartással", "HDR10 retained") : "SDR Blu-ray"}</small>
        </div>
      </div>

      <div className="wizard-steps wizard-steps--four">
        {["Playlist", t("Sávok", "Tracks"), t("Videó", "Video"), t("Ellenőrzés", "Check")].map((label, index) => (
          <button
            type="button"
            key={index}
            className={index + 1 === step ? "wizard-step wizard-step--active" : index + 1 < step ? "wizard-step wizard-step--complete" : "wizard-step"}
            onClick={() => index + 1 < step && setStep(index + 1)}
            disabled={index + 1 > step}
            aria-current={index + 1 === step ? "step" : undefined}
          >
            <span>{index + 1 < step ? <Check size={15} /> : index + 1}</span>{label}
          </button>
        ))}
      </div>

      {scan.warnings.length > 0 && (
        <Notice tone="warning" title={t("A scan figyelmeztetései", "Scan warnings")}>
          <ul>{scan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </Notice>
      )}

      {step === 1 && (
        <div className="playlist-grid">
          {scan.playlists.map((item) => {
            const video = item.streams.find((stream) => stream.kind === "video")?.video;
            return (
              <button type="button" key={item.playlist_id} className={playlistId === item.playlist_id ? "playlist-card playlist-card--selected" : "playlist-card"} aria-pressed={playlistId === item.playlist_id} onClick={() => choosePlaylist(item.playlist_id)}>
                <span className="playlist-card__visual"><Film size={27} aria-hidden="true" /><small>{video?.width ?? "?"}×{video?.height ?? "?"}</small></span>
                <span className="playlist-card__content">
                  <span className="playlist-card__top">
                    <strong>{item.edition_label || (item.episode_number ? t(`${item.episode_number}. epizód`, `Episode ${item.episode_number}`) : `Playlist ${item.playlist_id}`)}</strong>
                    {item.recommended && <Badge tone="success">{t("Ajánlott", "Recommended")}</Badge>}
                  </span>
                  <span className="playlist-card__facts">
                    <span>{formatDuration(item.duration_seconds)}</span>
                    <span>{t(`${item.chapters.length} fejezet`, `${item.chapters.length} chapters`)}</span>
                    <span>{t(`${item.segments.length} szegmens`, `${item.segments.length} segments`)}</span>
                    <span>{t(`${item.angle_count} szög`, `${item.angle_count} angles`)}</span>
                  </span>
                  <span className="playlist-card__tags">
                    <Badge>{video?.codec?.toUpperCase() || t("VIDEÓ", "VIDEO")}</Badge>
                    {video?.hdr10 && <Badge tone="info">HDR10</Badge>}
                    {video?.dolby_vision && <Badge tone="warning">DV → HDR10</Badge>}
                    {item.seamless_branching && <Badge>Seamless branching</Badge>}
                  </span>
                </span>
                <span className="playlist-card__check">{playlistId === item.playlist_id && <Check size={16} />}</span>
              </button>
            );
          })}
          {playlist && playlist.angle_count > 1 && (
            <label className="field playlist-angle-field">
              <span>{t("Kameraállás / szög", "Camera angle")}</span>
              <select value={angle} onChange={(event) => { setAngle(Number(event.target.value)); setValidation(null); }}>
                {Array.from({ length: playlist.angle_count }, (_, index) => index + 1).map((value) => (
                  <option key={value} value={value}>{t(`${value}. szög`, `Angle ${value}`)}</option>
                ))}
              </select>
              <small>{t("A kiválasztott playlist több Blu-ray szöget tartalmaz; válaszd ki a feldolgozandót.", "The selected playlist has several Blu-ray angles; choose the one to process.")}</small>
            </label>
          )}
        </div>
      )}

      {step === 2 && playlist && (
        <div className="track-sections">
          <Card className="tracker-card">
            <div className="section-heading">
              <div><span className="section-heading__icon"><Trophy size={19} /></span><div><h3>{t("Tracker-szabályok", "Tracker rules")}</h3><p>{t("Melyik oldal szabályai szerint készüljön a release", "Which site's rules the release should follow")}</p></div></div>
            </div>
            <div className="tracker-card__controls">
              <label className="field">
                <span>{t("Tracker-profil", "Tracker profile")}</span>
                <select aria-label={t("Tracker-profil", "Tracker profile")} value={trackerProfile} onChange={(event) => { setTrackerProfile(event.target.value as TrackerProfile); setArrangementNotes([]); setValidation(null); }}>
                  {(Object.keys(TRACKER_PROFILE_LABELS) as TrackerProfile[]).map((value) => <option key={value} value={value}>{TRACKER_PROFILE_LABELS[value]}</option>)}
                </select>
                <small>{trackerProfile === "ncore"
                  ? t(
                    "nCore + magyar encode-szabvány: magyar hang elöl és alapértelmezett, 1080p-n nincs TrueHD/DTS-HD MA, DTS/TrueHD mellé DD@640 kell.",
                    "nCore + Hungarian encoding standard: Hungarian audio first and default, no TrueHD/DTS-HD MA at 1080p, DTS/TrueHD needs a DD@640 track alongside.",
                  )
                  : trackerProfile === "aither"
                    ? t(
                      "Aither: csak eredeti és angol hang (plusz kommentár), TrueHD mellé DD/DD+ kompatibilitási sáv, angol felirat, ha nincs angol hang.",
                      "Aither: original and English audio only (plus commentary), a DD/DD+ compatibility track alongside TrueHD, English subtitles when there is no English audio.",
                    )
                    : t("Általános mód: nincs trackerspecifikus ellenőrzés.", "General mode: no tracker-specific checks.")}</small>
              </label>
              {trackerProfile !== "none" && (
                <Button variant="secondary" icon={<WandSparkles size={17} />} onClick={() => applyTrackerArrangement(trackerProfile)}>
                  {t("Sávterv igazítása", "Arrange tracks")} ({TRACKER_PROFILE_LABELS[trackerProfile]})
                </Button>
              )}
            </div>
            {arrangementNotes.length > 0 && <Notice tone="info" title={t("Mi változott", "What changed")}><ul>{arrangementNotes.map((note) => <li key={note}>{note}</li>)}</ul></Notice>}
            {trackerProfile !== "none" && (
              <ol className="tracker-order" aria-label={t("Kimeneti sávsorrend", "Output track order")}>
                {plannedOrder(tracks, playlist).map(({ track, stream }) => (
                  <li key={track.stream_id}>
                    <strong>{stream.kind === "audio" ? t("Hang", "Audio") : t("Felirat", "Subtitle")}</strong>
                    <span>{track.language || stream.language?.iso639_2t || "?"} · {track.action === "copy" ? (stream.codec_profile || stream.codec) : track.action.toUpperCase()}{stream.kind === "audio" && channelLayout(track.action === "copy" || track.action === "flac" ? stream.channels : Math.min(stream.channels ?? 0, 6)) ? ` ${channelLayout(track.action === "copy" || track.action === "flac" ? stream.channels : Math.min(stream.channels ?? 0, 6))}` : ""}{track.subtitle_kind === "forced" ? " · forced" : ""}</span>
                    {stream.kind === "audio" && track.default && <Badge tone="success">{t("alapértelmezett", "default")}</Badge>}
                  </li>
                ))}
              </ol>
            )}
          </Card>
          <TrackTable
            title={t("Hangsávok", "Audio tracks")}
            icon={<Music size={20} />}
            streams={playlist.streams.filter((stream) => stream.kind === "audio")}
            selections={tracks}
            onUpdate={updateTrack}
          />
          <TrackTable
            title={t("Feliratok", "Subtitles")}
            icon={<Subtitles size={20} />}
            streams={playlist.streams.filter((stream) => stream.kind === "subtitle")}
            selections={tracks}
            onUpdate={updateTrack}
          />
          {unclassifiedRetainedSubtitles.length > 0 && (
            <Notice tone="warning" title={t("Felirattípus megadása szükséges", "Subtitle type required")}>
              <p>{t(
                `${unclassifiedRetainedSubtitles.length} megtartott felirat még „Ellenőrizendő” állapotban van.`,
                `${unclassifiedRetainedSubtitles.length} kept subtitle(s) still marked “Needs check”.`,
              )}</p>
              <p>{t(
                "Minden megtartott feliratnál válaszd a „Teljes felirat” vagy a „Forced / signs” típust. Ha a sáv nem kell, válaszd a „Kihagyás” lehetőséget. Ezután válik elérhetővé a Tovább gomb.",
                "For every kept subtitle choose “Full subtitle” or “Forced / signs”. If the track is not needed, choose “Omit”. The Next button then becomes available.",
              )}</p>
            </Notice>
          )}
          {unresolvedTracks.length > 0 && (
            <Notice tone="warning" title={t("Hiányzó nyelv", "Missing language")}>
              {t(
                `${unresolvedTracks.length} megtartott sáv nyelve bizonytalan. Megadhatod most, vagy a hangot a worker beszédmintákból próbálja azonosítani; PGS feliratnál kézi megadás szükséges.`,
                `The language of ${unresolvedTracks.length} kept track(s) is uncertain. You can set it now, or the worker tries to identify audio from speech samples; PGS subtitles must be set by hand.`,
              )}
            </Notice>
          )}
        </div>
      )}

      {step === 3 && playlist && (
        <div className="video-settings-layout">
          <div className="video-settings-main">
            {needsColorConfirmation && (
              <SourceColorConfirmation
                video={videoStream?.video}
                discKind={scan.disc_kind}
                missing={reportedMissingColorFields}
                value={colorDraft}
                confirmed={colorConfirmed}
                safeRecommendation={safeColorRecommendation}
                onChange={(next) => {
                  setColorDraft(next);
                  setColorConfirmed(false);
                  setSettings((current) => {
                    const updated = { ...current };
                    delete updated.color;
                    return updated;
                  });
                  clearPlanFeedback();
                }}
                onConfirm={confirmSourceColor}
              />
            )}
            <Card className="settings-card ai-adviser-card">
              <div className="section-heading">
                <div><span className="section-heading__icon"><Sparkles size={19} /></span><div><h3>{t("AI beállítási tanácsadó", "AI settings adviser")}</h3><p>{t("A scan és a saját minőségi célod alapján", "Based on the scan and your own quality goal")}</p></div></div>
                {aiChosen?.configured && <Badge tone="success">{aiChosen.model}</Badge>}
              </div>
              <Notice tone="info" title={t("Mit kap meg az AI?", "What does the AI receive?")}>
                {t(
                  `Csak a kiválasztott playlist technikai scanadatait és az alábbi célleírást küldi el a(z) ${aiChosen?.label ?? "OpenAI"} API-nak. A film, képkockák, fájlútvonalak és API-kulcs nem kerülnek a kérés tartalmába. A válasz csak szerkeszthető javaslat; alkalmazás és planner-ellenőrzés nélkül nem indulhat kódolás.`,
                  `Only the technical scan data of the selected playlist and the goal description below are sent to the ${aiChosen?.label ?? "OpenAI"} API. The film, frames, file paths and API key are not part of the request. The answer is only an editable suggestion; no encode can start without applying it and passing the planner check.`,
                )}
              </Notice>
              {aiStatus.isError ? (
                <Notice tone="danger">{t("Az AI állapota nem kérdezhető le. Frissítsd az oldalt, vagy ellenőrizd a backend verzióját.", "The AI status cannot be queried. Reload the page or check the backend version.")}</Notice>
              ) : aiStatus.isLoading ? (
                <ProgressBar value={0.35} label={t("AI elérhetőségének ellenőrzése…", "Checking AI availability…")} />
              ) : !aiChosen?.configured ? (
                <Notice tone="warning" title={t("AI API-kulcs szükséges", "AI API key required")}>
                  {t("Az AI-ajánlóhoz OpenAI- vagy Claude-kulcs kell: a ", "The AI adviser needs an OpenAI or Claude key: set it on the ")}
                  <strong>{t("Rendszer", "System")}</strong>
                  {t(
                    " oldal AI tanácsadó kártyáján adhatod meg. Addig a hagyományos, determinisztikus ajánlott profil használható.",
                    " page, on the AI adviser card. Until then the classic, deterministic recommended profile is available.",
                  )}
                </Notice>
              ) : null}
              {aiConfigured.length > 1 && (
                <label className="field ai-provider-choice">
                  <span>{t("AI szolgáltató", "AI provider")}</span>
                  <select value={aiProvider ?? ""} onChange={(event) => { setAiProvider(event.target.value as AIProvider); aiRecommendation.reset(); }}>
                    {aiConfigured.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.model}</option>)}
                  </select>
                </label>
              )}
              <div className="ai-goal-grid">
                <label className="field">
                  <span>{t("Minőség és méret prioritása", "Quality vs. size priority")}</span>
                  <select value={aiQualityPriority} onChange={(event) => { setAiQualityPriority(event.target.value as AIQualityPriority); aiRecommendation.reset(); }}>
                    <option value="maximum">{t("Maximális minőség / archiválás", "Maximum quality / archival")}</option>
                    <option value="balanced">{t("Kiegyensúlyozott minőség és méret", "Balanced quality and size")}</option>
                    <option value="compact">{t("Kisebb fájl az elsődleges", "Smaller file first")}</option>
                  </select>
                </label>
                <label className="field">
                  <span>{t("Kívánt méret (GiB, opcionális)", "Desired size (GiB, optional)")}</span>
                  <input type="number" min="0.1" max="500" step="0.1" value={aiTargetSize} onChange={(event) => { setAiTargetSize(event.target.value); aiRecommendation.reset(); }} placeholder={t("pl. 12", "e.g. 12")} />
                  <small>{t("CRF esetén ez irány, nem garantált végleges méret.", "With CRF this is a direction, not a guaranteed final size.")}</small>
                </label>
                <label className="field">
                  <span>{t("Műfaj / képjellemzők (opcionális)", "Genre / picture traits (optional)")}</span>
                  <input maxLength={120} value={aiGenre} onChange={(event) => { setAiGenre(event.target.value); aiRecommendation.reset(); }} placeholder={t("pl. szemcsés film noir, anime, koncert", "e.g. grainy film noir, anime, concert")} />
                </label>
                <label className="field ai-goal-prompt">
                  <span>{t("Saját kérés az AI-nak", "Your own request to the AI")}</span>
                  <textarea maxLength={2000} rows={4} value={aiPrompt} onChange={(event) => { setAiPrompt(event.target.value); aiRecommendation.reset(); }} placeholder={t("Írd le, milyen eredményt szeretnél…", "Describe the result you want…")} />
                </label>
              </div>
              <Button
                className="ai-recommend-button"
                icon={<WandSparkles size={17} />}
                loading={aiRecommendation.isPending}
                disabled={!aiStatus.data?.configured || !playlistId}
                onClick={() => aiRecommendation.mutate()}
              >
                {t("AI-javaslat kérése", "Ask for an AI suggestion")}
              </Button>
              {aiRecommendation.isError && (
                <Notice tone="danger" title={t("Az AI-javaslat nem készült el", "The AI suggestion failed")}>
                  {aiRecommendation.error instanceof ApiError ? aiRecommendation.error.detail : t("Ismeretlen hiba történt.", "An unknown error occurred.")}
                </Notice>
              )}
              {aiRecommendation.data && (
                <div className="ai-recommendation-result">
                  <div className="ai-recommendation-result__heading">
                    <div><span className="eyebrow">{t(`AI-javaslat · ${Math.round(aiRecommendation.data.confidence * 100)}% bizonyosság`, `AI suggestion · ${Math.round(aiRecommendation.data.confidence * 100)}% confidence`)}</span><h4>{aiRecommendation.data.summary}</h4></div>
                    <Badge tone="info">{aiRecommendation.data.model}</Badge>
                  </div>
                  {aiRecommendation.data.rationale.length > 0 && <ul>{aiRecommendation.data.rationale.map((item) => <li key={item}>{item}</li>)}</ul>}
                  {aiRecommendation.data.warnings.length > 0 && (
                    <Notice tone="warning" title={t("Fontos korlátok", "Important limits")}>
                      <ul>{aiRecommendation.data.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
                    </Notice>
                  )}
                  <Button variant="secondary" icon={<Check size={17} />} onClick={applyAIRecommendation}>{t("Javaslat alkalmazása a mezőkre", "Apply suggestion to the fields")}</Button>
                  {aiApplied && <Notice tone="success">{t("Az AI-javaslat bekerült a szerkeszthető mezőkbe. A végleges szerveroldali ellenőrzés továbbra is kötelező.", "The AI suggestion was loaded into the editable fields. The final server-side check is still required.")}</Notice>}
                </div>
              )}
            </Card>
            <Card className="settings-card">
              <div className="section-heading">
                <div><span className="section-heading__icon"><WandSparkles size={19} /></span><div><h3>{t("Ajánlott profil", "Recommended profile")}</h3><p>{t("A scan és a tartalomtípus alapján", "Based on the scan and the content type")}</p></div></div>
                <div className="detail-switch" role="group" aria-label={t("Profil részletessége", "Profile detail level")}>
                  {(["beginner", "advanced", "pro"] as DetailLevel[]).map((level) => (
                    <button type="button" key={level} className={detailLevel === level ? "active" : ""} aria-pressed={detailLevel === level} onClick={() => { setDetailLevel(level); setValidation(null); aiRecommendation.reset(); setAiApplied(false); }}>
                      {level === "beginner" ? t("Kezdő", "Beginner") : level === "advanced" ? t("Haladó", "Advanced") : t("Profi", "Pro")}
                    </button>
                  ))}
                </div>
              </div>
              {schema.isError || recommendation.isError ? (
                <Notice tone="danger">{t("A profil sémája vagy ajánlása nem tölthető be. Próbáld újra az oldal frissítése után.", "The profile schema or recommendation cannot be loaded. Try again after reloading the page.")}</Notice>
              ) : schema.isLoading || recommendation.isLoading ? <ProgressBar value={0.45} label={t("Profil betöltése…", "Loading profile…")} /> : (
                <ProfileFields
                  fields={schema.data?.fields ?? []}
                  encoder={encoder}
                  settings={settings}
                  recommendation={recommendation.data?.settings ?? {}}
                  search={settingsSearch}
                  onSearch={setSettingsSearch}
                  onUpdate={updateSetting}
                  onSettings={updateSettings}
                />
              )}
            </Card>

            <QualityOptions
              encoder={encoder}
              contentType={job.content_type}
              sourceVideo={videoStream?.video ?? undefined}
              temporalFilter={temporalFilter}
              autoCrf={autoCrf}
              onAutoCrf={(value) => { setAutoCrf(value); clearPlanFeedback(); }}
              dynamicHdr={dynamicHdr}
              onDynamicHdr={(value) => { setDynamicHdr(value); clearPlanFeedback(); }}
              onApplyNoiseProfile={applyNoiseProfile}
            />

            <ProfileLibraryPanel
              encoder={encoder}
              detailLevel={detailLevel}
              settings={settings}
              autoCrf={autoCrf}
              dynamicHdr={dynamicHdr}
              onApply={(selection) => applyLibraryProfile(selection)}
            />

            <Card className="settings-card">
              <div className="section-heading">
                <div><span className="section-heading__icon"><ScanLine size={19} /></span><div><h3>{t("Képkocka-kezelés és crop", "Frame handling and crop")}</h3><p>{videoStream?.video?.width}×{videoStream?.video?.height} · {videoStream?.video?.field_order || t("ismeretlen mezősorrend", "unknown field order")}</p></div></div>
              </div>
              {sourceInterlaced && <Notice tone="warning">{t("A scan váltottsoros forrást jelzett. Ellenőrizd, hogy IVTC vagy deinterlace szükséges-e; ezt nem biztonságos teljesen automatikusan eldönteni.", "The scan reported an interlaced source. Check whether IVTC or deinterlacing is needed; this is not safe to decide fully automatically.")}</Notice>}
              <Notice tone="info" title={t("Automatikus crop", "Automatic crop")}>
                {t(
                  "Ha mind a négy érték 0, a worker a teljes film képkockáit átvizsgálja, és automatikusan alkalmazza a biztonságosan kimutatható fekete sávok levágását. Kézzel csak akkor állítsd, ha szándékosan felül akarod írni az automatikus döntést.",
                  "If all four values are 0, the worker scans the frames of the whole film and automatically crops the black bars it can detect safely. Set them by hand only if you deliberately want to override the automatic decision.",
                )}
              </Notice>
              <label className="field">
                <span>{t("Időbeli szűrés", "Temporal filtering")}</span>
                <select value={temporalFilter} onChange={(event) => { setTemporalFilter(event.target.value); setValidation(null); }}>
                  <option value="progressive">{t("Progresszív — nincs időbeli szűrés", "Progressive — no temporal filtering")}</option>
                  <option value="ivtc_tff">{t("IVTC — felső mező először", "IVTC — top field first")}</option>
                  <option value="ivtc_bff">{t("IVTC — alsó mező először", "IVTC — bottom field first")}</option>
                  <option value="bwdif_tff">{t("BWDIF — felső mező először", "BWDIF — top field first")}</option>
                  <option value="bwdif_bff">{t("BWDIF — alsó mező először", "BWDIF — bottom field first")}</option>
                  <option value="hybrid_safe_bob_tff">{t("Hibrid safe bob — TFF", "Hybrid safe bob — TFF")}</option>
                  <option value="hybrid_safe_bob_bff">{t("Hibrid safe bob — BFF", "Hybrid safe bob — BFF")}</option>
                </select>
              </label>
              <CropEditor crop={crop} width={videoStream?.video?.width ?? 1920} height={videoStream?.video?.height ?? 1080} onChange={(next) => { setCrop(next); setValidation(null); }} />
            </Card>
          </div>

          <aside className="video-settings-side">
            <Card className="source-facts-card">
              <span className="eyebrow">{t("Scanből rögzítve", "Fixed by the scan")}</span>
              <h3>{t("Forrásparaméterek", "Source parameters")}</h3>
              <dl className="summary-list">
                <div><dt>{t("Kimeneti kodek", "Output codec")}</dt><dd>{encoder}</dd></div>
                <div><dt>{t("Forrás", "Source")}</dt><dd>{videoStream?.video?.codec?.toUpperCase() || "—"}</dd></div>
                <div><dt>{t("Bitmélység", "Bit depth")}</dt><dd>{videoStream?.video?.bit_depth ?? "—"} bit</dd></div>
                <div><dt>{t("Képsebesség", "Frame rate")}</dt><dd>{videoStream?.video?.frame_rate || "—"}</dd></div>
                <div><dt>{t("Színtér", "Colour space")}</dt><dd>{videoStream?.video?.color_primaries || "—"}</dd></div>
                <div><dt>HDR10</dt><dd>{videoStream?.video?.hdr10 ? t("Megtartva", "Kept") : t("Nincs", "None")}</dd></div>
              </dl>
              {videoStream?.video?.dolby_vision && <Notice tone="warning">{t("Alapértelmezetten a Dolby Vision nem kerül megtartásra (a HDR10 alréteg lesz a kimenet); a „Minőségi opciók” szakaszban kérhető a megtartás.", "By default Dolby Vision is not kept (the output is the HDR10 base layer); you can ask to keep it in the “Quality options” section.")}</Notice>}
            </Card>
          </aside>
        </div>
      )}

      {step === 4 && (
        <div className="review-layout">
          <Card className="review-main-card">
            <span className="eyebrow">{t("Végleges ellenőrzés", "Final check")}</span>
            <h3>{job.name}</h3>
            <div className="review-summary-grid">
              <div><ListVideo size={18} /><span><small>Playlist</small><strong>{playlistId} · {formatDuration(playlist?.duration_seconds)}</strong></span></div>
              <div><Music size={18} /><span><small>{t("Megtartott sávok", "Kept tracks")}</small><strong>{retainedTracks.length}</strong></span></div>
              <div><Settings2 size={18} /><span><small>{t("Videóprofil", "Video profile")}</small><strong>{encoder} · {detailLevel}</strong></span></div>
              <div><Sparkles size={18} /><span><small>Comparison</small><strong>I / P / B · PNG</strong></span></div>
            </div>

            <label className="field">
              <span>{t("Kimeneti fájlnév", "Output file name")}</span>
              <div className="input-suffix"><input value={outputName} onChange={(event) => { setOutputName(event.target.value); setValidation(null); }} /><span>.mkv</span></div>
            </label>
            <div className="release-name-tools">
              <label className="field">
                <span>{t("Release-tag (csoport)", "Release tag (group)")}</span>
                <input aria-label={t("Release-tag", "Release tag")} maxLength={32} value={releaseTag} placeholder={t("pl. TAG", "e.g. TAG")} onChange={(event) => setReleaseTag(event.target.value)} />
                <small>{t("A böngésző megjegyzi. Aither-névben „-TAG”, magyar névben „HUN-TAG” alakban jelenik meg.", "The browser remembers it. It appears as “-TAG” in an Aither name and as “HUN-TAG” in a Hungarian name.")}</small>
              </label>
              <Button variant="secondary" icon={<Tag size={17} />} onClick={suggestReleaseName}>
                {t("Név javaslata", "Suggest name")} ({namingStyle(trackerProfile) === "hungarian" ? t("magyar szabvány", "Hungarian standard") : "Aither"})
              </Button>
            </div>

            <div className="review-options">
              <label className="toggle-row">
                <span><strong>{t("Képfeltöltés és BBCode", "Image upload and BBCode")}</strong><small>{t("Automatikus módban a sorrend: ImgBB, Catbox, majd Freeimage; a sikeres szolgáltató az egész csomagra rögzül.", "In automatic mode the order is ImgBB, Catbox, then Freeimage; the first host that succeeds is used for the whole set.")}</small></span>
                <input type="checkbox" checked={uploadImages} onChange={(event) => { setUploadImages(event.target.checked); setValidation(null); }} /><span className="toggle" aria-hidden="true" />
              </label>
              <label className="field">
                <span>{t("Képtárhely", "Image host")}</span>
                <select aria-label={t("Képtárhely", "Image host")} value={selectedImageProvider} disabled={!uploadImages} onChange={(event) => { setSelectedImageProvider(event.target.value as ImageUploadProvider); setValidation(null); }}>
                  {Object.entries(IMAGE_UPLOAD_PROVIDER_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <small>{t("Automatikus módban csak az első sikeres kép előtt válthat szolgáltatót; kézi módban nincs failover.", "In automatic mode the host can only change before the first successful image; manual mode has no failover.")}</small>
              </label>
              <label className="field">
                <span>{t("Feltöltött képek", "Uploaded images")}</span>
                <select aria-label={t("Feltöltött képek köre", "Set of uploaded images")} value={selectedImageSet} disabled={!uploadImages} onChange={(event) => { setSelectedImageSet(event.target.value as UploadImageSet); setValidation(null); }}>
                  {Object.entries(UPLOAD_IMAGE_SET_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <small>{t("HDR-filmnél minden képpárnak natív és SDR-re leképezett nézete is van; az egyik elhagyása felezi a feltöltést. A helyi PNG-k mind megmaradnak.", "For an HDR film every image pair has a native and an SDR tone-mapped view; leaving one out halves the upload. All local PNGs are kept.")}</small>
              </label>
              <label className="toggle-row">
                <span><strong>{t("Szigorú I/P/B típusazonosság · kötelező", "Strict I/P/B type match · required")}</strong><small>{t("Progresszív forrásnál a source és az encode képtípusa mindig azonos; ez nem kapcsolható ki.", "For a progressive source the source and encode frame types always match; this cannot be turned off.")}</small></span>
                <input type="checkbox" checked disabled aria-label={t("Szigorú I/P/B típusazonosság kötelező", "Strict I/P/B type match required")} /><span className="toggle" aria-hidden="true" />
              </label>
            </div>

            {!validation && (
              <Notice tone="info" title={t("Még nincs jóváhagyva", "Not approved yet")}>{t("Az „Ellenőrzés” gomb a backend valódi plannerével validálja a sávokat, cropot, HDR-t és x264/x265 paramétereket, de még nem indít kódolást.", "The “Check plan” button validates the tracks, crop, HDR and x264/x265 parameters with the backend's real planner, but does not start encoding yet.")}</Notice>
            )}
            {needsColorConfirmation && !colorConfirmed && (
              <Notice tone="warning" title={t("A forrás színadatait még jóvá kell hagynod", "You still need to approve the source colour data")}>
                <p>{t("A lemezből hiányzik:", "Missing from the disc:")} {reportedMissingColorFields.map((field) => SOURCE_COLOR_FIELD_LABELS[field]).join(", ")}.</p>
                <p>{safeColorRecommendation
                  ? t("A forrás jellemzői alapján ajánlott biztonságos értékeket egy érintéssel jóváhagyhatod; ez nem végez színkonverziót.", "You can approve the safe values recommended from the source's properties in one click; this does no colour conversion.")
                  : t("Ehhez a forráshoz nem adható biztonságos automatikus alapérték. Nyisd meg a mezőket, és csak ellenőrzött értékeket adj meg.", "No safe automatic default exists for this source. Open the fields and enter verified values only.")}</p>
                {safeColorRecommendation
                  ? <Button variant="secondary" icon={<Palette size={17} />} onClick={confirmSourceColor}>{t("Ajánlott értékek jóváhagyása", "Approve recommended values")}</Button>
                  : <Button variant="secondary" icon={<Palette size={17} />} onClick={() => setStep(3)}>{t("Színadatok kézi megadása", "Enter colour data by hand")}</Button>}
              </Notice>
            )}
            {validate.isError && !colorApiIssue && !subtitleClassificationApiIssue && !audioSubtitleFieldsApiIssue && <Notice tone="danger" title={t("A terv nem indítható", "The plan cannot start")}>{validate.error instanceof ApiError ? validate.error.detail : validate.error.message}</Notice>}
            {validate.isError && colorApiIssue && (
              <Notice tone="danger" title={t("Hiányos forrás-színinformáció", "Incomplete source colour information")}>
                <p>{t("A kódolás biztonsága érdekében erősítsd meg ezeket:", "For a safe encode, confirm these:")} {reportedMissingColorFields.map((field) => SOURCE_COLOR_FIELD_LABELS[field]).join(", ")}.</p>
                <Button variant="secondary" onClick={() => setStep(3)}>{t("Színadatok megnyitása", "Open colour data")}</Button>
              </Notice>
            )}
            {validate.isError && subtitleClassificationApiIssue && (
              <Notice tone="danger" title={t("Hiányzik egy megtartott felirat típusa", "A kept subtitle has no type")}>
                <p>{t(
                  "A megtartott feliratok egyikénél sincs megengedve az „Ellenőrizendő” állapot. Mindegyiket sorold be „Teljes felirat” vagy „Forced / signs” típusba, illetve hagyd ki, ha nincs rá szükség.",
                  "“Needs check” is not allowed for any kept subtitle. Classify each one as “Full subtitle” or “Forced / signs”, or omit it if it is not needed.",
                )}</p>
                <Button variant="secondary" onClick={() => setStep(2)}>{t("Feliratok megnyitása", "Open subtitles")}</Button>
              </Notice>
            )}
            {validate.isError && audioSubtitleFieldsApiIssue && (
              <Notice tone="danger" title={t("A hangsáv hibás feliratjelölést tartalmazott", "An audio track carried subtitle flags")}>
                <p>{t(
                  "A „forced” és a felirattípus csak feliratokhoz használható. A felület ezeket most automatikusan eltávolítja a hangsávokból.",
                  "“Forced” and the subtitle type apply to subtitles only. The interface now removes them from the audio tracks automatically.",
                )}</p>
                <Button variant="secondary" onClick={() => validate.mutate()} loading={validate.isPending}>{t("Terv újraellenőrzése", "Check plan again")}</Button>
              </Notice>
            )}
            {save.isError && <Notice tone="danger" title={t("A jóváhagyás nem menthető", "The approval cannot be saved")}>{save.error instanceof ApiError ? save.error.detail : save.error.message}</Notice>}
          </Card>

          <Card className={validation ? "validation-card validation-card--success" : "validation-card"}>
            <span className="validation-card__icon">{validation ? <Check size={26} /> : <SlidersHorizontal size={26} />}</span>
            <span className="eyebrow">{t("Szerveroldali planner", "Server-side planner")}</span>
            <h3>{validation ? t("A terv érvényes", "The plan is valid") : t("Ellenőrzésre vár", "Waiting for check")}</h3>
            <p>{validation
              ? t("A tényleges effektív profil elkészült. Jóváhagyás után a munka kész paraméterekkel beáll a kódolási sorba.", "The effective profile is ready. Once approved, the job joins the encoding queue with its final parameters.")
              : t("A backend ugyanazzal a logikával ellenőriz, amelyet a worker kódoláskor használ.", "The backend checks with the same logic the worker uses when encoding.")}</p>
            {validation && (
              <>
                <dl className="summary-list">
                  <div><dt>{t("Kódoló", "Encoder")}</dt><dd>{validation.encoder}</dd></div>
                  <div><dt>CRF</dt><dd>{String(validation.settings.crf)}</dd></div>
                  <div><dt>Preset</dt><dd>{String(validation.settings.preset)}</dd></div>
                  <div><dt>{t("Profil", "Profile")}</dt><dd>{String(validation.settings.profile)}</dd></div>
                  <div><dt>Crop</dt><dd>{Object.values(validation.crop).join(" / ")}</dd></div>
                </dl>
                {validation.advisory_warnings.length > 0 && <Notice tone="warning"><ul>{validation.advisory_warnings.map((item) => <li key={item}>{item}</li>)}</ul></Notice>}
                {(validation.tracker_findings?.length ?? 0) > 0 && (
                  <Notice tone="warning" title={t(`${TRACKER_PROFILE_LABELS[(validation.tracker_profile as TrackerProfile) ?? trackerProfile] ?? "Tracker"}-szabályok`, `${TRACKER_PROFILE_LABELS[(validation.tracker_profile as TrackerProfile) ?? trackerProfile] ?? "Tracker"} rules`)}>
                    <ul>{validation.tracker_findings?.map((item) => <li key={item.code + item.message}>{item.severity === "info" ? "ℹ️ " : ""}{item.message}</li>)}</ul>
                  </Notice>
                )}
                {validation.tracker_profile && validation.tracker_profile !== "none" && (validation.tracker_findings?.length ?? 0) === 0 && (
                  <Notice tone="success">{t(`A sávterv megfelel a(z) ${TRACKER_PROFILE_LABELS[validation.tracker_profile as TrackerProfile] ?? validation.tracker_profile} szabályainak.`, `The track plan meets the ${TRACKER_PROFILE_LABELS[validation.tracker_profile as TrackerProfile] ?? validation.tracker_profile} rules.`)}</Notice>
                )}
                <details className="command-preview"><summary><Copy size={15} /> {t("FFmpeg videóparaméterek", "FFmpeg video parameters")}</summary><code>{validation.ffmpeg_video_args.join(" ")}</code></details>
              </>
            )}
            {!validation ? (
              <Button icon={<Check size={17} />} onClick={() => validate.mutate()} loading={validate.isPending} disabled={needsColorConfirmation && !colorConfirmed}>{t("Terv ellenőrzése", "Check plan")}</Button>
            ) : (
              <Button icon={<Clapperboard size={18} />} onClick={() => save.mutate()} loading={save.isPending}>{t("Jóváhagyás és automatikus indítás", "Approve and start automatically")}</Button>
            )}
          </Card>
        </div>
      )}

      <div className="wizard-footer">
        <Button variant="ghost" icon={<ArrowLeft size={17} />} onClick={() => setStep((value) => Math.max(1, value - 1))} disabled={step === 1}>{t("Vissza", "Back")}</Button>
        {step < 4 && <Button icon={<ArrowRight size={17} />} onClick={() => { setStep((value) => Math.min(4, value + 1)); setValidation(null); }} disabled={!canNext}>{t("Tovább", "Next")}</Button>}
      </div>
    </div>
  );
}

function sourceColorOptions(): Record<SourceColorField, Array<{ value: string; label: string }>> {
  return {
    primaries: [
      { value: "bt709", label: "BT.709" },
      { value: "bt2020", label: "BT.2020" },
      { value: "smpte170m", label: "SMPTE 170M" },
      { value: "smpte240m", label: "SMPTE 240M" },
      { value: "bt470m", label: "BT.470 M" },
      { value: "bt470bg", label: "BT.470 BG" },
    ],
    transfer: [
      { value: "bt709", label: "BT.709" },
      { value: "smpte2084", label: "PQ / SMPTE ST 2084" },
      { value: "arib-std-b67", label: "HLG / ARIB STD-B67" },
      { value: "smpte170m", label: "SMPTE 170M" },
      { value: "smpte240m", label: "SMPTE 240M" },
      { value: "bt470m", label: "BT.470 M" },
      { value: "bt470bg", label: "BT.470 BG" },
      { value: "linear", label: t("Lineáris", "Linear") },
    ],
    matrix: [
      { value: "bt709", label: "BT.709" },
      { value: "bt2020nc", label: t("BT.2020 nem konstans fényesség", "BT.2020 non-constant luminance") },
      { value: "bt2020c", label: t("BT.2020 konstans fényesség", "BT.2020 constant luminance") },
      { value: "smpte170m", label: "SMPTE 170M" },
      { value: "bt470bg", label: "BT.470 BG" },
      { value: "rgb", label: "RGB" },
    ],
    range: [
      { value: "limited", label: t("Korlátozott / TV", "Limited / TV") },
      { value: "full", label: t("Teljes / PC", "Full / PC") },
    ],
    chroma_location: [
      { value: "left", label: t("Bal", "Left") },
      { value: "center", label: t("Közép", "Centre") },
      { value: "topleft", label: t("Bal felső", "Top left") },
      { value: "top", label: t("Felső", "Top") },
      { value: "bottomleft", label: t("Bal alsó", "Bottom left") },
      { value: "bottom", label: t("Alsó", "Bottom") },
    ],
  };
}

function SourceColorConfirmation({
  video,
  discKind,
  missing,
  value,
  confirmed,
  safeRecommendation,
  onChange,
  onConfirm,
}: {
  video: MediaStream["video"] | undefined;
  discKind: DiscScanResult["disc_kind"];
  missing: SourceColorField[];
  value: SourceColorMetadata;
  confirmed: boolean;
  safeRecommendation: boolean;
  onChange: (value: SourceColorMetadata) => void;
  onConfirm: () => void;
}) {
  const profileName = discKind === "uhd" && video?.hdr10
    ? "HDR10 UHD Blu-ray · BT.2020 / PQ"
    : "SDR Blu-ray · BT.709";
  const fields = Object.keys(SOURCE_COLOR_FIELD_LABELS) as SourceColorField[];
  const colorOptions = sourceColorOptions();
  const complete = Object.values(value).every((item) => Boolean(item));
  const manualReason = discKind === "uhd" && !video?.hdr10
    ? t("Az SDR UHD-forrás színtere nem következtethető ki biztonságosan a lemeztípusból.", "The colour space of an SDR UHD source cannot be inferred safely from the disc type.")
    : t("Automatikus BT.709 csak legalább 1280×720-as, 8 bites SDR Blu-ray forráshoz használható biztonságosan.", "Automatic BT.709 is only safe for an 8-bit SDR Blu-ray source of at least 1280×720.");

  return (
    <Card className={confirmed ? "source-color-card source-color-card--confirmed" : "source-color-card"}>
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Palette size={19} /></span>
          <div>
            <h3>{t("Forrás színinformációjának megerősítése", "Confirm source colour information")}</h3>
            <p>{t("A scan nem tudott minden kötelező jelölést kiolvasni", "The scan could not read every required flag")}</p>
          </div>
        </div>
        <Badge tone={confirmed ? "success" : "warning"}>{confirmed ? t("Jóváhagyva", "Approved") : t("Teendő", "To do")}</Badge>
      </div>

      <div className="source-color-missing" aria-label={t("Hiányzó forrásadatok", "Missing source data")}>
        <strong>{t("Hiányzik a lemezből:", "Missing from the disc:")}</strong>
        <div>{missing.map((field) => <Badge key={field} tone="warning">{SOURCE_COLOR_FIELD_LABELS[field]}</Badge>)}</div>
      </div>

      <Notice tone={confirmed ? "success" : safeRecommendation ? "info" : "warning"} title={confirmed ? t("A színjelölés megerősítve", "Colour flags confirmed") : safeRecommendation ? t(`Ajánlott alapérték: ${profileName}`, `Recommended default: ${profileName}`) : t("Kézi ellenőrzés szükséges", "Manual check required")}>
        {confirmed
          ? t("A kódoló a jóváhagyott jelölést írja a kimenetbe. Színkonverzió nem történik.", "The encoder writes the approved flags into the output. No colour conversion happens.")
          : safeRecommendation
            ? t("A lemeztípus, a felbontás, a bitmélység és a HDR-jelzés alapján töltöttük ki. Nézd át, majd hagyd jóvá; ettől még nem indul el a kódolás.", "Filled in from the disc type, resolution, bit depth and HDR flag. Review, then approve; this does not start encoding yet.")
            : t(`${manualReason} Válaszd ki a lemez dokumentációjával vagy hiteles elemzéssel ellenőrzött értékeket.`, `${manualReason} Choose values verified against the disc's documentation or a reliable analysis.`)}
      </Notice>

      <details className="source-color-details" open={!confirmed}>
        <summary>{confirmed ? t("Jóváhagyott értékek megtekintése", "View approved values") : t("Ajánlott értékek ellenőrzése", "Review recommended values")}</summary>
        <div className="source-color-fields">
          {fields.map((field) => {
            const editable = missing.includes(field);
            const options = colorOptions[field];
            const knownOption = options.some((option) => option.value === value[field]);
            return (
              <label key={field} className="source-color-field">
                <span>
                  <strong>{SOURCE_COLOR_FIELD_LABELS[field]}</strong>
                  <small>{editable ? t("Hiányzott · ajánlott érték", "Was missing · recommended value") : t("A scanből rögzítve / BD-alapérték", "Fixed by the scan / BD default")}</small>
                </span>
                <select
                  value={value[field]}
                  disabled={!editable}
                  onChange={(event) => onChange({ ...value, [field]: event.target.value })}
                >
                  {!value[field] && <option value="">{t("— Válassz ellenőrzött értéket —", "— Choose a verified value —")}</option>}
                  {!knownOption && value[field] && <option value={value[field]}>{value[field]}</option>}
                  {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
            );
          })}
        </div>
      </details>

      {!confirmed && (
        <Button className="source-color-confirm" icon={<Check size={17} />} onClick={onConfirm} disabled={!complete}>
          {safeRecommendation ? t("Ezeknek az értékeknek a jóváhagyása", "Approve these values") : t("A kézzel ellenőrzött értékek jóváhagyása", "Approve the manually verified values")}
        </Button>
      )}
    </Card>
  );
}

function TrackTable({
  title,
  icon,
  streams,
  selections,
  onUpdate,
}: {
  title: string;
  icon: ReactNode;
  streams: MediaStream[];
  selections: TrackSelection[];
  onUpdate: (streamId: string, update: Partial<TrackSelection>) => void;
}) {
  return (
    <Card className="track-card">
      <div className="section-heading"><div><span className="section-heading__icon">{icon}</span><div><h3>{title}</h3><p>{t(`${streams.length} sáv a kiválasztott playlistben`, `${streams.length} track(s) in the selected playlist`)}</p></div></div></div>
      {!streams.length ? <p className="muted">{t("Nincs ilyen sáv.", "No such tracks.")}</p> : (
        <div className="track-table">
          {streams.map((stream) => {
            const selection = selections.find((item) => item.stream_id === stream.id);
            if (!selection) {
              return <Notice key={stream.id} tone="danger">{t(`A(z) ${stream.id} sávhoz nem készült választási terv. Válaszd ki újra a playlistet.`, `No selection plan was made for track ${stream.id}. Select the playlist again.`)}</Notice>;
            }
            const declaredLanguage = detectedLanguage(stream);
            const uncertain = !declaredLanguage || stream.language?.needs_review;
            const actionDetails = audioActionDetails(selection.action);
            const sourceDetails = [
              stream.codec.toUpperCase(),
              stream.codec_profile,
              stream.channels ? t(`${stream.channels} csatorna`, `${stream.channels} channels`) : null,
              stream.channel_layout,
              stream.sample_rate ? `${stream.sample_rate / 1000} kHz` : null,
              stream.bit_depth ? `${stream.bit_depth} bit` : null,
              stream.object_audio ? t("objektumalapú hang", "object-based audio") : null,
            ].filter(Boolean).join(" · ");
            return (
              <div key={stream.id} className={selection.action === "omit" ? "track-row track-row--omitted" : "track-row"}>
                <div className="track-row__identity">
                  <span className="track-row__type">{stream.kind === "audio" ? <Music size={17} /> : <Subtitles size={17} />}</span>
                  <span><strong>{stream.title || t(`${stream.codec.toUpperCase()} sáv`, `${stream.codec.toUpperCase()} track`)}</strong><small>{sourceDetails}</small></span>
                </div>
                <label className="track-language">
                  <Languages size={16} aria-hidden="true" />
                  <input
                    value={selection.language || ""}
                    onChange={(event) => onUpdate(stream.id, { language: event.target.value.trim() || null })}
                    placeholder={declaredLanguage ? t(`forrás: ${declaredLanguage}`, `source: ${declaredLanguage}`) : t("pl. hun / yue / cmn", "e.g. hun / yue / cmn")}
                    maxLength={35}
                    aria-label={t(`${stream.title || stream.id} nyelve`, `${stream.title || stream.id} language`)}
                  />
                  {uncertain && <span role="img" aria-label={t("Bizonytalan vagy hiányzó nyelv", "Uncertain or missing language")} title={t("Bizonytalan vagy hiányzó nyelv", "Uncertain or missing language")}><AlertTriangle size={15} aria-hidden="true" /></span>}
                </label>
                <label className="track-language">
                  <input
                    value={selection.name || ""}
                    onChange={(event) => onUpdate(stream.id, { name: event.target.value.trim() || null })}
                    placeholder={stream.kind === "audio" ? t("pl. Cantonese Original Mix", "e.g. Cantonese Original Mix") : t("pl. English Forced / SDH", "e.g. English Forced / SDH")}
                    maxLength={120}
                    aria-label={t(`${stream.title || stream.id} sávneve`, `${stream.title || stream.id} track name`)}
                  />
                </label>
                <div className={stream.kind === "audio" ? "track-actions track-actions--audio" : "track-actions"} role="group" aria-label={t(`${stream.title || stream.id} kezelése`, `${stream.title || stream.id} handling`)}>
                  {(stream.kind === "audio" ? AUDIO_TRACK_ACTIONS : ["copy", "omit"] as TrackAction[]).map((action) => (
                    <button type="button" key={action} className={selection.action === action ? "active" : ""} aria-pressed={selection.action === action} onClick={() => onUpdate(stream.id, { action: action as TrackAction })}>
                      {audioActionDetails(action).label}
                    </button>
                  ))}
                </div>
                {stream.kind === "audio" && <div className="track-target-note"><strong>{actionDetails.label}:</strong> {actionDetails.description}</div>}
                {selection.action !== "omit" && (
                  <div className="track-flags">
                    <label><input type="checkbox" checked={selection.default} onChange={(event) => onUpdate(stream.id, { default: event.target.checked })} /> {t("Alapértelmezett", "Default")}</label>
                    {stream.kind === "subtitle" && (
                      <label>
                        {t("Felirattípus", "Subtitle type")}
                        <select
                          value={selection.subtitle_kind || "unknown"}
                          onChange={(event) => {
                            const kind = event.target.value as "unknown" | "full" | "forced";
                            onUpdate(stream.id, {
                              subtitle_kind: kind,
                              forced: kind === "forced",
                            });
                          }}
                          aria-label={t(`${stream.title || stream.id} felirattípusa`, `${stream.title || stream.id} subtitle type`)}
                        >
                          <option value="unknown">{t("Ellenőrizendő", "Needs check")}</option>
                          <option value="full">{t("Teljes felirat", "Full subtitle")}</option>
                          <option value="forced">Forced / signs</option>
                        </select>
                      </label>
                    )}
                  </div>
                )}
                {stream.kind === "subtitle" && selection.action !== "omit" && selection.subtitle_kind === "unknown" && (
                  <div className="track-warning">{t("A forced/full besorolást tartalmi ellenőrzés után kötelező megadni; a forrás flagje önmagában nem elég.", "The forced/full classification must be set after checking the content; the source flag alone is not enough.")}</div>
                )}
                {stream.object_audio && AUDIO_TRANSCODE_ACTIONS.has(selection.action) && <div className="track-warning">{t("Átalakításkor az Atmos/DTS:X objektum-metaadat elvész; a csatornaalapú hangsáv marad meg.", "Converting drops the Atmos/DTS:X object metadata; the channel-based audio is kept.")}</div>}
                {stream.kind === "audio" && stream.channels && stream.channels > 6 && ["ac3", "eac3", "dts"].includes(selection.action) && <div className="track-warning">{t(`A ${stream.channels} csatornás forrás ennél a célnál ellenőrzötten 5.1-re lesz keverve.`, `The ${stream.channels}-channel source is downmixed to 5.1 (verified) for this target.`)}</div>}
                {stream.kind === "audio" && selection.action === "dts" && /dts/i.test(`${stream.codec} ${stream.codec_profile || ""}`) && /hd/i.test(`${stream.codec} ${stream.codec_profile || ""}`) && <div className="track-target-note">{t("A beágyazott DTS core újrakódolás nélkül lesz kinyerve.", "The embedded DTS core is extracted without re-encoding.")}</div>}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function ProfileFields({
  fields,
  encoder,
  settings,
  recommendation,
  search,
  onSearch,
  onUpdate,
  onSettings,
}: {
  fields: FieldSpec[];
  encoder: "x264" | "x265";
  settings: Record<string, unknown>;
  recommendation: Record<string, unknown>;
  search: string;
  onSearch: (value: string) => void;
  onUpdate: (field: FieldSpec, raw: string | boolean) => void;
  onSettings: Dispatch<SetStateAction<Record<string, unknown>>>;
}) {
  const filtered = fields.filter((field) => {
    if (LOCKED_FIELDS.has(field.name)) return false;
    const needle = search.trim().toLocaleLowerCase("hu");
    return !needle || `${field.name} ${fieldLabel(field.name)} ${field.description}`.toLocaleLowerCase("hu").includes(needle);
  });
  const grouped = filtered.reduce<Record<string, FieldSpec[]>>((result, field) => {
    (result[field.group] ??= []).push(field);
    return result;
  }, {});
  const groups = Object.entries(grouped);
  return (
    <>
      {fields.length > 14 && (
        <label className="search-field settings-search"><Search size={16} aria-hidden="true" /><input aria-label={t("Kódolóparaméter keresése", "Search encoder parameters")} value={search} onChange={(event) => onSearch(event.target.value)} placeholder={t("Paraméter keresése…", "Search parameters…")} /></label>
      )}
      <div className="profile-groups">
        {groups.map(([group, groupFields]) => (
          <ProfileGroup key={group} initiallyOpen={group === "rate_control" || group === "gop" || fields.length < 15}>
            <summary><span>{groupLabel(group)}</span><Badge>{groupFields.length}</Badge><ChevronDown size={17} /></summary>
            <div className="profile-fields">
              {groupFields.map((field) => field.name === "vbv" ? (
                <VbvField key={field.name} value={settings.vbv} onChange={(value) => onSettings((current) => ({ ...current, vbv: value }))} />
              ) : (
                <ProfileField key={field.name} field={field} encoder={encoder} value={settings[field.name] ?? recommendation[field.name] ?? field.default} onUpdate={onUpdate} />
              ))}
            </div>
          </ProfileGroup>
        ))}
      </div>
    </>
  );
}

function ProfileGroup({ initiallyOpen, children }: { initiallyOpen: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <details className="profile-group" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      {children}
    </details>
  );
}

function ProfileField({ field, value, encoder, onUpdate }: { field: FieldSpec; value: unknown; encoder: "x264" | "x265"; onUpdate: (field: FieldSpec, raw: string | boolean) => void }) {
  const inputId = useId();
  const label = fieldLabel(field.name);
  const help = FIELD_HELP[field.name];
  const description = encoderHelp(field.name)?.what || (help ? tx(help) : "") || field.description;
  // The help button stays outside the <label>: a button inside it would
  // become the label's control instead of the input.
  const heading = (
    <span>
      <strong><label htmlFor={inputId}>{label}</label><FieldHelpButton field={field.name} encoder={encoder} /></strong>
      {description && <small>{description}</small>}
    </span>
  );
  if (field.value_type === "boolean" && field.optional) {
    // Unset leaves the preset's own value; a toggle cannot express that.
    return (
      <div className="parameter-field">
        {heading}
        <select id={inputId} value={value === true ? "true" : value === false ? "false" : ""} onChange={(event) => onUpdate(field, event.target.value)}>
          <option value="">{t("Preset szerint", "Preset default")}</option>
          <option value="true">{t("Be", "On")}</option>
          <option value="false">{t("Ki", "Off")}</option>
        </select>
      </div>
    );
  }
  if (field.value_type === "boolean") {
    return (
      <div className="parameter-field parameter-field--toggle">
        {heading}
        <label className="parameter-field__switch">
          <input id={inputId} type="checkbox" checked={Boolean(value)} onChange={(event) => onUpdate(field, event.target.checked)} /><span className="toggle" aria-hidden="true" />
        </label>
      </div>
    );
  }
  return (
    <div className="parameter-field">
      {heading}
      {field.value_type === "enum" ? (
        <select id={inputId} value={String(value ?? "")} onChange={(event) => onUpdate(field, event.target.value)}>
          {field.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
        </select>
      ) : (
        <input
          id={inputId}
          type={field.value_type === "number" || field.value_type === "integer" ? "number" : "text"}
          value={String(value ?? "")}
          placeholder={field.optional ? t("preset szerint", "preset default") : undefined}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          step={field.value_type === "integer" ? 1 : field.value_type === "number" ? 0.05 : undefined}
          onChange={(event) => onUpdate(field, event.target.value)}
        />
      )}
    </div>
  );
}

function VbvField({ value, onChange }: { value: unknown; onChange: (value: unknown) => void }) {
  const enabled = Boolean(value && typeof value === "object");
  const current = enabled ? value as Record<string, unknown> : {};
  return (
    <div className="parameter-field parameter-field--object">
      <label className="toggle-row toggle-row--compact">
        <span><strong>{t("VBV korlátozás", "VBV limit")}</strong><small>{t("Csak konkrét lejátszói/level kompatibilitási igénynél szükséges.", "Only needed for a specific player or level compatibility requirement.")}</small></span>
        <input type="checkbox" checked={enabled} onChange={(event) => onChange(event.target.checked ? { maxrate_kbps: 40000, bufsize_kbps: 50000, initial_fullness: 0.9 } : null)} /><span className="toggle" />
      </label>
      {enabled && <div className="object-fields">
        <label>Maxrate (kb/s)<input type="number" value={String(current.maxrate_kbps ?? 40000)} onChange={(event) => onChange({ ...current, maxrate_kbps: Number(event.target.value) })} /></label>
        <label>Buffer (kb)<input type="number" value={String(current.bufsize_kbps ?? 50000)} onChange={(event) => onChange({ ...current, bufsize_kbps: Number(event.target.value) })} /></label>
        <label>{t("Kezdeti telítettség", "Initial fullness")}<input type="number" min="0" max="1" step="0.05" value={String(current.initial_fullness ?? 0.9)} onChange={(event) => onChange({ ...current, initial_fullness: Number(event.target.value) })} /></label>
      </div>}
    </div>
  );
}

function CropEditor({
  crop,
  width,
  height,
  onChange,
}: {
  crop: { left: number; top: number; right: number; bottom: number };
  width: number;
  height: number;
  onChange: (value: { left: number; top: number; right: number; bottom: number }) => void;
}) {
  const sourceWidth = Math.max(2, width || 1920);
  const sourceHeight = Math.max(2, height || 1080);
  const maxHorizontal = Math.max(0, Math.floor(sourceWidth / 3 / 2) * 2);
  const maxVertical = Math.max(0, Math.floor(sourceHeight / 3 / 2) * 2);
  const innerWidth = Math.max(2, 100 - ((crop.left + crop.right) / sourceWidth) * 100);
  const innerHeight = Math.max(2, 100 - ((crop.top + crop.bottom) / sourceHeight) * 100);
  const normalizeCrop = (raw: string, maximum: number) =>
    Math.min(maximum, Math.max(0, Math.round((Number(raw) || 0) / 2) * 2));
  const automatic = crop.left === 0 && crop.top === 0 && crop.right === 0 && crop.bottom === 0;
  return (
    <div className="crop-editor">
      <div className="crop-mode" role="status">
        {automatic ? (
          <Badge tone="success">{t("Automatikus crop — a worker a teljes filmből méri", "Automatic crop — the worker measures it over the whole film")}</Badge>
        ) : (
          <>
            <Badge tone="warning">{t("Kézi crop — felülírja az automatikus mérést", "Manual crop — overrides the automatic measurement")}</Badge>
            <Button variant="ghost" onClick={() => onChange({ left: 0, top: 0, right: 0, bottom: 0 })}>
              {t("Vissza automatikusra", "Back to automatic")}
            </Button>
          </>
        )}
      </div>
      <div className="crop-preview" style={{ aspectRatio: `${sourceWidth} / ${sourceHeight}` }}>
        <div className="crop-preview__frame" style={{
          left: `${(crop.left / sourceWidth) * 100}%`,
          right: `${(crop.right / sourceWidth) * 100}%`,
          top: `${(crop.top / sourceHeight) * 100}%`,
          bottom: `${(crop.bottom / sourceHeight) * 100}%`,
        }}>
          <span>{Math.round(sourceWidth - crop.left - crop.right)} × {Math.round(sourceHeight - crop.top - crop.bottom)}</span>
        </div>
        <div className="crop-preview__grid" />
        <small>{t(`${innerWidth.toFixed(0)}% × ${innerHeight.toFixed(0)}% megmarad`, `${innerWidth.toFixed(0)}% × ${innerHeight.toFixed(0)}% kept`)}</small>
      </div>
      <div className="crop-controls">
        {(["top", "bottom", "left", "right"] as const).map((side) => {
          const max = side === "top" || side === "bottom" ? maxVertical : maxHorizontal;
          const label = side === "top" ? t("Fent", "Top") : side === "bottom" ? t("Lent", "Bottom") : side === "left" ? t("Bal", "Left") : t("Jobb", "Right");
          return (
            <div className="crop-control" key={side}>
              <span>{label}<input aria-label={t(`${label} crop pixelben`, `${label} crop in pixels`)} type="number" min="0" max={max} step="2" value={crop[side]} onChange={(event) => onChange({ ...crop, [side]: normalizeCrop(event.target.value, max) })} /></span>
              <input aria-label={t(`${label} crop csúszka`, `${label} crop slider`)} type="range" min="0" max={max} step="2" value={crop[side]} onChange={(event) => onChange({ ...crop, [side]: normalizeCrop(event.target.value, max) })} />
            </div>
          );
        })}
      </div>
      <small className="field-help">{t("0 / 0 / 0 / 0 = automatikus crop. A kézi értékek páros pixelekre állnak; a backend minden esetben ellenőrzi a forrásméretet és a kimeneti kompatibilitást.", "0 / 0 / 0 / 0 = automatic crop. Manual values snap to even pixels; the backend always checks the source size and output compatibility.")}</small>
    </div>
  );
}
