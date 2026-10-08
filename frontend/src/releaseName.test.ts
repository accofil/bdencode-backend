import { describe, expect, it } from "vitest";
import type { MediaStream, Playlist, TrackSelection, VideoProperties } from "./api/types";
import {
  buildReleaseName,
  plannedDynamicRange,
  releaseAudio,
  sanitizeReleaseTag,
  titleBaseOf,
  type ReleaseAudio,
} from "./releaseName";
import { releaseTitleBase } from "./utils";

const audio = (codec: string, channels: number, language: string, extra: Partial<ReleaseAudio> = {}): ReleaseAudio => ({
  codec, channels, language, atmos: false, commentary: false, ...extra,
});

// Every name below is also accepted by tests/test_release_naming.py for the same plan.
describe("buildReleaseName", () => {
  it("writes the Aither order with a language tag when there is no English audio", () => {
    expect(buildReleaseName({
      base: "La.Femme.Nikita.1990", encoder: "x265", style: "aither",
      audio: [audio("DTSHDMA", 6, "fr")], dynamicRange: ["HDR", "DV"], tag: "TAG",
    })).toBe("La.Femme.Nikita.1990.FRENCH.2160p.UHD.BluRay.DTS-HD.MA.5.1.DV.HDR.x265-TAG");
  });

  it("marks an original track plus an English dub as Dual-Audio", () => {
    expect(buildReleaseName({
      base: "Movie.2020", encoder: "x265", style: "aither",
      audio: [audio("TRUEHD", 8, "fr", { atmos: true }), audio("DD", 6, "en"), audio("DD", 2, "fr", { commentary: true })],
      dynamicRange: ["HDR", "HDR10+"], tag: "TAG",
    })).toBe("Movie.2020.2160p.UHD.BluRay.Dual-Audio.TrueHD.7.1.Atmos.HDR10+.x265-TAG");
  });

  it("writes the Hungarian order: dynamic range first, the original audio, then HUN", () => {
    expect(buildReleaseName({
      base: "Movie.2020", encoder: "x265", style: "hungarian",
      audio: [audio("DD", 6, "hu"), audio("TRUEHD", 8, "en", { atmos: true })],
      dynamicRange: ["HDR", "DV"], tag: "TAG",
    })).toBe("Movie.2020.2160p.UHD.BluRay.DV.HDR.TrueHD.7.1.Atmos.x265.HUN-TAG");
    expect(buildReleaseName({
      base: "Movie.2020", encoder: "x264", style: "hungarian",
      audio: [audio("DD", 6, "hu"), audio("DD", 2, "hu"), audio("DDP", 6, "en")],
      dynamicRange: ["SDR"], tag: "TAG",
    })).toBe("Movie.2020.1080p.BluRay.DDP5.1.x264.2xHUN-TAG");
  });

  it("does not repeat the language tag when a suggestion is regenerated", () => {
    expect(buildReleaseName({
      base: "La.Femme.Nikita.1990.FRENCH", encoder: "x265", style: "aither",
      audio: [audio("DTSHDMA", 6, "fr")], dynamicRange: ["HDR"], tag: "TAG",
    })).toBe("La.Femme.Nikita.1990.FRENCH.2160p.UHD.BluRay.DTS-HD.MA.5.1.HDR.x265-TAG");
  });

  it("leaves the group off without a tag and keeps a Hungarian original untagged", () => {
    expect(buildReleaseName({
      base: "Valami.Amerika.2002", encoder: "x264", style: "hungarian",
      audio: [audio("DD", 6, "hu")], dynamicRange: ["SDR"],
    })).toBe("Valami.Amerika.2002.1080p.BluRay.DD5.1.x264");
  });
});

describe("release name inputs", () => {
  const stream = (id: string, codec: string, channels: number, extra: Partial<MediaStream> = {}): MediaStream => ({
    id, index: 0, pid: null, kind: "audio", codec, codec_profile: null, language: { bcp47: "en" }, title: null,
    channels, channel_layout: null, sample_rate: 48000, bit_depth: null, default: false, forced: false,
    roles: [], object_audio: false, video: null, ...extra,
  });
  const playlist = {
    streams: [
      stream("a1", "truehd", 8, { object_audio: true }),
      stream("a2", "truehd", 8, { object_audio: true }),
      stream("a3", "ac3", 2, { roles: ["commentary"] }),
    ],
  } as unknown as Playlist;
  const track = (stream_id: string, action: TrackSelection["action"], order: number, language: string | null = null): TrackSelection => ({
    stream_id, action, order, language, name: null, default: false,
  });

  it("derives codec, channels, Atmos and language from the track plan", () => {
    expect(releaseAudio([track("a2", "eac3", 2, "hun"), track("a1", "copy", 1), track("a3", "copy", 3)], playlist)).toEqual([
      { codec: "TRUEHD", channels: 8, atmos: true, language: "en", commentary: false },
      { codec: "DDP", channels: 6, atmos: false, language: "hu", commentary: false },
      { codec: "DD", channels: 2, atmos: false, language: "en", commentary: true },
    ]);
  });

  it("resolves the dynamic range like the backend", () => {
    const hdr = { hdr10: true, hdr10_plus: true, dolby_vision: true, dolby_vision_profile: 7, hdr10_base_layer: true, color_transfer: "smpte2084" } as VideoProperties;
    expect(plannedDynamicRange("x265", hdr, "auto", "progressive")).toEqual(["HDR", "HDR10+"]);
    expect(plannedDynamicRange("x265", { ...hdr, hdr10_plus: false }, "auto", "progressive")).toEqual(["HDR", "DV"]);
    expect(plannedDynamicRange("x265", hdr, "dolby_vision", "ivtc_tff")).toEqual(["HDR"]);
    expect(plannedDynamicRange("x265", hdr, "discard", "progressive")).toEqual(["HDR"]);
    expect(plannedDynamicRange("x264", hdr, "auto", "progressive")).toEqual(["SDR"]);
  });

  it("cleans the release tag and the title base", () => {
    expect(sanitizeReleaseTag(" -My Group! ")).toBe("MyGroup");
    expect(sanitizeReleaseTag("---")).toBe("");
    expect(releaseTitleBase("Movie.2026.DTS-HD.MA.1080p.BluRay.x264")).toBe("Movie.2026");
    expect(releaseTitleBase("La Femme Nikita 1990 UHD BluRay")).toBe("La.Femme.Nikita.1990");
    expect(titleBaseOf("Mintafilm.1080p.BluRay.x264")).toBe("Mintafilm");
    expect(titleBaseOf("La.Femme.Nikita.1990.FRENCH.2160p.UHD.BluRay.x265-TAG")).toBe("La.Femme.Nikita.1990.FRENCH");
    expect(titleBaseOf("Some Disc Name 2001")).toBe("Some.Disc.Name.2001");
  });
});
