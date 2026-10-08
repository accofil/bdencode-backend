import { describe, expect, it } from "vitest";
import type { MediaStream, Playlist, TrackSelection } from "./api/types";
import { arrangeForTracker, plannedOrder } from "./trackerArrangement";

const stream = (id: string, kind: "audio" | "subtitle", codec: string, extra: Partial<MediaStream> = {}): MediaStream => ({
  id, index: 0, pid: null, kind, codec, codec_profile: null, language: null, title: null, channels: null,
  channel_layout: null, sample_rate: null, bit_depth: null, default: false, forced: false, roles: [],
  object_audio: false, video: null, ...extra,
});

const playlist = {
  streams: [
    stream("en", "audio", "truehd", { channels: 8, roles: ["main"], object_audio: true }),
    stream("hu", "audio", "dts", { channels: 6, codec_profile: "DTS", roles: ["dub"] }),
    stream("fr", "audio", "ac3", { channels: 6, roles: ["dub"] }),
    stream("comm", "audio", "ac3", { channels: 2, roles: ["commentary"] }),
    stream("de-forced", "subtitle", "hdmv_pgs_subtitle"),
    stream("en-full", "subtitle", "hdmv_pgs_subtitle"),
    stream("hu-full", "subtitle", "hdmv_pgs_subtitle"),
    stream("hu-forced", "subtitle", "hdmv_pgs_subtitle"),
  ],
} as unknown as Playlist;

const track = (stream_id: string, language: string, order: number, extra: Partial<TrackSelection> = {}): TrackSelection => ({
  stream_id, action: "copy", language, name: null, default: order === 0, order, ...extra,
});

const tracks: TrackSelection[] = [
  track("en", "eng", 0),
  track("hu", "hun", 1),
  track("fr", "fre", 2),
  track("comm", "eng", 3),
  track("de-forced", "ger", 4, { subtitle_kind: "forced" }),
  track("en-full", "eng", 5, { subtitle_kind: "full" }),
  track("hu-full", "hun", 6, { subtitle_kind: "full" }),
  track("hu-forced", "hun", 7, { subtitle_kind: "forced" }),
];

const byId = (list: TrackSelection[]) => Object.fromEntries(list.map((item) => [item.stream_id, item]));

describe("arrangeForTracker", () => {
  it("puts the Hungarian dub first for nCore and converts lossless audio at 1080p", () => {
    const result = arrangeForTracker("ncore", tracks, playlist, "x264");
    const arranged = byId(result.tracks);
    expect(arranged.fr.action).toBe("omit");
    expect(arranged.en.action).toBe("eac3");
    expect(arranged["de-forced"].action).toBe("omit");
    expect(plannedOrder(result.tracks, playlist).map((item) => item.stream.id)).toEqual([
      "hu", "en", "comm", "hu-forced", "hu-full", "en-full",
    ]);
    expect([arranged.hu.default, arranged.en.default, arranged.comm.default]).toEqual([true, false, false]);
    expect(result.notes.join(" ")).toMatch(/francia hang kimarad/);
    expect(result.notes.join(" ")).toMatch(/7\.1 5\.1-re keveredik/);
    expect(result.notes.join(" ")).toMatch(/német forced felirat kimarad/);
  });

  it("keeps lossless audio at 2160p for nCore", () => {
    expect(byId(arrangeForTracker("ncore", tracks, playlist, "x265").tracks).en.action).toBe("copy");
  });

  it("keeps only the original and English audio for Aither", () => {
    const result = arrangeForTracker("aither", tracks, playlist, "x265");
    const arranged = byId(result.tracks);
    expect([arranged.hu.action, arranged.fr.action, arranged.en.action]).toEqual(["omit", "omit", "copy"]);
    expect(plannedOrder(result.tracks, playlist).slice(0, 2).map((item) => item.stream.id)).toEqual(["en", "comm"]);
    expect(arranged.en.default).toBe(true);
  });

  it("brings back an omitted Hungarian dub and the original track", () => {
    const omitted = tracks.map((item) => (item.stream_id === "hu" || item.stream_id === "en" ? { ...item, action: "omit" as const } : item));
    const result = arrangeForTracker("ncore", omitted, playlist, "x265");
    const arranged = byId(result.tracks);
    expect([arranged.hu.action, arranged.en.action]).toEqual(["copy", "copy"]);
    expect(result.notes.join(" ")).toMatch(/magyar hang bekerült/);
    expect(result.notes.join(" ")).toMatch(/angol hang bekerült a tervbe \(az eredeti nyelvű hang kötelező\)/);
  });

  it("keeps the TrueHD's own AC-3 core right after it as the compatibility track", () => {
    const withCore = {
      streams: [
        stream("thd", "audio", "truehd", { pid: 4352, channels: 8, roles: ["main"] }),
        stream("thd-core", "audio", "ac3", { pid: 4352, channels: 6, roles: ["main"] }),
        stream("hu", "audio", "ac3", { pid: 4353, channels: 6, roles: ["dub"] }),
      ],
    } as unknown as Playlist;
    const plan = [track("thd", "eng", 0), track("thd-core", "eng", 1, { action: "omit" }), track("hu", "hun", 2)];
    const result = arrangeForTracker("ncore", plan, withCore, "x265");
    expect(plannedOrder(result.tracks, withCore).map((item) => item.stream.id)).toEqual(["hu", "thd", "thd-core"]);
    expect(result.notes.join(" ")).toMatch(/AC3-magja kompatibilitási sávként megmarad/);
    // At 1080p the TrueHD becomes E-AC3 itself, so its core is not added.
    const converted = arrangeForTracker("ncore", plan, withCore, "x264");
    expect(byId(converted.tracks)["thd-core"].action).toBe("omit");
  });

  it("changes nothing without a tracker profile", () => {
    expect(arrangeForTracker("none", tracks, playlist, "x264")).toEqual({ tracks, notes: [] });
  });

  it("gives every track a unique order", () => {
    const orders = arrangeForTracker("ncore", tracks, playlist, "x264").tracks.map((item) => item.order);
    expect(new Set(orders).size).toBe(orders.length);
  });
});
