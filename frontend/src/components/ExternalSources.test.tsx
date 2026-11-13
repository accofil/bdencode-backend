import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { ExternalMapSegment, ExternalReviewItem, ExternalSourceSelection, Job } from "../api/types";
import { ExternalReviewCard, ExternalSourcesCard, listeningPoints } from "./ExternalSources";

vi.mock("../api/client", async (original) => {
  const actual = await original<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      probeExternalSource: vi.fn(),
      sources: vi.fn(),
      externalReview: vi.fn(),
      approveExternalSource: vi.fn(),
      discardExternalSource: vi.fn(),
      setExternalPitch: vi.fn(),
      createExternalExcerpt: vi.fn(),
    },
  };
});

const mocked = vi.mocked(api);

function wrap(node: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>);
}

const segments: ExternalMapSegment[] = [
  { target_start: 140, target_end: 3347, offset: -140, boundary_uncertainty_frames: 0, similarity_median: 0.55, similarity_p10: 0.3 },
  { target_start: 3347, target_end: 50000, offset: -130, boundary_uncertainty_frames: 2, similarity_median: 0.9, similarity_p10: 0.8 },
  { target_start: 51000, target_end: 90000, offset: -1130, boundary_uncertainty_frames: 0, similarity_median: 0.93, similarity_p10: 0.85 },
];

const item: ExternalReviewItem = {
  selection: {
    id: "e1",
    path: "/dvd.iso",
    tracks: [{ stream: "#0x80", language: "hun", position: 0, default: true, pitch: "restore" }],
    subtitles: [],
    approved_map_sha256: null,
  },
  review: {
    id: "e1",
    path: "/dvd.iso",
    kind: "dvd-image",
    fps: "25",
    target_fps: "24000/1001",
    map_sha256: "a".repeat(64),
    map: {
      mode: "frame-locked",
      target_frames: 90000,
      donor_frames: 89000,
      matched_frames: 89000,
      unmatched_frames: 1140,
      similarity_median: 0.91,
      share_at_least_0_8: 0.93,
      segments,
    },
    tracks: [{ stream: "#0x80", language: "hun", pitch: "restore", codec: "ac3", channels: 2, copy: false, encoding: { codec: "ac3", bit_rate: 224000, dialnorm: -27 }, silent_samples: 100, file: "track-00.ac3" }],
    subtitles: [],
  },
};

const job = { id: "j1", version: 3, state: "NEEDS_REVIEW" } as unknown as Job;

beforeEach(() => vi.resetAllMocks());

describe("listeningPoints", () => {
  it("lists every splice and missing part, in film order", () => {
    const points = listeningPoints(segments, 24, 90000);
    expect(points.filter((point) => point.kind === "splice")).toHaveLength(1);
    const gap = points.find((point) => point.kind === "gap");
    expect(gap?.seconds).toBeCloseTo(50000 / 24);
    expect(gap?.label).toContain("41.7");
    expect(points.filter((point) => point.kind === "sample")).toHaveLength(3);
    expect(points.map((point) => point.seconds)).toEqual([...points.map((point) => point.seconds)].sort((a, b) => a - b));
  });
});

