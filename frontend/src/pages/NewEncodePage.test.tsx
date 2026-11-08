import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { setLanguage } from "../i18n";
import { renderApp } from "../test/render";
import { NewEncodePage, visibleSourceEntries } from "./NewEncodePage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      sources: vi.fn(),
      createJob: vi.fn(),
    },
  };
});

describe("NewEncodePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem("bdencode:new-job-draft", JSON.stringify({ purpose: "encode" }));
    vi.mocked(api.sources).mockResolvedValue({
      roots: ["/storage"],
      path: "/storage",
      entries: [
        { name: "MOVIE_DISC", path: "/storage/MOVIE_DISC", is_bluray: true },
        { name: "OTHER_DISC", path: "/storage/OTHER_DISC", is_bluray: true },
        { name: "Extras", path: "/storage/Extras", is_bluray: false },
      ],
    });
  });

  it("asks first what the job is for, and shows only that job's steps", async () => {
    localStorage.clear();
    renderApp(<NewEncodePage />, "/new");
    expect(screen.getByRole("heading", { name: "Mit szeretnél csinálni?" })).toBeInTheDocument();
    expect(screen.queryByText("Tartalom")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Hang vagy felirat illesztése/ }));
    expect(await screen.findByRole("heading", { name: /Melyik encode-ra, remuxra vagy lemezre/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Munkamód$/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tartalom$/ })).toBeInTheDocument();
  });

  it("remembers the purpose on the job, and fitting needs no encode settings", async () => {
    localStorage.setItem("bdencode:new-job-draft", JSON.stringify({ purpose: "fit" }));
    vi.mocked(api.createJob).mockResolvedValue({ id: "new" } as never);
    renderApp(<NewEncodePage />, "/new");
    fireEvent.click(await screen.findByRole("button", { name: "MOVIE_DISC kiválasztása" }));
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));
    fireEvent.click(await screen.findByRole("button", { name: "Munka létrehozása és scan" }));
    await vi.waitFor(() => expect(api.createJob).toHaveBeenCalled());
    expect(vi.mocked(api.createJob).mock.calls[0][0].settings).toMatchObject({ purpose: "fit" });
  });

  it("goes back to the choice from the first step", async () => {
    renderApp(<NewEncodePage />, "/new");
    await screen.findByRole("button", { name: "MOVIE_DISC kiválasztása" });
    fireEvent.click(screen.getByRole("button", { name: "Vissza" }));
    expect(screen.getByRole("heading", { name: "Mit szeretnél csinálni?" })).toBeInTheDocument();
  });

  it("switches between source roots when there are several", async () => {
    vi.mocked(api.sources).mockImplementation(async (path?: string) => {
      const current = path ?? "/home/accofil/storage";
      return {
        roots: ["/home/accofil/storage", "/home/accofil/torrents"],
        path: current,
        entries: current.startsWith("/home/accofil/torrents")
          ? [{ name: "qbittorrent", path: "/home/accofil/torrents/qbittorrent", is_bluray: false, kind: "folder" }]
          : [{ name: "MOVIE_DISC", path: "/home/accofil/storage/MOVIE_DISC", is_bluray: true }],
      };
    });
    renderApp(<NewEncodePage />, "/new");

    const storage = await screen.findByRole("button", { name: "storage", pressed: true });
    const torrents = screen.getByRole("button", { name: "torrents", pressed: false });
    expect(storage).toHaveAttribute("title", "/home/accofil/storage");
    fireEvent.click(torrents);

    expect(await screen.findByText("qbittorrent")).toBeInTheDocument();
    expect(api.sources).toHaveBeenLastCalledWith("/home/accofil/torrents");
    expect(screen.getByRole("button", { name: "torrents", pressed: true })).toBeInTheDocument();
  });

  it("shows no root switcher for a single source root", async () => {
    renderApp(<NewEncodePage />, "/new");
    await screen.findAllByText("Blu-ray forrás");
    expect(screen.queryByRole("group", { name: "Tárhely" })).not.toBeInTheDocument();
  });

  it("walks the wizard in Hungarian", async () => {
    renderApp(<NewEncodePage />, "/new");

    expect((await screen.findAllByText("Blu-ray forrás")).length).toBe(2);
    expect(screen.getByRole("button", { name: /Forrás$/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "MOVIE_DISC kiválasztása" }));
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));

    expect(screen.getByText("Sorozatlemez")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));

    expect(screen.getAllByText("Kezdő").length).toBeGreaterThan(0);
    expect(screen.getByText("Comparison képek feltöltése")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Munka létrehozása és scan" })).toBeInTheDocument();
  });

  it("lets another disc replace the first choice, name included", async () => {
    renderApp(<NewEncodePage />, "/new");

    fireEvent.click(await screen.findByRole("button", { name: "MOVIE_DISC kiválasztása" }));
    // A long name is clamped in its tile; the full name stays in the tooltip.
    expect(screen.getByTitle("OTHER_DISC")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "OTHER_DISC kiválasztása" }));
    expect(screen.getByText("/storage/OTHER_DISC")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));
    expect(screen.getByPlaceholderText("Például: A film címe (2024)")).toHaveValue("OTHER_DISC");

    // A name the operator typed is kept when the disc changes.
    fireEvent.change(screen.getByPlaceholderText("Például: A film címe (2024)"), { target: { value: "My Film (1990)" } });
    fireEvent.click(screen.getByRole("button", { name: /Forrás$/ }));
    fireEvent.click(screen.getByRole("button", { name: "MOVIE_DISC kiválasztása" }));
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));
    expect(screen.getByPlaceholderText("Például: A film címe (2024)")).toHaveValue("My Film (1990)");

    fireEvent.click(screen.getByRole("button", { name: /Forrás$/ }));
    fireEvent.click(screen.getByRole("button", { name: "Kijelölés törlése" }));
    expect(screen.queryByText("/storage/MOVIE_DISC")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tovább" })).toBeDisabled();
  });

  it("offers a disc-remux MKV file as a source, named without its extension", async () => {
    const name = "I Want Your Sex 2026 Hybrid 2160p UHD Blu-ray Remux DoVi HDR10+ HEVC TrueHD 7.1 Atmos.mkv";
    vi.mocked(api.sources).mockResolvedValue({
      roots: ["/storage"],
      path: "/storage",
      entries: [
        { name: "Extras", path: "/storage/Extras", is_bluray: false, kind: "folder" },
        { name, path: `/storage/${name}`, is_bluray: false, kind: "mkv" },
      ],
    });
    renderApp(<NewEncodePage />, "/new");

    expect(await screen.findByText("MKV remux")).toBeInTheDocument();
    // The long name is clamped in its tile; the full name stays in the tooltip.
    expect(screen.getByTitle(name)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: `${name} megnyitása` })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extras megnyitása" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `${name} kiválasztása` }));
    expect(screen.getByText(`/storage/${name}`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));
    expect(screen.getByPlaceholderText("Például: A film címe (2024)")).toHaveValue(name.slice(0, -4));
  });

  it("hides MKV files on request, keeps discs and folders, and remembers the choice", async () => {
    vi.mocked(api.sources).mockResolvedValue({
      roots: ["/storage"],
      path: "/storage",
      entries: [
        { name: "Extras", path: "/storage/Extras", is_bluray: false, kind: "folder" },
        { name: "MOVIE_DISC", path: "/storage/MOVIE_DISC", is_bluray: true, kind: "bluray" },
        { name: "Some Remux.mkv", path: "/storage/Some Remux.mkv", is_bluray: false, kind: "mkv" },
      ],
    });
    const { unmount } = renderApp(<NewEncodePage />, "/new");
    const toggle = await screen.findByRole("checkbox", { name: "Csak teljes lemezek" });
    expect(toggle).not.toBeChecked();
    expect(await screen.findByRole("button", { name: "Some Remux.mkv kiválasztása" })).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(screen.queryByRole("button", { name: "Some Remux.mkv kiválasztása" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "MOVIE_DISC kiválasztása" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extras megnyitása" })).toBeInTheDocument();

    unmount();
    renderApp(<NewEncodePage />, "/new");
    expect(await screen.findByRole("checkbox", { name: "Csak teljes lemezek" })).toBeChecked();
    expect(await screen.findByRole("button", { name: "MOVIE_DISC kiválasztása" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Some Remux.mkv kiválasztása" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Csak teljes lemezek" }));
    expect(screen.getByRole("button", { name: "Some Remux.mkv kiválasztása" })).toBeInTheDocument();
  });

  it("filters source entries by kind and name together", () => {
    const entries = [
      { name: "Alpha", path: "/s/Alpha", is_bluray: false, kind: "folder" as const },
      { name: "Alpha Disc", path: "/s/Alpha Disc", is_bluray: true, kind: "bluray" as const },
      { name: "Alpha.mkv", path: "/s/Alpha.mkv", is_bluray: false, kind: "mkv" as const },
      { name: "Legacy", path: "/s/Legacy", is_bluray: true },
    ];
    expect(visibleSourceEntries(entries, "", false)).toHaveLength(4);
    expect(visibleSourceEntries(entries, "", true).map((entry) => entry.name)).toEqual(["Alpha", "Alpha Disc", "Legacy"]);
    expect(visibleSourceEntries(entries, "alpha", true).map((entry) => entry.name)).toEqual(["Alpha", "Alpha Disc"]);
  });

  it("shows the wizard in English", async () => {
    setLanguage("en", { persist: false });
    renderApp(<NewEncodePage />, "/new");

    expect((await screen.findAllByText("Blu-ray source")).length).toBe(2);
    expect(screen.getByText("Folder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    for (const step of ["Source", "Content", "Mode"]) {
      expect(screen.getByRole("button", { name: new RegExp(`${step}$`) })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Select MOVIE_DISC" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(screen.getByRole("heading", { name: "What is on the disc?" })).toBeInTheDocument();
    for (const label of ["Film", "Concert", "Anime", "Series disc"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    for (const label of ["Beginner", "Advanced", "Pro", "Upload comparison images"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByRole("option", { name: "Automatic: ImgBB → Catbox → Freeimage" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create job and scan" })).toBeInTheDocument();
    expect(screen.queryByText("Tovább")).not.toBeInTheDocument();
  });
});
