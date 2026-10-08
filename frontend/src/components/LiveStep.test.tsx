import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JobLive, LiveStep } from "../api/types";
import { renderApp } from "../test/render";
import { LiveStepPanel, remainingSeconds, StepTimelineCard, stepPercent } from "./LiveStep";

function makeStep(overrides: Partial<LiveStep> = {}): LiveStep {
  return {
    schema_version: 1,
    key: "crop-scan",
    label: "Crop-keresés (GPU)",
    fraction: 0.2537,
    detail: "29 / 117 perc",
    started_at: 1_000,
    updated_at: 1_060,
    eta_seconds: 180,
    metrics: {},
    side: {},
    ...overrides,
  };
}

describe("live step", () => {
  it("shows the running step with its own percentage, times and side tasks", () => {
    const live: JobLive = {
      step: makeStep({ side: { index: { label: "Forrásindex", fraction: 0.57, done: false } } }),
      timeline: [],
      now: 1_090,
    };
    renderApp(<LiveStepPanel live={live} />);

    expect(screen.getByText("Crop-keresés (GPU)")).toBeInTheDocument();
    expect(screen.getByText("29 / 117 perc")).toBeInTheDocument();
    expect(screen.getByText("25.3%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Crop-keresés (GPU) folyamata" })).toHaveAttribute("aria-valuenow", "25");
    // Elapsed from the server clock; the estimate made 30 s ago is aged.
    expect(screen.getByText("1:30")).toBeInTheDocument();
    expect(screen.getByText("~2:30")).toBeInTheDocument();
    expect(screen.getByText("57.0%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Forrásindex folyamata" })).toHaveAttribute("aria-valuenow", "57");
  });

  it("animates an unmeasurable step instead of inventing a percentage", () => {
    renderApp(<LiveStepPanel live={{ step: makeStep({ key: "language", label: "Hangsávok nyelvének ellenőrzése", fraction: null, eta_seconds: null, detail: null }), timeline: [], now: 1_010 }} />);

    const bar = screen.getByRole("progressbar", { name: "Hangsávok nyelvének ellenőrzése folyamata" });
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar.querySelector(".progress-track--indeterminate")).not.toBeNull();
    expect(screen.getByRole("img", { name: "Folyamatban, az aránya nem mérhető" })).toBeInTheDocument();
    expect(screen.queryByText(/Hátralévő/)).not.toBeInTheDocument();
  });

  it("reports the encoder's speed and the projected size against the target", () => {
    const encode = makeStep({
      key: "encode",
      label: "Videókódolás",
      fraction: 0.5,
      detail: null,
      metrics: { fps: 1.84, speed: 0.077, eta_seconds: 43_000, output_bytes: 12.4e9, projected_bytes: 24.8e9, target_bytes: 25e9 },
    });
    const { unmount } = renderApp(<LiveStepPanel live={{ step: encode, timeline: [], now: 1_060 }} />);

    expect(screen.getByText("1.84 fps · 0.077×")).toBeInTheDocument();
    expect(screen.getByText("12.40 GB")).toBeInTheDocument();
    expect(screen.getByText("célon belül")).toBeInTheDocument();
    // The encoder's estimate wins over the step's own average.
    expect(screen.getByText("~11:56:40")).toBeInTheDocument();
    unmount();

    const over = { ...encode, metrics: { ...encode.metrics, projected_bytes: 27e9 } };
    renderApp(<LiveStepPanel live={{ step: over, timeline: [], now: 1_060 }} />);
    expect(screen.getByText("+8% a cél felett")).toBeInTheDocument();
  });

  it("never rounds a step up to 100% and never counts below zero", () => {
    expect(stepPercent(0.9999)).toBe("99.9%");
    expect(stepPercent(1)).toBe("100.0%");
    expect(remainingSeconds(makeStep({ eta_seconds: 10, updated_at: 1_000 }), 1_500)).toBe(0);
    expect(remainingSeconds(makeStep({ eta_seconds: null }), 1_500)).toBeNull();
  });

  it("lists the finished steps with their durations and the running one", () => {
    const live: JobLive = {
      step: makeStep({ key: "auto-crf", label: "Automatikus CRF-keresés", started_at: 5_000 }),
      timeline: [
        { key: "staging", label: "Lemezfájlok helyi másolata", started_at: 1_000, finished_at: 1_300, seconds: 300, outcome: "done" },
        { key: "language", label: "Hangsávok nyelvének ellenőrzése", started_at: 1_300, finished_at: 1_390, seconds: 90, outcome: "review" },
        { key: "encode", label: "Videókódolás", started_at: 1_400, finished_at: 1_460, seconds: 60, outcome: "interrupted" },
      ],
      now: 5_125,
    };
    const { unmount } = renderApp(<StepTimelineCard live={live} showStep />);

    const list = screen.getByRole("list");
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText("5:00")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("img", { name: "ellenőrzést kért" })).toBeInTheDocument();
    expect(within(rows[2]).getByRole("img", { name: "megszakítva" })).toBeInTheDocument();
    expect(within(rows[3]).getByText("Automatikus CRF-keresés")).toBeInTheDocument();
    expect(within(rows[3]).getByText("2:05")).toBeInTheDocument();
    expect(screen.getByText("Összesen 7:30")).toBeInTheDocument();
    unmount();

    // A job that no longer runs never shows a leftover step.
    renderApp(<StepTimelineCard live={live} showStep={false} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});