describe("ExternalReviewCard", () => {
  it("makes an excerpt with the ear test by default and shows it", async () => {
    mocked.externalReview.mockResolvedValue({ items: [item] });
    mocked.createExternalExcerpt.mockResolvedValue({ name: "preview-1s-20s-480p-abcdef0123.mp4", start_seconds: 1, duration_seconds: 20, height: 480, size_bytes: 1, created_at: 1 });
    wrap(<ExternalReviewCard job={job} />);
    const listen = await screen.findAllByRole("button", { name: "Meghallgatom" });
    fireEvent.click(listen[0]);
    await waitFor(() => expect(mocked.createExternalExcerpt).toHaveBeenCalled());
    expect(mocked.createExternalExcerpt.mock.calls[0][2]).toMatchObject({ audio: "both", duration_seconds: 20, height: 480, track: 0 });
    expect(await screen.findByLabelText("Kivonat az illesztett hanggal")).toBeTruthy();
  });

  it("warns about the silent part and approves the shown map", async () => {
    mocked.externalReview.mockResolvedValue({ items: [item] });
    mocked.approveExternalSource.mockResolvedValue(job);
    wrap(<ExternalReviewCard job={job} />);
    expect(await screen.findByText("A külső sáv itt néma lesz")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Jóváhagyom, mehet tovább" }));
    await waitFor(() => expect(mocked.approveExternalSource).toHaveBeenCalledWith("j1", "e1", "a".repeat(64)));
  });

  it("changes the pitch only through a new fit", async () => {
    mocked.externalReview.mockResolvedValue({ items: [item] });
    mocked.setExternalPitch.mockResolvedValue(job);
    wrap(<ExternalReviewCard job={job} />);
    const pitch = await screen.findByLabelText("Hangmagasság");
    fireEvent.change(pitch, { target: { value: "keep" } });
    await waitFor(() => expect(mocked.setExternalPitch).toHaveBeenCalledWith("j1", "e1", "#0x80", "keep"));
  });

  it("is absent once every fit is approved", async () => {
    const approved = { ...item, selection: { ...item.selection, approved_map_sha256: "a".repeat(64) } };
    mocked.externalReview.mockResolvedValue({ items: [approved] });
    const { container } = wrap(<ExternalReviewCard job={job} />);
    await waitFor(() => expect(mocked.externalReview).toHaveBeenCalled());
    expect(container.querySelector(".external-card")).toBeNull();
  });
});

describe("ExternalSourcesCard", () => {
  it("adds the picked track with the source's language, and removes it again", async () => {
    mocked.probeExternalSource.mockResolvedValue({
      kind: "dvd-image",
      path: "/dvd.iso",
      fps: "25",
      duration_seconds: 6468,
      width: 720,
      height: 576,
      tracks: [{ stream: "#0x80", codec: "ac3", channels: 2, sample_rate: 48000, bit_rate: null, language: "hu", title: null }],
      support: { available: true, missing: [], dvd_missing: [] },
    });
    let value: ExternalSourceSelection[] = [];
    const onChange = vi.fn((next: ExternalSourceSelection[]) => { value = next; view.rerender(tree()); });
    const client = new QueryClient();
    const tree = () => <QueryClientProvider client={client}><ExternalSourcesCard value={value} onChange={onChange} available /></QueryClientProvider>;
    const view = render(tree());
    fireEvent.change(screen.getByLabelText(/A forrás helye/), { target: { value: "/dir" } });
    fireEvent.click(screen.getByRole("button", { name: "Beolvasás" }));
    const check = await screen.findByRole("checkbox", { name: /AC3 2 csatorna/ });
    fireEvent.click(check);
    expect(value[0]).toMatchObject({ path: "/dvd.iso", tracks: [{ stream: "#0x80", language: "hun", pitch: "restore" }] });
    fireEvent.click(screen.getByRole("checkbox", { name: /AC3 2 csatorna/ }));
    expect(value).toEqual([]);
  });

  it("finds a file of a large folder by name and chooses an MKV by its name", async () => {
    const web = "/q/HUN-FULCRUM/fulcrum-tlws.2025.1080p.web.mkv";
    mocked.sources.mockImplementation(async (_path?: string, query?: string) => (
      query
        ? { roots: ["/q"], path: "/q", truncated: false, total: 1, entries: [{ name: "fulcrum-tlws.2025.1080p.web.mkv", path: web, is_bluray: false, kind: "mkv" }] }
        : { roots: ["/q"], path: "/q", truncated: true, total: 2260, entries: [{ name: "A", path: "/q/A", is_bluray: false, kind: "folder" }] }
    ));
    mocked.probeExternalSource.mockResolvedValue({
      kind: "file", path: web, fps: "25", duration_seconds: 6000, width: 1920, height: 1080, tracks: [], subtitles: [],
    } as never);
    wrap(<ExternalSourcesCard value={[]} onChange={() => undefined} available />);

    fireEvent.click(screen.getByRole("button", { name: "Tallózás" }));
    expect(await screen.findByText(/2260 elem van, ebből 1 látszik/)).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Keresés a mappában" }), { target: { value: "fulcrum" } });
    fireEvent.click(await screen.findByRole("button", { name: "fulcrum-tlws.2025.1080p.web.mkv" }));

    await waitFor(() => expect(mocked.probeExternalSource).toHaveBeenCalledWith(web));
    expect(mocked.sources).toHaveBeenCalledWith(undefined, "fulcrum");
    expect(mocked.sources).not.toHaveBeenCalledWith(web);
  });

  it("says so when this host lacks a tool", () => {
    wrap(<ExternalSourcesCard value={[]} onChange={() => undefined} available={false} />);
    expect(screen.getByText(/hiányzik az ehhez szükséges eszköz/)).toBeTruthy();
  });
});
