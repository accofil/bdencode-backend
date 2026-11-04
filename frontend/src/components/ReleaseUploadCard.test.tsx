import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { ReleasePreparation, UploadPlan } from "../api/types";
import { ReleaseUploadCard } from "./ReleaseUploadCard";
import { TrackerSettingsPanel } from "./TrackerSettingsPanel";

vi.mock("../api/client", async (original) => {
  const actual = await original<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      buildReleaseTorrent: vi.fn(),
      releasePreparationAction: vi.fn(),
      acknowledgeReleaseDuplicates: vi.fn(),
      releaseUploadPlan: vi.fn(),
      uploadRelease: vi.fn(),
      seedRelease: vi.fn(),
      releaseSiteTorrentUrl: (id: string) => `/api/v1/release-preparations/${id}/site-torrent`,
      trackerSettings: vi.fn(),
      saveTrackerSettings: vi.fn(),
      setTrackerSecret: vi.fn(),
      deleteTrackerSecret: vi.fn(),
      checkTrackerConnection: vi.fn(),
    },
  };
});

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const base: ReleasePreparation = { id: "p1", job_id: "j1", version: 4, state: "READY", kit_ready: true };
const hash = "a".repeat(40);
const plan: UploadPlan = {
  tracker: "aither",
  release_name: "Film.2020.1080p-X",
  torrent_sha256: "b".repeat(64),
  info_hash: hash,
  files: ["Film.2020.1080p-X.mkv"],
  seeding: { automatic: true, category: "bdencode" },
  fields: { name: "Film 2020 1080p-X", description: "[img]x[/img]", anonymous: false, personal_release: true, mod_queue: false },
  facts: { type: "REMUX", tmdb: 42 },
  problems: [],
};

beforeEach(() => vi.clearAllMocks());

