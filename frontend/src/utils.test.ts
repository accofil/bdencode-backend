import { describe, expect, it } from "vitest";
import { makeJob } from "./test/fixtures";
import { formatEventMessage, formatStatusMessage, formatWorkerError, isFastComparisonTimeoutReview, stageProgress, suggestedOutputName } from "./utils";

describe("formatEventMessage", () => {
  it("localizes historical worker messages", () => {
    expect(formatEventMessage("job.state", "reference timeline prepared"))
      .toBe("A referencia-idővonal elkészült");
  });

  it("uses a Hungarian event-kind label when no message exists", () => {
    expect(formatEventMessage("artifact.created", null)).toBe("Melléklet létrehozva");
    expect(formatEventMessage("artifact.created", "artifact.created")).toBe("Melléklet létrehozva");
  });

  it("preserves useful messages it does not recognize", () => {
    expect(formatEventMessage("job.selection", "Operátori beállítások jóváhagyva"))
      .toBe("Operátori beállítások jóváhagyva");
  });

  it("localizes the same historical text when it is the active status", () => {
    expect(formatStatusMessage("reference timeline prepared", "Állapotfrissítésre vár"))
      .toBe("A referencia-idővonal elkészült");
    expect(formatStatusMessage("FileNotFoundError: /job/work/chapters.xml", "Állapotfrissítésre vár"))
      .toMatch(/fejezetlista létrehozása/i);
    expect(formatStatusMessage("retrying failed MUXING stage", "Állapotfrissítésre vár"))
      .toBe("MKV összeállítása: biztonságos folytatás");
  });

  it("localizes the review and upload messages the job page resolves", () => {
    expect(formatStatusMessage("one or more retained tracks need a confirmed language before encoding", ""))
      .toBe("Egy vagy több megtartott sáv nyelvét meg kell erősíteni a kódolás előtt");
    expect(formatStatusMessage("comparison image 03-B-f000123456-encode.png (40.1 MB) exceeds the upload limit of the image host (imgbb 34 MB)", ""))
      .toBe("A(z) 03-B-f000123456-encode.png kép (40.1 MB) nagyobb a képtárhely korlátjánál: másik tárhellyel kell elölről kezdeni a feltöltést.");
    expect(formatStatusMessage("the image host rejected the upload: ImgBB HTTP 400: invalid; fix the cause", ""))
      .toMatch(/végleg elutasította/);
    expect(formatStatusMessage("sampled VMAF of the final file: mean 94.02, 1% low 84.95 (576 frames)", ""))
      .toBe("Mintavett VMAF a kész fájlon: átlag 94.02, 1% low 84.95 (576 képkocka)");
    expect(formatEventMessage("job.upload-reset", "job.upload-reset")).toBe("Képfeltöltés elölről");
  });

  it("explains the chapter retry failure without hiding its technical details", () => {
    expect(formatWorkerError("FileNotFoundError: /job/work/chapters.xml"))
      .toMatch(/fejezetlista létrehozása/i);
  });

  it("explains an audio spectrum failure as a safe QC continuation", () => {
    const failure = "ProcessFailure: ffmpeg -filter_complex showspectrumpic ... audio-01-source-spectrum.png";
    expect(formatWorkerError(failure)).toMatch(/spektrumképének elkészítése/i);
    expect(formatStatusMessage(failure, "Állapotfrissítésre vár"))
      .toMatch(/QC szakasztól biztonságosan folytatható/i);
  });

  it("localizes fast comparison progress and recognizes its resumable timeout", () => {
    expect(formatStatusMessage("fast comparison: preparing bounded samples", ""))
      .toBe("Gyors comparison: a rövid videóminták előkészítése");
    expect(formatStatusMessage("fast comparison: pair 3/5 complete", ""))
      .toBe("Gyors comparison: 3/5 képpár elkészült");
    const timeout = "fast comparison exceeded its bounded command/time budget";
    expect(isFastComparisonTimeoutReview(timeout)).toBe(true);
    expect(formatStatusMessage(timeout, "")).toMatch(/ötperces időkorlátot/i);
  });

  it("localizes the warnings that let a job continue", () => {
    expect(formatEventMessage(
      "worker.crop-verification-warning",
      "crop verification: 2 short flash(es) reach into the cropped border (3 frame(s), longest 0.08 s); the crop is kept and the job continues",
    )).toBe("Crop-ellenőrzés: 2 rövid felvillanás ér bele a levágott sávba (3 képkocka, a leghosszabb 0.08 mp). A crop marad, a job folytatódik.");
    for (const [kind, message] of [
      ["worker.subtitle-decode-warning", "the final subtitle decode shows known harmless differences; the job continues"],
      ["worker.video-duration-warning", "the estimated playlist duration differs from the frame count; the job continues"],
      ["worker.video-efficiency-warning", "the encoded video is not smaller than the source; the job continues"],
      ["worker.stream-policy-warning", "the final video stream is described differently by this FFmpeg build; the job continues"],
    ]) {
      expect(formatEventMessage(kind, message)).toMatch(/a job folytatódik/);
    }
    expect(formatEventMessage("worker.video-efficiency-warning", null)).toBe("Videóméret: figyelmeztetés");
  });

  it("uses backend pipeline baselines for legacy jobs without progress", () => {
    expect(stageProgress(makeJob({ state: "MUXING", progress: null }))).toBe(0.78);
    expect(stageProgress(makeJob({ state: "FAILED", resume_state: "MUXING", progress: null }))).toBe(0.78);
  });
});

describe("suggestedOutputName", () => {
  it("removes inherited COMPLETE/source-group and codec tails", () => {
    expect(suggestedOutputName("After.We.Fell.2021.COMPLETE.BLURAY-iNTEGRUM", "x264"))
      .toBe("After.We.Fell.2021.1080p.BluRay.x264");
    expect(suggestedOutputName("Assassination.Nation.2018.1080p.USA.Blu-ray.AVC.DTS-HD.MA.5.1-BeyondHD", "x264"))
      .toBe("Assassination.Nation.2018.1080p.BluRay.x264");
  });

  it("does not inherit MULTi and normalizes UHD output", () => {
    expect(suggestedOutputName("Amsterdamned.II.2025.MULTi.COMPLETE.BLURAY-MONUMENT", "x264"))
      .toBe("Amsterdamned.II.2025.1080p.BluRay.x264");
    expect(suggestedOutputName("Example Movie 2026 UHD REMUX", "x265"))
      .toBe("Example.Movie.2026.2160p.UHD.BluRay.x265");
  });
});
