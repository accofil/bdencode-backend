import type { MediaStream, Playlist, TrackSelection } from "./api/types";
import { t } from "./i18n";
import { audioCodecFamily, type TrackerProfile } from "./releaseName";

/** Formats an nCore 1080p encode may not carry: they become E-AC3 (DD+) 5.1, 1024 kbps. */
const NCORE_1080P_FORBIDDEN = new Set(["TRUEHD", "DTSHDMA", "DTSHDHRA", "DTSX", "LPCM"]);

const ISO639_2_TO_BCP47: Record<string, string> = {
  hun: "hu", eng: "en", ger: "de", deu: "de", fre: "fr", fra: "fr", ita: "it", spa: "es",
  jpn: "ja", kor: "ko", chi: "zh", zho: "zh", rus: "ru", pol: "pl", cze: "cs", ces: "cs",
};

interface Entry {
  track: TrackSelection;
  stream: MediaStream;
  position: number;
  language: string;
  commentary: boolean;
  dub: boolean;
}

export interface TrackerArrangement {
  tracks: TrackSelection[];
  /** Notes on what changed, for the wizard, in the current interface language. */
  notes: string[];
}

function languageOf(track: TrackSelection, stream: MediaStream): string {
  const code = (track.language ?? "").toLowerCase();
  if (code) return ISO639_2_TO_BCP47[code] ?? code.split("-")[0];
  const bcp47 = stream.language?.bcp47 ?? "";
  return bcp47 ? bcp47.split("-")[0].toLowerCase() : "und";
}

function entries(tracks: TrackSelection[], playlist: Playlist, kind: "audio" | "subtitle"): Entry[] {
  const position = new Map(playlist.streams.map((stream, index) => [stream.id, index]));
  return tracks.flatMap((track) => {
    const stream = playlist.streams.find((item) => item.id === track.stream_id);
    if (!stream || stream.kind !== kind) return [];
    return [{
      track,
      stream,
      position: position.get(stream.id) ?? 0,
      language: languageOf(track, stream),
      commentary: stream.roles.includes("commentary"),
      dub: stream.roles.includes("dub"),
    }];
  }).sort((left, right) => left.position - right.position);
}

function originalLanguage(audio: Entry[]): string | null {
  const spoken = audio.filter((item) => !item.commentary);
  return (spoken.find((item) => !item.dub && item.language !== "und")
    ?? spoken.find((item) => item.language !== "hu" && item.language !== "und")
    ?? spoken[0])?.language ?? null;
}

const LANGUAGE_NAMES: Record<string, { hu: string; en: string }> = {
  hu: { hu: "magyar", en: "Hungarian" },
  en: { hu: "angol", en: "English" },
  de: { hu: "német", en: "German" },
  fr: { hu: "francia", en: "French" },
  it: { hu: "olasz", en: "Italian" },
  es: { hu: "spanyol", en: "Spanish" },
  ja: { hu: "japán", en: "Japanese" },
};
const languageName = (code: string) => {
  const name = LANGUAGE_NAMES[code];
  return name ? t(name.hu, name.en) : code;
};

/**
 * Rearrange a track plan for a tracker's rules: allowed languages and formats,
 * output order and the default audio.  Choices the operator already made to
 * omit a track are kept; everything changed is explained in ``notes``.
 */