describe("ReleaseUploadCard", () => {
  it("starts with the torrent and keeps the later steps closed", async () => {
    vi.mocked(api.buildReleaseTorrent).mockResolvedValue({ ...base, state: "BUILDING_TORRENT", version: 5 });

    wrap(<ReleaseUploadCard preparation={base} />);

    expect(screen.getByRole("button", { name: "Dupe check" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Feltöltés…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Torrent készítése" }));
    await waitFor(() => expect(api.buildReleaseTorrent).toHaveBeenCalledWith("p1", 4));
  });

  it("shows the hits, and an own reason opens the way", async () => {
    vi.mocked(api.acknowledgeReleaseDuplicates).mockResolvedValue({ ...base, state: "READY_TO_PUBLISH" });
    const review: ReleasePreparation = {
      ...base,
      state: "NEEDS_REVIEW",
      torrent_infohash: hash,
      dupe_receipt: {
        outcome: "DUPLICATE",
        matches: [{ name: "Film 2020 x264-Y", url: "https://aither.cc/torrents/1", size: 1, exact: false, trumpable: false }],
      },
    };

    wrap(<ReleaseUploadCard preparation={review} />);

    expect(screen.getByRole("link", { name: "Film 2020 x264-Y" })).toHaveAttribute("href", "https://aither.cc/torrents/1");
    const go = screen.getByRole("button", { name: "Átnéztem, mehet tovább" });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Miért férhet el/), { target: { value: "Remux az encode mellett" } });
    fireEvent.click(go);
    await waitFor(() =>
      expect(api.acknowledgeReleaseDuplicates).toHaveBeenCalledWith("p1", 4, "Remux az encode mellett"),
    );
  });

  it("offers no way past an identical name or a blocked release", () => {
    const exact: ReleasePreparation = {
      ...base,
      state: "NEEDS_REVIEW",
      torrent_infohash: hash,
      dupe_receipt: { outcome: "DUPLICATE", matches: [{ name: "Film", url: "", size: null, exact: true, trumpable: false }] },
    };
    wrap(<ReleaseUploadCard preparation={exact} />);

    expect(screen.getByText("Pontosan ez a név már fent van")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Átnéztem, mehet tovább" })).not.toBeInTheDocument();
  });

  it("uploads only after the plan was shown and confirmed", async () => {
    vi.mocked(api.releaseUploadPlan).mockResolvedValue(plan);
    vi.mocked(api.uploadRelease).mockResolvedValue({ ...base, state: "PUBLISHING", version: 6 });
    const ready: ReleasePreparation = { ...base, state: "READY_TO_PUBLISH", version: 5, torrent_infohash: hash };

    wrap(<ReleaseUploadCard preparation={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Feltöltés…" }));

    expect(await screen.findByText("Ez valódi feltöltés a trackerre")).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Feltöltés most" });
    expect(send).toBeDisabled();
    await screen.findByDisplayValue("Film 2020 1080p-X");
    fireEvent.click(screen.getByRole("checkbox", { name: /Átnéztem, és ezt töltöm fel: Film\.2020\.1080p-X/ }));
    fireEvent.click(send);

    await waitFor(() => expect(api.uploadRelease).toHaveBeenCalledTimes(1));
    expect(api.uploadRelease).toHaveBeenCalledWith("p1", "aither", expect.objectContaining({
      expected_version: 5,
      confirm_release_name: "Film.2020.1080p-X",
      torrent_sha256: plan.torrent_sha256,
      name: "Film 2020 1080p-X",
      personal_release: true,
    }));
  });

  it("names the problems of a plan", async () => {
    vi.mocked(api.releaseUploadPlan).mockResolvedValue({ ...plan, problems: ["Aither needs the film's TMDB id"] });
    const ready: ReleasePreparation = { ...base, state: "READY_TO_PUBLISH", torrent_infohash: hash };

    wrap(<ReleaseUploadCard preparation={ready} />);
    fireEvent.click(screen.getByRole("button", { name: "Feltöltés…" }));

    expect(await screen.findByText("Aither needs the film's TMDB id")).toBeInTheDocument();
  });

  it("links the finished upload and offers another seed", async () => {
    vi.mocked(api.seedRelease).mockResolvedValue({ ...base, state: "SEEDING" });
    const published: ReleasePreparation = {
      ...base,
      state: "PUBLISHED",
      torrent_infohash: hash,
      publication_receipt: { outcome: "PUBLISHED", url: "https://aither.cc/torrents/7" },
      qbittorrent_receipt: { outcome: "FAILED" },
      error: "does not seed yet",
    };

    wrap(<ReleaseUploadCard preparation={published} />);

    expect(screen.getByRole("link", { name: "https://aither.cc/torrents/7" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tracker torrentje" })).toHaveAttribute(
      "href",
      "/api/v1/release-preparations/p1/site-torrent",
    );
    fireEvent.click(screen.getByRole("button", { name: "Seed újra" }));
    await waitFor(() => expect(api.seedRelease).toHaveBeenCalledWith("p1", 4));
  });

  it("warns when it is not known whether it went up", () => {
    wrap(<ReleaseUploadCard preparation={{ ...base, state: "UNKNOWN", torrent_infohash: hash }} />);

    expect(screen.getByText("Nem tudni, felment-e")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dupe check" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Feltöltés…" })).toBeDisabled();
  });
});

describe("TrackerSettingsPanel", () => {
  const status = {
    aither: { configured: true },
    ncore: { configured: false },
    qbittorrent: { url: "http://127.0.0.1:8080", username: "accofil", password_set: false, configured: true },
    key_management: { available: true, results: [] },
  };

  it("shows what is set, never a secret, and checks the connection", async () => {
    vi.mocked(api.trackerSettings).mockResolvedValue(status);
    vi.mocked(api.checkTrackerConnection).mockResolvedValue({ result: "Aither API OK" });

    wrap(<TrackerSettingsPanel />);

    expect(await screen.findByText("Trackerek és seedelés")).toBeInTheDocument();
    expect(screen.getByDisplayValue("http://127.0.0.1:8080")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Kapcsolat ellenőrzése" })[0]);
    expect(await screen.findByText("Aither API OK")).toBeInTheDocument();
    expect(api.checkTrackerConnection).toHaveBeenCalledWith("aither");
  });

  it("sends a new secret to the helper and clears the field", async () => {
    vi.mocked(api.trackerSettings).mockResolvedValue(status);
    vi.mocked(api.setTrackerSecret).mockResolvedValue({ request_id: "r" });

    wrap(<TrackerSettingsPanel />);

    const field = await screen.findByLabelText(/cookies\.txt/);
    fireEvent.change(field, { target: { value: "nick=a; pass=b" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Mentés" })[1]);

    await waitFor(() => expect(api.setTrackerSecret).toHaveBeenCalledWith("ncore", "nick=a; pass=b"));
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("closes the secret fields where the helper is missing", async () => {
    vi.mocked(api.trackerSettings).mockResolvedValue({ ...status, key_management: { available: false, results: [] } });

    wrap(<TrackerSettingsPanel />);

    expect(await screen.findByLabelText(/cookies\.txt/)).toBeDisabled();
  });
});
