import { describe, expect, it } from "vitest";
import type { MediaStream, TrackAnalysis, TrackSelection } from "../api/types";
import { makeScan } from "../test/fixtures";
import { trackLanguageSettled } from "./SelectionWizard";

const base = makeScan().playlists[0].streams.find((stream) => stream.kind === "audio")!;
const subtitle = (language: MediaStream["language"]): MediaStream => ({ ...base, id: "subtitle:3", kind: "subtitle", codec: "hdmv_pgs_subtitle", language });
const keep = { stream_id: "subtitle:3", action: "copy", language: null } as unknown as TrackSelection;
const read = (iso639_2t: string, confidence: number): TrackAnalysis => ({
  schema_version: 2,
  subtitles: { "subtitle:3": { events: 40, sampled_seconds: 180, events_per_minute: 13, suggested_kind: "full", confidence: "high", language: { status: "detected", iso639_2t, confidence, method: "ocr" } } },
});
const label = (iso639_2t: string, needs_review: boolean) => ({ iso639_2t, bcp47: null, confidence: 0.8, needs_review }) as MediaStream["language"];

describe("trackLanguageSettled", () => {
  it("trusts a label that needs no review, and a hand-set language", () => {
    expect(trackLanguageSettled(subtitle(label("deu", false)), keep, undefined)).toBe(true);
    expect(trackLanguageSettled(subtitle(null), { ...keep, language: "hun" }, undefined)).toBe(true);
  });

  it("settles a label marked for review only when the captions confirm it", () => {
    // A remux MKV track: its Matroska tag alone is marked for review.
    expect(trackLanguageSettled(subtitle(label("deu", true)), keep, read("deu", 0.88))).toBe(true);
    expect(trackLanguageSettled(subtitle(label("deu", true)), keep, read("eng", 0.88))).toBe(false);
    expect(trackLanguageSettled(subtitle(label("deu", true)), keep, undefined)).toBe(false);
  });

  it("takes a clear reading for an unlabelled track, not a weak one", () => {
    expect(trackLanguageSettled(subtitle(null), keep, read("fra", 0.8))).toBe(true);
    expect(trackLanguageSettled(subtitle(null), keep, read("fra", 0.6))).toBe(false);
  });
});
