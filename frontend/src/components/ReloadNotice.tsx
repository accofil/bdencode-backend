import type { EvaluationSuggestion, Job, LocalizedPair } from "../api/types";
import { getLanguage, t } from "../i18n";
import { FIELD_LABELS } from "./EvaluationCard";
import { Badge, Notice } from "./ui";

/** Where a job loaded again from a finished one came from (``settings.reload``). */
export interface ReloadOrigin {
  fromJobId: string;
  fromName: string;
  mode: "clean" | "same";
  selection: Record<string, unknown> | null;
  suggestions: EvaluationSuggestion[];
  evaluated: boolean;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function localized(value: unknown): LocalizedPair | null {
  const pair = record(value);
  return pair && typeof pair.hu === "string" && typeof pair.en === "string" ? { hu: pair.hu, en: pair.en } : null;
}

function suggestion(value: unknown): EvaluationSuggestion | null {
  const item = record(value);
  if (!item || typeof item.field !== "string" || typeof item.value !== "number") return null;
  const reason = localized(item.reason);
  if (!reason) return null;
  const current = typeof item.current === "number" || typeof item.current === "string" ? item.current : null;
  return {
    field: item.field,
    current,
    value: item.value,
    reason,
    ...(typeof item.estimated_size_change_percent === "number" ? { estimated_size_change_percent: item.estimated_size_change_percent } : {}),
  };
}

export function reloadOrigin(job: Pick<Job, "settings">): ReloadOrigin | null {
  const raw = record(job.settings?.reload);
  if (!raw || typeof raw.from_job_id !== "string" || (raw.mode !== "clean" && raw.mode !== "same")) return null;
  const suggestions = Array.isArray(raw.suggestions)
    ? raw.suggestions.map(suggestion).filter((item): item is EvaluationSuggestion => item !== null)
    : [];
  return {
    fromJobId: raw.from_job_id,
    fromName: typeof raw.from_name === "string" ? raw.from_name : raw.from_job_id,
    mode: raw.mode,
    selection: raw.mode === "same" ? record(raw.selection) : null,
    suggestions,
    evaluated: record(raw.evaluation) !== null,
  };
}

function pick(pair: LocalizedPair): string {
  return getLanguage() === "hu" ? pair.hu : pair.en;
}

/**
 * The note on a job loaded again from a finished one.  With the same
 * settings it lists what the evaluation of the finished encode suggests;
 * nothing of it is applied, the operator decides.
 */
export function ReloadNotice({ job }: { job: Pick<Job, "settings"> }) {
  const origin = reloadOrigin(job);
  if (!origin) return null;
  if (origin.mode === "clean") {
    return (
      <Notice tone="info" title={t("Újrakezdés tiszta lappal", "Started again with a clean slate")}>
        {t(`A(z) „${origin.fromName}” munka forrása, alapbeállításokkal. A korábbi munka és kiadása változatlan.`, `The source of “${origin.fromName}”, with default settings. The earlier job and its release are unchanged.`)}
      </Notice>
    );
  }
  return (
    <Notice tone="info" title={t("Újrakezdés a korábbi beállításokkal", "Started again with the earlier settings")}>
      <p>{t(`A(z) „${origin.fromName}” munka jóváhagyott beállításai vannak betöltve. A korábbi munka és kiadása változatlan.`, `The approved settings of “${origin.fromName}” are loaded. The earlier job and its release are unchanged.`)}</p>
      {origin.suggestions.length > 0 ? (
        <div className="evaluation-card__suggestions">
          <strong>{t("Javasolt módosítások a korábbi encode értékelése alapján (nincsenek alkalmazva):", "Suggested changes from the evaluation of the earlier encode (not applied):")}</strong>
          <ul className="operator-review__hosts" aria-label={t("Javasolt módosítások", "Suggested changes")}>
            {origin.suggestions.map((item) => (
              <li key={item.field}>
                <strong>{t(...(FIELD_LABELS[item.field] ?? [item.field, item.field]))}: {String(item.current ?? "—")} → {item.value}</strong>
                {typeof item.estimated_size_change_percent === "number" && <Badge tone="info">{t("méret", "size")} {item.estimated_size_change_percent > 0 ? "+" : ""}{item.estimated_size_change_percent}%</Badge>}
                <small>{pick(item.reason)}</small>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="evaluation-card__none">{origin.evaluated
          ? t("A korábbi encode értékelése nem javasolt módosítást.", "The evaluation of the earlier encode suggested no change.")
          : t("A korábbi munkának nincs értékelése, ezért nincs javaslat.", "The earlier job has no evaluation, so there is no suggestion.")}</p>
      )}
    </Notice>
  );
}
