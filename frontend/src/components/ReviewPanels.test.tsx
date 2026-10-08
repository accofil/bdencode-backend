import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { JobReview } from "../api/types";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { LanguageReviewCard, languageLabel, UploadReviewCard } from "./ReviewPanels";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      confirmTrackLanguages: vi.fn(),
      resetUpload: vi.fn(),
      retryUpload: vi.fn(),
    },
  };
});

const LANGUAGES = [
  { code: "eng", bcp47: "en" },
  { code: "hun", bcp47: "hu" },
  { code: "deu", bcp47: "de" },
];

function languageReview(): JobReview {
  return {
    state: "NEEDS_REVIEW",
    kind: "language",
    message: "one or more retained tracks need a confirmed language before encoding",
    details: {},
    resume_state: "ENCODING",
    upload: null,
    language: {
      languages: LANGUAGES,
      tracks: [
        {
          stream_id: "audio:4352", kind: "audio", codec: "truehd", channels: 8, title: "English Atmos",
          declared: "eng", detected: "eng", detected_confidence: 0.98, resolved: "eng", current: null,
          needs_confirmation: false, reason: null, suggested: "eng",
        },
        {
          stream_id: "audio:4353", kind: "audio", codec: "dts", channels: 6, title: null,
          declared: "eng", detected: "hun", detected_confidence: 0.91, resolved: null, current: null,
          needs_confirmation: true, reason: "language_conflict_or_low_confidence", suggested: "hun",
        },
        {
          stream_id: "subtitle:4608", kind: "subtitle", codec: "hdmv_pgs_subtitle", channels: null, title: null,
          declared: null, detected: null, detected_confidence: null, resolved: null, current: null,
          needs_confirmation: true, reason: "subtitle_ocr_or_manual_override_required", suggested: null,
        },
      ],
    },
  };
}

function uploadReview(overrides: Partial<JobReview> = {}): JobReview {
  return {
    state: "UPLOAD_FAILED",
    kind: "upload_failed",
    message: "image upload failed; retry is safe",
    details: {},
    resume_state: null,
    language: null,
    upload: {
      provider: "imgbb",
      uploaded_images: 7,
      largest_image_bytes: 40 * 1024 * 1024,
      override: { provider: null, image_set: null, upload_images: null },
      hosts: [
        { provider: "imgbb", max_upload_bytes: 32 * 1024 * 1024 },
        { provider: "catbox", max_upload_bytes: 200_000_000 },
        { provider: "freeimage", max_upload_bytes: 64 * 1024 * 1024 },
      ],
    },
    ...overrides,
  };
}

describe("review cards", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names languages in Hungarian and keeps unknown tags as codes", () => {
    expect(languageLabel("hun", "hu")).toBe("magyar (hun)");
    expect(languageLabel("xyz", null)).toBe("xyz");
  });

  it("confirms every retained track's language, starting from the suggestions", async () => {
    const user = userEvent.setup();
    const job = makeJob({ state: "NEEDS_REVIEW", version: 9 });
    vi.mocked(api.confirmTrackLanguages).mockResolvedValue(makeJob({ state: "READY", version: 10 }));
    renderApp(<LanguageReviewCard job={job} review={languageReview()} />);

    expect(screen.getByText("2 sáv kér döntést")).toBeInTheDocument();
    expect(screen.getByText(/lemez: angol \(eng\) · felismerés: magyar \(hun\) · 91%/)).toBeInTheDocument();
    expect(screen.getByText("A felirat nyelve a lemezről nem olvasható ki biztosan.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Hang · DTS · 5.1: nyelv" })).toHaveValue("hun");
    const confirm = screen.getByRole("button", { name: "Nyelvek megerősítése és folytatás" });
    // The subtitle has no clue at all: nothing is guessed for it.
    expect(confirm).toBeDisabled();

    await user.selectOptions(screen.getByRole("combobox", { name: "Felirat · PGS: nyelv" }), "hun");
    await user.click(confirm);

    await waitFor(() => expect(api.confirmTrackLanguages).toHaveBeenCalledWith(
      "job-1",
      { "audio:4352": "eng", "audio:4353": "hun", "subtitle:4608": "hun" },
      9,
    ));
  });

  it("retries a failed upload, resets it to another host or finishes without images", async () => {
    const user = userEvent.setup();
    const job = makeJob({ state: "UPLOAD_FAILED", version: 4, selection: { upload_image_set: "all" } });
    vi.mocked(api.retryUpload).mockResolvedValue(makeJob({ state: "UPLOADING", version: 5 }));
    vi.mocked(api.resetUpload).mockResolvedValue(makeJob({ state: "UPLOADING", version: 5 }));
    renderApp(<UploadReviewCard job={job} review={uploadReview()} credentials={{ imgbb: { configured: true }, freeimage: { configured: false } }} />);

    expect(within(screen.getByText("Rögzített tárhely").closest("div")!).getByText("ImgBB")).toBeInTheDocument();
    expect(within(screen.getByText("Már feltöltve").closest("div")!).getByText("7 kép")).toBeInTheDocument();
    const hosts = within(screen.getByRole("list", { name: "Képtárhelyek korlátai" })).getAllByRole("listitem");
    expect(within(hosts[0]).getByText("a legnagyobb kép túl nagy")).toBeInTheDocument();
    expect(within(hosts[1]).getByText("a képek elférnek")).toBeInTheDocument();
    expect(within(hosts[2]).getByText("nincs beállított kulcs")).toBeInTheDocument();
    // The locked host cannot take the largest picture: a plain retry is pointless.
    expect(screen.getByRole("button", { name: "Újrapróbálás" })).toBeDisabled();

    await user.selectOptions(screen.getByRole("combobox", { name: "Új képtárhely" }), "catbox");
    await user.selectOptions(screen.getByRole("combobox", { name: "Feltöltött képek köre" }), "sdr");
    await user.click(screen.getByRole("button", { name: "Újrakezdés ezzel a beállítással" }));
    await waitFor(() => expect(api.resetUpload).toHaveBeenCalledWith("job-1", {
      provider: "catbox",
      image_set: "sdr",
      upload_images: true,
      expected_version: 4,
    }));

    await user.click(screen.getByRole("button", { name: "Befejezés képek nélkül…" }));
    await user.click(screen.getByRole("button", { name: "Igen, befejezés képek nélkül" }));
    await waitFor(() => expect(api.resetUpload).toHaveBeenLastCalledWith("job-1", { upload_images: false, expected_version: 4 }));
  });

  it("offers a plain retry when the locked host can take every picture", async () => {
    const user = userEvent.setup();
    const job = makeJob({ state: "UPLOAD_FAILED", version: 4 });
    vi.mocked(api.retryUpload).mockResolvedValue(makeJob({ state: "UPLOADING", version: 5 }));
    const review = uploadReview();
    renderApp(<UploadReviewCard job={job} review={{ ...review, upload: { ...review.upload!, largest_image_bytes: 1024 } }} />);

    await user.click(screen.getByRole("button", { name: "Újrapróbálás" }));
    await waitFor(() => expect(api.retryUpload).toHaveBeenCalledWith("job-1"));
  });
});
