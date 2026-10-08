import { CircleHelp } from "lucide-react";
import { useState } from "react";
import { encoderHelp } from "../encoderHelp";
import type { EncoderHelpEntry, HelpEncoder } from "../encoderHelp";
import { t } from "../i18n";
import { Badge, Modal } from "./ui";

type HelpRowKey = "effect" | "values" | "grain" | "clean" | "animation" | "aither" | "ncore" | "caution";

/** The labelled rows under a setting's description, in display order. */
function helpRows(): Array<{ key: HelpRowKey; label: string }> {
  return [
    { key: "effect", label: t("Hatás", "Effect") },
    { key: "values", label: t("Szokásos értékek", "Typical values") },
    { key: "grain", label: t("Szemcsés film", "Grainy film") },
    { key: "clean", label: t("Tiszta, digitális film", "Clean, digital film") },
    { key: "animation", label: t("Animáció", "Animation") },
    { key: "aither", label: t("Aither-gyakorlat", "Aither practice") },
    { key: "ncore", label: t("nCore / magyar szabvány", "nCore / Hungarian standard") },
    { key: "caution", label: t("Figyelem", "Caution") },
  ];
}

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
        {helpRows().map(({ key, label }) => {
          const text = entry[key];
          return text ? <div key={key}><dt>{label}</dt><dd>{text}</dd></div> : null;
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
        aria-label={t(`${entry.title}: súgó`, `${entry.title}: help`)}
        title={t("Súgó", "Help")}
        onClick={(event) => {
          // The button sits inside the field's <label>: do not toggle the control.
          event.preventDefault();
          event.stopPropagation();
          setOpen(true);
        }}
      >
        <CircleHelp size={15} aria-hidden="true" />
      </button>
      <Modal open={open} title={t(`Súgó: ${entry.title}`, `Help: ${entry.title}`)} onClose={() => setOpen(false)}>
        <HelpEntryView entry={entry} encoder={encoder} />
      </Modal>
    </>
  );
}
