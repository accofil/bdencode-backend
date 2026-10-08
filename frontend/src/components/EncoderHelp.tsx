import { CircleHelp } from "lucide-react";
import { useState } from "react";
import { encoderHelp } from "../encoderHelp";
import type { EncoderHelpEntry, HelpEncoder } from "../encoderHelp";
import { Badge, Modal } from "./ui";

const ROWS: Array<{ key: keyof EncoderHelpEntry; label: string }> = [
  { key: "effect", label: "Hatás" },
  { key: "values", label: "Szokásos értékek" },
  { key: "grain", label: "Szemcsés film" },
  { key: "clean", label: "Tiszta, digitális film" },
  { key: "animation", label: "Animáció" },
  { key: "aither", label: "Aither-gyakorlat" },
  { key: "ncore", label: "nCore / magyar szabvány" },
  { key: "caution", label: "Figyelem" },
];

/** One setting's full help: what it does, its effect and the usual values. */
export function HelpEntryView({ entry, encoder }: { entry: EncoderHelpEntry; encoder?: HelpEncoder }) {
  return (
    <article className="help-entry" id={`help-${entry.field}`}>
      <header>
        <h3>{entry.title}</h3>
        <code>{entry.field}</code>
        {entry.encoders.map((item) => <Badge key={item} tone={item === encoder ? "info" : "neutral"}>{item}</Badge>)}
      </header>
      <p>{entry.what}</p>
      <dl>
        {ROWS.map(({ key, label }) => {
          const text = entry[key];
          return typeof text === "string" && text ? <div key={key}><dt>{label}</dt><dd>{text}</dd></div> : null;
        })}
      </dl>
    </article>
  );
}

/** A "?" next to a wizard setting that opens its help. */
export function FieldHelpButton({ field, encoder }: { field: string; encoder?: HelpEncoder }) {
  const entry = encoderHelp(field);
  const [open, setOpen] = useState(false);
  if (!entry) return null;
  return (
    <>
      <button
        type="button"
        className="field-help-button"
        aria-label={`${entry.title}: súgó`}
        title="Súgó"
        onClick={(event) => {
          // The button sits inside the field's <label>: do not toggle the control.
          event.preventDefault();
          event.stopPropagation();
          setOpen(true);
        }}
      >
        <CircleHelp size={15} aria-hidden="true" />
      </button>
      <Modal open={open} title={`Súgó: ${entry.title}`} onClose={() => setOpen(false)}>
        <HelpEntryView entry={entry} encoder={encoder} />
      </Modal>
    </>
  );
}
