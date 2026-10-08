import type { DynamicHdrMode, Playlist, TrackSelection, VideoProperties } from "./api/types";
import { releaseTitleBase } from "./utils";

/** Which tracker's rules a job follows; "none" keeps the plain BDEncode behaviour. */
export type TrackerProfile = "none" | "aither" | "ncore";
export type NamingStyle = "aither" | "hungarian";

export const TRACKER_PROFILE_LABELS: Record<TrackerProfile, string> = {
  none: "Nincs (általános)",
  aither: "Aither",
  ncore: "nCore",
};

/** One planned output audio track, as a release name may describe it. */
export interface ReleaseAudio {
  codec: string;
  channels: number | null;
  atmos: boolean;
  language: string;
  commentary: boolean;
}

export interface ReleaseNameInput {
  /** Title and year, dot separated: "La.Femme.Nikita.1990". */
  base: string;
  encoder: "x264" | "x265";
  style: NamingStyle;
  audio: ReleaseAudio[];
  /** Any of SDR, HDR, HDR10+, DV, HLG. */
  dynamicRange: string[];
  tag?: string;
}

const RELEASE_TAG_KEY = "bdencode.release-tag";
const TAG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/;

const CODEC_TOKENS: Record<string, string> = {
  TRUEHD: "TrueHD",
  DTSHDMA: "DTS-HD.MA",
  DTSX: "DTS-X",
  DTSHDHRA: "DTS-HD.HRA",
  DTS: "DTS",
  DDP: "DDP",
  DD: "DD",
  FLAC: "FLAC",
  LPCM: "LPCM",
  AAC: "AAC",
  OPUS: "Opus",
};
// Scene habit: DDP5.1 / DD5.1 / AAC2.0, but TrueHD.7.1 / DTS-HD.MA.5.1.
const ATTACHED_CHANNELS = new Set(["DDP", "DD", "AAC"]);
const LOSSY_ACTIONS = new Set(["ac3", "eac3", "dts"]);
const ACTION_FAMILIES: Record<string, string> = { flac: "FLAC", ac3: "DD", eac3: "DDP", dts: "DTS" };

/** Aither puts the spoken language after the year when there is no English audio. */
const LANGUAGE_NAMES: Record<string, string> = {
  hu: "HUNGARIAN", fr: "FRENCH", de: "GERMAN", it: "ITALIAN", es: "SPANISH", pt: "PORTUGUESE",
  ru: "RUSSIAN", pl: "POLISH", cs: "CZECH", nl: "DUTCH", sv: "SWEDISH", da: "DANISH",
  no: "NORWEGIAN", nb: "NORWEGIAN", fi: "FINNISH", ja: "JAPANESE", ko: "KOREAN", zh: "CHINESE",
  cmn: "MANDARIN", yue: "CANTONESE", hi: "HINDI", th: "THAI", tr: "TURKISH", el: "GREEK",
};

const ISO639_2_TO_BCP47: Record<string, string> = {
  hun: "hu", eng: "en", fre: "fr", fra: "fr", ger: "de", deu: "de", ita: "it", spa: "es",
  por: "pt", rus: "ru", pol: "pl", cze: "cs", ces: "cs", dut: "nl", nld: "nl", swe: "sv",
  dan: "da", nor: "no", nob: "nb", fin: "fi", jpn: "ja", kor: "ko", chi: "zh", zho: "zh",
  cmn: "cmn", yue: "yue", hin: "hi", tha: "th", tur: "tr", gre: "el", ell: "el",
};

