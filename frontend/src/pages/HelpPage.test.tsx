import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FieldHelpButton } from "../components/EncoderHelp";
import { ENCODER_HELP, encoderHelp, HELP_GROUPS } from "../encoderHelp";
import { renderApp } from "../test/render";
import { HelpPage } from "./HelpPage";

describe("encoder help", () => {
  it("covers every grouped setting exactly once", () => {
    const grouped = HELP_GROUPS.flatMap((group) => group.fields);
    expect(new Set(grouped).size).toBe(grouped.length);
    for (const field of grouped) expect(encoderHelp(field), field).toBeDefined();
    for (const entry of ENCODER_HELP) expect(grouped, entry.field).toContain(entry.field);
  });

  it("filters the settings by encoder and by search", async () => {
    const user = userEvent.setup();
    renderApp(<HelpPage />);

    expect(screen.getByRole("heading", { name: "Kódolási beállítások" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Macroblock-tree (mbtree)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "SAO" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "x264 (1080p)" }));
    expect(screen.queryByRole("heading", { name: "SAO" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Macroblock-tree (mbtree)" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Mindkettő" }));
    await user.type(screen.getByRole("textbox", { name: "Beállítás keresése" }), "szemcsét");
    expect(screen.getByRole("heading", { name: "SAO" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Annex B" })).not.toBeInTheDocument();

    await user.clear(screen.getByRole("textbox", { name: "Beállítás keresése" }));
    await user.type(screen.getByRole("textbox", { name: "Beállítás keresése" }), "nincs ilyen beállítás");
    expect(screen.getByText("Nincs találat")).toBeInTheDocument();
  });

  it("opens a setting's help from the wizard without toggling the control", async () => {
    const user = userEvent.setup();
    renderApp(<label><span>SAO<FieldHelpButton field="sao" encoder="x265" /></span><input type="checkbox" aria-label="SAO kapcsoló" /></label>);

    await user.click(screen.getByRole("button", { name: "SAO: súgó" }));
    const dialog = screen.getByRole("dialog", { name: "Súgó: SAO" });
    expect(within(dialog).getByText(/szinte mindig kikapcsolva \(--no-sao\)/)).toBeInTheDocument();
    expect(within(dialog).getByText("Aither-gyakorlat")).toBeInTheDocument();
    expect(within(dialog).getByText("nCore / magyar szabvány")).toBeInTheDocument();
    expect(within(dialog).getByText(/--no-sao --selective-sao 0/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "SAO kapcsoló" })).not.toBeChecked();
  });
});