export function arrangeForTracker(
  profile: TrackerProfile,
  tracks: TrackSelection[],
  playlist: Playlist,
  encoder: "x264" | "x265",
): TrackerArrangement {
  if (profile === "none") return { tracks, notes: [] };
  const notes: string[] = [];
  const updates = new Map<string, Partial<TrackSelection>>();
  const update = (id: string, change: Partial<TrackSelection>) => updates.set(id, { ...updates.get(id), ...change });

  const audio = entries(tracks, playlist, "audio");
  const original = originalLanguage(audio);
  const permitted = profile === "ncore"
    ? new Set(["hu", "en", "de", ...(original ? [original] : [])])
    : new Set(["en", ...(original ? [original] : [])]);
  const actionOf = (item: Entry) => updates.get(item.track.stream_id)?.action ?? item.track.action;

  // The original-language track is mandatory; nCore is about the Hungarian dub as well.
  for (const language of profile === "ncore" ? ["hu", original] : [original]) {
    if (!language || audio.some((item) => !item.commentary && item.language === language && actionOf(item) !== "omit")) continue;
    const candidate = audio.find((item) => !item.commentary && item.language === language && (language === "hu" || !item.dub))
      ?? audio.find((item) => !item.commentary && item.language === language);
    if (!candidate) continue;
    update(candidate.track.stream_id, { action: "copy" });
    notes.push(t(
      `A(z) ${languageName(language)} hang bekerült a tervbe${language === original ? " (az eredeti nyelvű hang kötelező)" : ""}.`,
      `The ${languageName(language)} audio was added to the plan${language === original ? " (the original-language audio is mandatory)" : ""}.`,
    ));
  }

  for (const item of audio) {
    if (actionOf(item) === "omit") continue;
    if (!item.commentary && !permitted.has(item.language)) {
      update(item.track.stream_id, { action: "omit" });
      notes.push(t(
        `A(z) ${languageName(item.language)} hang kimarad: ${profile === "ncore" ? "az nCore csak magyar, angol, német és eredeti nyelvű hangot enged" : "Aitheren csak az eredeti és az angol hang mehet"}.`,
        `The ${languageName(item.language)} audio is omitted: ${profile === "ncore" ? "nCore only allows Hungarian, English, German and original-language audio" : "Aither only allows the original and English audio"}.`,
      ));
      continue;
    }
    const family = audioCodecFamily(item.stream.codec, item.stream.codec_profile);
    if (profile === "ncore" && encoder === "x264" && actionOf(item) === "copy" && NCORE_1080P_FORBIDDEN.has(family)) {
      update(item.track.stream_id, { action: "eac3" });
      const downmix = (item.stream.channels ?? 0) > 6;
      notes.push(t(
        `A(z) ${languageName(item.language)} ${item.stream.codec_profile || item.stream.codec} sáv E-AC3 (DD+) 5.1, 1024 kbps lesz: 1080p-n az nCore nem engedi a veszteségmentes hangot.${downmix ? " A 7.1 5.1-re keveredik (FFmpeg-gel 7.1-es E-AC3 nem készíthető)." : ""}`,
        `The ${languageName(item.language)} ${item.stream.codec_profile || item.stream.codec} track becomes E-AC3 (DD+) 5.1, 1024 kbps: nCore does not allow lossless audio at 1080p.${downmix ? " The 7.1 is downmixed to 5.1 (FFmpeg cannot make 7.1 E-AC3)." : ""}`,
      ));
    }
  }

  // TrueHD on Blu-ray carries its own AC-3 core (same PID): it is the compatibility track
  // both trackers want (nCore: DD@640, Aither: DD/DD+), kept as it is.
  const compatFor = new Map<string, Entry>();
  for (const item of audio) {
    if (actionOf(item) !== "copy" || audioCodecFamily(item.stream.codec, item.stream.codec_profile) !== "TRUEHD" || item.stream.pid === null) continue;
    const core = audio.find((other) => other !== item && other.stream.pid === item.stream.pid && other.stream.codec.toLowerCase() === "ac3");
    if (!core) continue;
    compatFor.set(item.track.stream_id, core);
    if (actionOf(core) !== "copy") {
      update(core.track.stream_id, { action: "copy" });
      notes.push(t(
        `A(z) ${languageName(item.language)} TrueHD AC3-magja kompatibilitási sávként megmarad (újrakódolás nélkül).`,
        `The AC3 core of the ${languageName(item.language)} TrueHD is kept as the compatibility track (without re-encoding).`,
      ));
    }
  }
  const cores = new Set([...compatFor.values()].map((item) => item.track.stream_id));

  const kept = audio.filter((item) => actionOf(item) !== "omit" && !cores.has(item.track.stream_id));
  const rank = (item: Entry): number => {
    if (item.commentary) return 9;
    if (profile === "ncore" && item.language === "hu") return 0;
    if (item.language === original) return 1;
    if (item.language === "en") return 2;
    return 3;
  };
  const orderedAudio = [...kept]
    .sort((left, right) => rank(left) - rank(right) || left.position - right.position)
    .flatMap((item) => {
      const core = compatFor.get(item.track.stream_id);
      return core ? [item, core] : [item];
    });
  orderedAudio.forEach((item, index) => update(item.track.stream_id, { order: index, default: index === 0 }));
  if (orderedAudio.length && orderedAudio[0].position !== Math.min(...kept.map((item) => item.position))) {
    notes.push(t(
      `Az első és alapértelmezett hang: ${languageName(orderedAudio[0].language)}.`,
      `First and default audio: ${languageName(orderedAudio[0].language)}.`,
    ));
  }

  const subtitles = entries(tracks, playlist, "subtitle");
  const dubbed = new Set(orderedAudio.filter((item) => !item.commentary).map((item) => item.language));
  const subtitleRank = (item: Entry): number => {
    const kind = item.track.subtitle_kind === "forced" ? 0 : item.stream.roles.includes("sdh") ? 2 : 1;
    if (profile === "ncore" && item.language === "hu") return kind;
    if (item.language === original) return 3 + kind;
    if (profile === "aither" && item.language === "en") return 3 + kind;
    return 6 + kind;
  };
  const keptSubtitles = subtitles.filter((item) => {
    if (item.track.action === "omit") return false;
    if (profile === "ncore" && item.track.subtitle_kind === "forced" && !dubbed.has(item.language)) {
      update(item.track.stream_id, { action: "omit" });
      notes.push(t(
        `A(z) ${languageName(item.language)} forced felirat kimarad: az nCore csak szinkronnal rendelkező nyelvhez enged forced feliratot.`,
        `The ${languageName(item.language)} forced subtitle is omitted: nCore only allows forced subtitles for a language with a dub.`,
      ));
      return false;
    }
    return true;
  });
  [...keptSubtitles]
    .sort((left, right) => subtitleRank(left) - subtitleRank(right) || left.position - right.position)
    .forEach((item, index) => update(item.track.stream_id, { order: orderedAudio.length + index }));

  // Omitted tracks go to the end, in disc order, so every order stays unique.
  let next = orderedAudio.length + keptSubtitles.length;
  const omitted = [...audio, ...subtitles]
    .filter((item) => (updates.get(item.track.stream_id)?.action ?? item.track.action) === "omit")
    .sort((left, right) => left.position - right.position);
  for (const item of omitted) update(item.track.stream_id, { order: next++, ...(item.stream.kind === "audio" ? { default: false } : {}) });

  return {
    tracks: tracks.map((track) => ({ ...track, ...updates.get(track.stream_id) })),
    notes,
  };
}

/** Output order of the retained tracks, for display. */
export function plannedOrder(tracks: TrackSelection[], playlist: Playlist): Array<{ track: TrackSelection; stream: MediaStream }> {
  return [...tracks]
    .filter((track) => track.action !== "omit")
    .sort((left, right) => left.order - right.order)
    .flatMap((track) => {
      const stream = playlist.streams.find((item) => item.id === track.stream_id);
      return stream && stream.kind !== "video" ? [{ track, stream }] : [];
    });
}
