import { BookOpen, ExternalLink, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { HelpEntryView } from "../components/EncoderHelp";
import { Card, EmptyState, PageHeader } from "../components/ui";
import { ENCODER_HELP, encoderHelp, HELP_GROUPS, HELP_SECTIONS, HELP_SOURCES } from "../encoderHelp";
import type { EncoderHelpEntry, HelpEncoder } from "../encoderHelp";

type Filter = "all" | HelpEncoder;

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "Mindkettő" },
  { value: "x264", label: "x264 (1080p)" },
  { value: "x265", label: "x265 (UHD)" },
];

function matches(entry: EncoderHelpEntry, needle: string): boolean {
  if (!needle) return true;
  return [entry.field, entry.title, entry.what, entry.effect, entry.values, entry.grain, entry.clean, entry.animation, entry.aither, entry.caution]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase("hu")
    .includes(needle);
}

export function HelpPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const needle = search.trim().toLocaleLowerCase("hu");
  const groups = useMemo(() => HELP_GROUPS.map((group) => ({
    ...group,
    entries: group.fields
      .map((field) => encoderHelp(field))
      .filter((entry): entry is EncoderHelpEntry => Boolean(entry))
      .filter((entry) => filter === "all" || entry.encoders.includes(filter))
      .filter((entry) => matches(entry, needle)),
  })).filter((group) => group.entries.length > 0), [filter, needle]);
  const shown = groups.reduce((total, group) => total + group.entries.length, 0);

  return (
    <div className="page page--help">
      <PageHeader
        eyebrow="Súgó"
        title="Kódolási beállítások"
        description="Az x264 és az x265 választható beállításai az Aither-kódolók gyakorlata, a nyilvános kódolási útmutatók és a kódolók dokumentációja alapján."
      />

      <div className="help-sections">
        {HELP_SECTIONS.map((section) => (
          <Card key={section.id} className="help-section">
            <h2>{section.title}</h2>
            {section.paragraphs.map((paragraph) => <p key={paragraph.slice(0, 32)}>{paragraph}</p>)}
          </Card>
        ))}
      </div>

      <div className="help-toolbar">
        <div className="segmented" role="group" aria-label="Kódoló">
          {FILTERS.map((item) => (
            <button key={item.value} type="button" className={filter === item.value ? "active" : ""} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}</button>
          ))}
        </div>
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <input aria-label="Beállítás keresése" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Beállítás keresése…" />
        </label>
        <small>{shown} / {ENCODER_HELP.length} beállítás</small>
      </div>

      {groups.length === 0 ? (
        <EmptyState icon={<BookOpen size={28} />} title="Nincs találat" description="Próbálj más kifejezést, vagy válaszd a „Mindkettő” szűrőt." />
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
        <h2>Források</h2>
        <ul>
          {HELP_SOURCES.map((source) => (
            <li key={source.title}>
              {source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title} <ExternalLink size={13} aria-hidden="true" /></a> : <strong>{source.title}</strong>}
              <small>{source.note}</small>
            </li>
          ))}
        </ul>
        <p className="muted-copy">Az értékek kiindulópontok: a végső beállítást az adott forrás próbakódolása és a B-frame-es képpárok összevetése dönti el.</p>
      </Card>
    </div>
  );
}
