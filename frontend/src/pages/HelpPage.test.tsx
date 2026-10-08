import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FieldHelpButton } from "../components/EncoderHelp";
import { ENCODER_HELP, encoderHelp, HELP_GROUPS, HELP_SECTIONS, HELP_SOURCES } from "../encoderHelp";
import { setLanguage } from "../i18n";
import type { LocalText } from "../i18n";
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

  it("has every help text in both languages", () => {
    const texts: Array<[string, LocalText]> = [];
    for (const entry of ENCODER_HELP) {
      for (const [key, value] of Object.entries(entry)) {
        if (value && typeof value === "object" && !Array.isArray(value)) texts.push([`${entry.field}.${key}`, value as LocalText]);
      }
    }
    HELP_SECTIONS.forEach((section) => [section.title, ...section.paragraphs].forEach((text) => texts.push([section.id, text])));
    HELP_GROUPS.forEach((group) => texts.push([group.id, group.title]));
    HELP_SOURCES.forEach((source) => texts.push([source.title.hu, source.title], [source.title.hu, source.note]));
    for (const [where, text] of texts) {
      expect(text.hu.trim(), where).not.toBe("");
      expect(text.en.trim(), where).not.toBe("");
    }
  });

  it("shows and searches the help in English", async () => {
    setLanguage("en", { persist: false });
    const user = userEvent.setup();
    renderApp(<HelpPage />);

    expect(screen.getByRole("heading", { name: "Encoding settings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "nCore and the Hungarian release standard" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Psychovisual tuning" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "CRF quality" })).toBeInTheDocument();
    expect(screen.getByText(/Sample Adaptive Offset filter: smooths parts of the picture/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Kódolási beállítások" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "x264 (1080p)" }));
    expect(screen.queryByRole("heading", { name: "SAO" })).not.toBeInTheDocument();

    // The search looks at the English text: a Hungarian word finds nothing.
    await user.click(screen.getByRole("button", { name: "Both" }));
    await user.type(screen.getByRole("textbox", { name: "Search settings" }), "smears fine detail");
    expect(screen.getByRole("heading", { name: "SAO" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Annex B" })).not.toBeInTheDocument();

    await user.clear(screen.getByRole("textbox", { name: "Search settings" }));
    await user.type(screen.getByRole("textbox", { name: "Search settings" }), "szemcsét");
    expect(screen.getByText("No matches")).toBeInTheDocument();
  });

  it("opens a setting's help in English", async () => {
    setLanguage("en", { persist: false });
    const user = userEvent.setup();
    renderApp(<label><span>SAO<FieldHelpButton field="sao" encoder="x265" /></span><input type="checkbox" aria-label="SAO switch" /></label>);

    await user.click(screen.getByRole("button", { name: "SAO: help" }));
    const dialog = screen.getByRole("dialog", { name: "Help: SAO" });
    expect(within(dialog).getByText(/Almost always off for live action \(--no-sao\)/)).toBeInTheDocument();
    expect(within(dialog).getByText("Aither practice")).toBeInTheDocument();
    expect(within(dialog).getByText("nCore / Hungarian standard")).toBeInTheDocument();
    expect(encoderHelp("crf")?.title).toBe("CRF quality");
  });
});
