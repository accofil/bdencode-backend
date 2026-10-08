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
        { name: "Extras", path: "/storage/Extras", is_bluray: false },
      ],
    });
  });

  it("walks the wizard in Hungarian", async () => {
    renderApp(<NewEncodePage />, "/new");

    expect(await screen.findByText("Blu-ray forrás")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Forrás$/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "MOVIE_DISC kiválasztása" }));
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));

    expect(screen.getByText("Sorozatlemez")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tovább" }));

    expect(screen.getAllByText("Kezdő").length).toBeGreaterThan(0);
    expect(screen.getByText("Comparison képek feltöltése")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Munka létrehozása és scan" })).toBeInTheDocument();
  });

  it("shows the wizard in English", async () => {
    setLanguage("en", { persist: false });
    renderApp(<NewEncodePage />, "/new");

    expect(await screen.findByText("Blu-ray source")).toBeInTheDocument();
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
