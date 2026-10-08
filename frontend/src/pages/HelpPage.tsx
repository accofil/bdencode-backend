import { BookOpen, ExternalLink, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { HelpEntryView } from "../components/EncoderHelp";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { ENCODER_HELP, encoderHelp, HELP_GROUPS, HELP_SECTIONS, HELP_SOURCES } from "../encoderHelp";
import type { EncoderHelpEntry, HelpEncoder } from "../encoderHelp";
import { locale, t, tx, useLanguage } from "../i18n";

type Filter = "all" | HelpEncoder;

function filters(): Array<{ value: Filter; label: string }> {
  return [
    { value: "all", label: t("Mindkettő", "Both") },
    { value: "x264", label: "x264 (1080p)" },
    { value: "x265", label: "x265 (UHD)" },
  ];
}

/** Whether the entry's text in the current language contains the (lower-cased) needle. */
function matches(entry: EncoderHelpEntry, needle: string): boolean {
  if (!needle) return true;
  return [entry.field, entry.title, entry.what, entry.effect, entry.values, entry.grain, entry.clean, entry.animation, entry.aither, entry.caution]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase(locale())
    .includes(needle);
}

export function HelpPage() {
  const language = useLanguage();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const needle = search.trim().toLocaleLowerCase(locale());
  const groups = useMemo(() => HELP_GROUPS.map((group) => ({
    id: group.id,
    title: tx(group.title),
    entries: group.fields
      .map((field) => encoderHelp(field))
      .filter((entry): entry is EncoderHelpEntry => Boolean(entry))
      .filter((entry) => filter === "all" || entry.encoders.includes(filter))
      .filter((entry) => matches(entry, needle)),
  })).filter((group) => group.entries.length > 0), [filter, needle, language]);
  const shown = groups.reduce((total, group) => total + group.entries.length, 0);

  return (
    <div className="page page--help">
      <PageHeader
        eyebrow={t("Súgó", "Help")}
        title={t("Kódolási beállítások", "Encoding settings")}
        description={t(
          "Az x264 és az x265 választható beállításai az Aither-kódolók gyakorlata, a nyilvános kódolási útmutatók és a kódolók dokumentációja alapján.",
          "The selectable x264 and x265 settings, based on the practice of Aither encoders, public encoding guides and the encoders' documentation.",
        )}
      />

      <div className="help-sections">
        {HELP_SECTIONS.map((section) => (
          <Card key={section.id} className="help-section">
            <h2>{tx(section.title)}</h2>
            {section.paragraphs.map((paragraph) => <p key={paragraph.hu.slice(0, 32)}>{tx(paragraph)}</p>)}
          </Card>
        ))}
      </div>

      <div className="help-toolbar">
        <div className="segmented" role="group" aria-label={t("Kódoló", "Encoder")}>
          {filters().map((item) => (
            <button key={item.value} type="button" className={filter === item.value ? "active" : ""} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}</button>
          ))}
        </div>
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <input aria-label={t("Beállítás keresése", "Search settings")} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Beállítás keresése…", "Search settings…")} />
        </label>
        <small>{shown} / {ENCODER_HELP.length} {t("beállítás", "settings")}</small>
      </div>

      {groups.length === 0 ? (
        <EmptyState
          icon={<BookOpen size={28} />}
          title={t("Nincs találat", "No matches")}
          description={t("Próbálj más kifejezést, vagy válaszd a „Mindkettő” szűrőt.", "Try a different term, or choose the “Both” filter.")}
        />
      ) : groups.map((group) => (
        <section key={group.id} className="help-group" aria-labelledby={`help-group-${group.id}`}>
          <h2 id={`help-group-${group.id}`}>{group.title}</h2>
          <div className="help-entries">
            {group.entries.map((entry) => (
              <Card key={entry.field} className="help-entry-card">
                <HelpEntryView entry={entry} encoder={filter === "all" ? undefined : filter} />
              </Card>
            ))}
          </div>
        </section>
      ))}

      <Card className="help-sources">
        <h2>{t("Források", "Sources")}</h2>
        <ul>
          {HELP_SOURCES.map((source) => (
            <li key={source.title.hu}>
              {source.url ? <a href={source.url} target="_blank" rel="noreferrer">{tx(source.title)} <ExternalLink size={13} aria-hidden="true" /></a> : <strong>{tx(source.title)}</strong>}
              <small>{tx(source.note)}</small>
            </li>
          ))}
        </ul>
        <p className="muted-copy">{t(
          "Az értékek kiindulópontok: a végső beállítást az adott forrás próbakódolása és a B-frame-es képpárok összevetése dönti el.",
          "The values are starting points: the final setting is decided by a test encode of the actual source and a comparison of B-frame screenshot pairs.",
        )}</p>
      </Card>
    </div>
  );
}
