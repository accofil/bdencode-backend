import { describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { retiredScanWarning, stabilityWarning } from "./utils";

describe("MKV scan warnings", () => {
  it("are shown in Hungarian", () => {
    setLanguage("hu");
    expect(stabilityWarning(
      "The video stream carries a x264 encoder signature without disc authoring options: the file is most likely an encode, not an untouched disc remux.",
    )).toBe("A videófolyamban x264 kódoló aláírása van, lemezre írási beállítások nélkül: a fájl valószínűleg újrakódolás, nem érintetlen lemez-remux.");
    expect(stabilityWarning("Not part of the title and left out: cover image (stream 8, mjpeg), data stream 9."))
      .toBe("Nem része a filmnek, ezért kimarad: borítókép (8. sáv, mjpeg), data (9. sáv).");
  });

  it("stay as they are in English", () => {
    setLanguage("en");
    const message = "Not part of the title and left out: cover image (stream 8, mjpeg).";
    expect(stabilityWarning(message)).toBe(message);
    setLanguage("hu");
  });
});

describe("retired scan warnings", () => {
  it("hide the old SOURCE_ID warning of 3.10-3.12.0 scans", () => {
    expect(retiredScanWarning("The video track carries no SOURCE_ID tag (written by MakeMKV/mkvmerge from the disc); make sure the file is an untouched disc remux, not an encode.")).toBe(true);
    expect(retiredScanWarning("Not part of the title and left out: cover image (stream 8, mjpeg).")).toBe(false);
  });
});