export function channelLayout(count: number | null | undefined): string | null {
  return ({ 1: "1.0", 2: "2.0", 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1" } as Record<number, string>)[count ?? 0] ?? null;
}

/** Name-level codec family of an untouched (copied) source stream; mirrors the backend. */
export function audioCodecFamily(codec: string, profile?: string | null): string {
  const name = (codec || "").toLowerCase();
  const detail = (profile || "").toUpperCase();
  if (name === "truehd" || name === "mlp") return "TRUEHD";
  if (name === "dts" || name === "dca") {
    if (detail.includes("DTS:X") || detail.includes("DTS-X")) return "DTSX";
    if (detail.includes("MA") && detail.includes("HD")) return "DTSHDMA";
    if (detail.includes("HRA") || (detail.includes("HD") && detail.includes("HR"))) return "DTSHDHRA";
    return "DTS";
  }
  if (name === "ac3") return "DD";
  if (name === "eac3") return "DDP";
  if (name === "flac") return "FLAC";
  if (name.startsWith("pcm")) return "LPCM";
  if (name === "aac") return "AAC";
  if (name === "opus") return "OPUS";
  return "OTHER";
}

function trackLanguage(track: TrackSelection, playlist: Playlist): string {
  const stream = playlist.streams.find((item) => item.id === track.stream_id);
  const code = (track.language ?? "").toLowerCase();
  if (code) return ISO639_2_TO_BCP47[code] ?? code.split("-")[0];
  const bcp47 = stream?.language?.bcp47 ?? "";
  return bcp47 ? bcp47.split("-")[0].toLowerCase() : "und";
}

/** Planned output audio, in output order, from the wizard's track plan. */
export function releaseAudio(tracks: TrackSelection[], playlist: Playlist): ReleaseAudio[] {
  const result: ReleaseAudio[] = [];
  for (const track of [...tracks].sort((left, right) => left.order - right.order)) {
    if (track.action === "omit") continue;
    const stream = playlist.streams.find((item) => item.id === track.stream_id);
    if (!stream || stream.kind !== "audio") continue;
    const copy = track.action === "copy";
    const channels = stream.channels ?? null;
    result.push({
      codec: copy ? audioCodecFamily(stream.codec, stream.codec_profile) : ACTION_FAMILIES[track.action] ?? "OTHER",
      channels: LOSSY_ACTIONS.has(track.action) && channels ? Math.min(channels, 6) : channels,
      atmos: copy && Boolean(stream.object_audio),
      language: trackLanguage(track, playlist),
      commentary: stream.roles.includes("commentary"),
    });
  }
  return result;
}

/** What the encode will be, mirroring the backend's dynamic HDR resolution. */
export function plannedDynamicRange(
  encoder: "x264" | "x265",
  video: VideoProperties | null | undefined,
  dynamicHdr: DynamicHdrMode,
  temporalFilter: string,
): string[] {
  if (encoder === "x264" || !video) return ["SDR"];
  const transfer = String(video.color_transfer ?? "").toLowerCase();
  const base = video.hdr10 ? "HDR" : transfer === "arib-std-b67" ? "HLG" : "SDR";
  const result = [base];
  if (!video.hdr10 || temporalFilter !== "progressive") return result;
  const dolbyVision = Boolean(video.dolby_vision && video.hdr10_base_layer && [7, 8].includes(Number(video.dolby_vision_profile)));
  if ((dynamicHdr === "hdr10plus" || dynamicHdr === "auto") && video.hdr10_plus) return [...result, "HDR10+"];
  if ((dynamicHdr === "dolby_vision" || dynamicHdr === "auto") && dolbyVision) return [...result, "DV"];
  return result;
}

function audioToken(audio: ReleaseAudio | undefined): string | null {
  if (!audio) return null;
  const token = CODEC_TOKENS[audio.codec];
  if (!token) return null;
  const layout = channelLayout(audio.channels);
  const withChannels = layout ? (ATTACHED_CHANNELS.has(audio.codec) ? `${token}${layout}` : `${token}.${layout}`) : token;
  return audio.atmos ? `${withChannels}.Atmos` : withChannels;
}

function dynamicTokens(dynamicRange: string[], style: NamingStyle): string[] {
  const has = (item: string) => dynamicRange.includes(item);
  const tokens: string[] = [];
  if (has("DV")) tokens.push("DV");
  if (has("HDR10+")) tokens.push(style === "hungarian" ? "HDR10Plus" : "HDR10+");
  else if (has("HDR")) tokens.push("HDR");
  else if (has("HLG")) tokens.push("HLG");
  return tokens;
}

export function sanitizeReleaseTag(value: string): string {
  const cleaned = value.trim().replace(/^-+/, "").replace(/[^A-Za-z0-9._-]+/g, "").slice(0, 32);
  return TAG_PATTERN.test(cleaned) ? cleaned : "";
}

/** Build a name the backend's release-name check accepts for the same plan. */
export function buildReleaseName(input: ReleaseNameInput): string {
  const resolution = input.encoder === "x265" ? "2160p.UHD.BluRay" : "1080p.BluRay";
  const codec = input.encoder;
  const tag = input.tag ? sanitizeReleaseTag(input.tag) : "";
  const group = tag ? `-${tag}` : "";
  const spoken = input.audio.filter((item) => !item.commentary);
  const languages = new Set(spoken.map((item) => item.language).filter((item) => item !== "und"));
  const parts: string[] = [];
  // A regenerated name must not repeat the language tag an earlier suggestion put after the year.
  const languageSuffix = new RegExp(`\\.(?:${[...new Set(Object.values(LANGUAGE_NAMES))].join("|")})$`, "i");
  const base = input.base.replace(languageSuffix, "") || input.base;
  if (input.style === "aither") {
    const main = spoken[0] ?? input.audio[0];
    const languageTag = main && !languages.has("en") ? LANGUAGE_NAMES[main.language] : undefined;
    parts.push(languageTag ? `${base}.${languageTag}` : base, resolution);
    if (main && main.language !== "en" && languages.size === 2 && languages.has("en")) parts.push("Dual-Audio");
    const audio = audioToken(main);
    if (audio) parts.push(audio);
    parts.push(...dynamicTokens(input.dynamicRange, "aither"), codec);
    return `${parts.join(".")}${group}`;
  }
  // Hungarian standard: [title].[year].[res].[source].[dynrng].[audio].[codec].[HUN]-[group];
  // the audio codec describes the original-language track.
  const original = spoken.find((item) => item.language !== "hu") ?? spoken[0] ?? input.audio[0];
  parts.push(base, resolution, ...dynamicTokens(input.dynamicRange, "hungarian"));
  const audio = audioToken(original);
  if (audio) parts.push(audio);
  parts.push(codec);
  const hungarian = spoken.filter((item) => item.language === "hu").length;
  if (hungarian > 0 && original?.language !== "hu") parts.push(hungarian > 1 ? `${hungarian}xHUN` : "HUN");
  return `${parts.join(".")}${group}`;
}

/** The title part of an existing name: everything before the resolution, or a cleaned title. */
export function titleBaseOf(name: string): string {
  const match = /^(.+?)\.(?:1080p|2160p)\./i.exec(name.trim());
  return match ? match[1] : releaseTitleBase(name);
}

export function namingStyle(profile: TrackerProfile): NamingStyle {
  return profile === "ncore" ? "hungarian" : "aither";
}

export function rememberedReleaseTag(): string {
  try {
    return sanitizeReleaseTag(window.localStorage.getItem(RELEASE_TAG_KEY) ?? "");
  } catch {
    return "";
  }
}

export function rememberReleaseTag(tag: string): void {
  try {
    const cleaned = sanitizeReleaseTag(tag);
    if (cleaned) window.localStorage.setItem(RELEASE_TAG_KEY, cleaned);
    else window.localStorage.removeItem(RELEASE_TAG_KEY);
  } catch {
    // Storage may be unavailable (private window); the field still works for this page.
  }
}
