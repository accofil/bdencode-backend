import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { JobEvaluation } from "../api/types";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { EvaluationCard } from "./EvaluationCard";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, jobEvaluation: vi.fn(), evaluateJob: vi.fn() } };
});

function evaluation(overrides: Partial<JobEvaluation> = {}): JobEvaluation {
  return {
    source: "deterministic",
    model: null,
    verdict: "transparent",
    summary: { hu: "Átlátszó kódolás.", en: "Transparent encode." },
    findings: [{ hu: "A videó 15%-kal kisebb a forrásnál.", en: "The video is 15% smaller than the source." }],
    suggestions: [{ field: "crf", current: 17.5, value: 18.5, estimated_size_change_percent: -13, reason: { hu: "Kisebb fájl, átlátszó marad.", en: "Smaller file, still transparent." } }],
    confidence: null,
    ai_available: false,
    ai_attempted: false,
    ai_error: null,
    created_at: "2026-10-12T10:00:00Z",
    facts: {
      encoder: "x264",
      settings: { crf: 17.5 },
      sizes: { saving_ratio: 0.147, video_kbps: 20466, source_video_kbps: 23985, bits_per_pixel: 0.443 },
      metrics: { ssim_mean: 0.9875, psnr_mean_db: 48.4 },
      vmaf: { mean: 95.27, one_percent_low: 91.94, minimum: 87.98 },
    },
    ...overrides,
  };
}

describe("EvaluationCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the fixed-rule verdict and the suggested CRF without an AI key", async () => {
    vi.mocked(api.jobEvaluation).mockResolvedValue(evaluation());
    renderApp(<EvaluationCard job={makeJob({ state: "COMPLETED" })} />);

    expect(await screen.findByText("Átlátszó")).toBeInTheDocument();
    expect(screen.getByText("Rögzített szabályok alapján")).toBeInTheDocument();
    expect(screen.getByText("CRF: 17.5 → 18.5")).toBeInTheDocument();
    expect(screen.getByText("méret -13%")).toBeInTheDocument();
    expect(api.evaluateJob).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Újraértékelés AI-val" })).not.toBeInTheDocument();
  });

  it("asks the AI once when a key is set", async () => {
    vi.mocked(api.jobEvaluation).mockResolvedValue(evaluation({ ai_available: true }));
    vi.mocked(api.evaluateJob).mockResolvedValue(evaluation({ ai_available: true, ai_attempted: true, source: "openai", model: "gpt-test", confidence: 0.8 }));
    renderApp(<EvaluationCard job={makeJob({ state: "COMPLETED" })} />);

    await waitFor(() => expect(api.evaluateJob).toHaveBeenCalledWith("job-1", true));
    expect(await screen.findByText("AI-értékelés: OpenAI · gpt-test · bizonyosság 80%")).toBeInTheDocument();
    expect(api.evaluateJob).toHaveBeenCalledTimes(1);
  });
});
