import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setLanguage } from "../i18n";
import { ReloadNotice, reloadOrigin } from "./ReloadNotice";

const suggestion = {
  field: "crf",
  current: 18,
  value: 17,
  reason: { hu: "Gyenge pontok a sötét jelenetekben.", en: "Weak spots in the dark scenes." },
  estimated_size_change_percent: 15,
};

describe("ReloadNotice", () => {
  beforeEach(() => setLanguage("hu", { persist: false }));

  it("lists the evaluation's suggestions without applying them", () => {
    render(<ReloadNotice job={{ settings: { reload: { from_job_id: "old", from_name: "Taffin", mode: "same", selection: { playlist_id: "00004" }, suggestions: [suggestion], evaluation: { verdict: "acceptable" } } } }} />);

    expect(screen.getByText("Újrakezdés a korábbi beállításokkal")).toBeInTheDocument();
    expect(screen.getByText(/nincsenek alkalmazva/)).toBeInTheDocument();
    expect(screen.getByText("CRF: 18 → 17")).toBeInTheDocument();
    expect(screen.getByText("Gyenge pontok a sötét jelenetekben.")).toBeInTheDocument();
    expect(screen.getByText("méret +15%")).toBeInTheDocument();
  });

  it("says when there was nothing to suggest or nothing evaluated", () => {
    const { rerender } = render(<ReloadNotice job={{ settings: { reload: { from_job_id: "old", from_name: "Taffin", mode: "same", selection: null, suggestions: [], evaluation: { verdict: "good" } } } }} />);
    expect(screen.getByText("A korábbi encode értékelése nem javasolt módosítást.")).toBeInTheDocument();

    rerender(<ReloadNotice job={{ settings: { reload: { from_job_id: "old", from_name: "Taffin", mode: "same", selection: null, suggestions: [], evaluation: null } } }} />);
    expect(screen.getByText("A korábbi munkának nincs értékelése, ezért nincs javaslat.")).toBeInTheDocument();
  });

  it("shows a clean start without the earlier settings, and nothing for an ordinary job", () => {
    const { container, rerender } = render(<ReloadNotice job={{ settings: { reload: { from_job_id: "old", from_name: "Taffin", mode: "clean" } } }} />);
    expect(screen.getByText("Újrakezdés tiszta lappal")).toBeInTheDocument();

    rerender(<ReloadNotice job={{ settings: {} }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("hands the wizard the earlier selection only for a reload with the same settings", () => {
    const selection = { playlist_id: "00004", tracks: [] };
    expect(reloadOrigin({ settings: { reload: { from_job_id: "old", mode: "same", selection } } })?.selection).toEqual(selection);
    expect(reloadOrigin({ settings: { reload: { from_job_id: "old", mode: "clean", selection } } })?.selection).toBeNull();
    expect(reloadOrigin({ settings: { reload: { from_job_id: "old", mode: "tweak" } } })).toBeNull();
  });
});
