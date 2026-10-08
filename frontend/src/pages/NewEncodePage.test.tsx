import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { setLanguage } from "../i18n";
import { renderApp } from "../test/render";
import { NewEncodePage } from "./NewEncodePage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      sources: vi.fn(),
    },
  };
});

describe("NewEncodePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
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
