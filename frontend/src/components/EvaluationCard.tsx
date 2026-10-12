import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";
import { api, ApiError } from "../api/client";
import type { Job, JobEvaluation, LocalizedPair } from "../api/types";
import { getLanguage, t, useLanguage } from "../i18n";
import { Badge, Button, Card, Notice } from "./ui";

const VERDICTS: Record<JobEvaluation["verdict"], { tone: "success" | "info" | "warning" | "danger"; hu: string; en: string }> = {
  transparent: { tone: "success", hu: "Átlátszó", en: "Transparent" },
  good: { tone: "info", hu: "Jó", en: "Good" },
  acceptable: { tone: "warning", hu: "Elfogadható", en: "Acceptable" },
  weak: { tone: "danger", hu: "Gyenge", en: "Weak" },
};

const FIELD_LABELS: Record<string, [string, string]> = {
  crf: ["CRF", "CRF"],
  aq_strength: ["AQ-erősség", "AQ strength"],
  aq_mode: ["AQ-mód", "AQ mode"],
  psy_rd: ["Psy-RD", "Psy-RD"],
  psy_rdoq: ["Psy-RDOQ", "Psy-RDOQ"],
  deblock_alpha: ["Deblock (alfa)", "Deblock (alpha)"],
  deblock_beta: ["Deblock (béta)", "Deblock (beta)"],
  bframes: ["B-képek", "B-frames"],
  ref: ["Referenciák", "References"],
  qcomp: ["qcomp", "qcomp"],
};

function pick(pair: LocalizedPair): string {
  return getLanguage() === "hu" ? pair.hu : pair.en;
}

function number(value: number | null | undefined, digits: number): string {
  return typeof value === "number" ? value.toFixed(digits) : "—";
}

function sourceLabel(evaluation: JobEvaluation): string {
  if (evaluation.source === "deterministic") return t("Rögzített szabályok alapján", "By fixed rules");
  const provider = evaluation.source === "anthropic" ? "Claude" : "OpenAI";
  return t(`AI-értékelés: ${provider}${evaluation.model ? ` · ${evaluation.model}` : ""}`, `AI evaluation: ${provider}${evaluation.model ? ` · ${evaluation.model}` : ""}`);
}

/** The verdict on a finished encode, with setting changes for a similar disc. */
export function EvaluationCard({ job }: { job: Job }) {
  useLanguage();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["evaluation", job.id],
    queryFn: () => api.jobEvaluation(job.id),
    enabled: job.state === "COMPLETED",
    retry: false,
  });
  const evaluate = useMutation({
    mutationFn: (useAi: boolean) => api.evaluateJob(job.id, useAi),
    onSuccess: (data) => queryClient.setQueryData(["evaluation", job.id], data),
  });
  const autoStarted = useRef(false);
  const data = query.data;
  useEffect(() => {
    // With an AI key the first visit asks the AI once; the answer is saved.
    if (data && data.ai_available && !data.ai_attempted && data.source === "deterministic" && !autoStarted.current) {
      autoStarted.current = true;
      evaluate.mutate(true);
    }
  }, [data, evaluate]);

  if (job.state !== "COMPLETED") return null;
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) return null;
    return <Notice tone="warning" title={t("Az értékelés nem érhető el", "The evaluation is not available")}>{query.error instanceof Error ? query.error.message : ""}</Notice>;
  }
  if (!data) return null;
  const verdict = VERDICTS[data.verdict];
  const facts = data.facts;
  const saving = facts.sizes.saving_ratio;

  return (
    <Card className="evaluation-card">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Gauge size={19} /></span>
          <div>
            <h2>{t("Értékelés", "Evaluation")} <Badge tone={verdict.tone}>{t(verdict.hu, verdict.en)}</Badge></h2>
            <p>{sourceLabel(data)}{data.confidence !== null ? ` · ${t("bizonyosság", "confidence")} ${Math.round(data.confidence * 100)}%` : ""}</p>
          </div>
        </div>
        <div className="evaluation-card__actions">
          {data.ai_available && <Button variant="secondary" icon={<Sparkles size={16} />} loading={evaluate.isPending && evaluate.variables === true} disabled={evaluate.isPending} onClick={() => evaluate.mutate(true)}>{t("Újraértékelés AI-val", "Re-evaluate with AI")}</Button>}
          <Button variant="ghost" icon={<RefreshCw size={16} />} loading={evaluate.isPending && evaluate.variables === false} disabled={evaluate.isPending} onClick={() => evaluate.mutate(false)}>{t("Szabályalapú értékelés", "Rule-based evaluation")}</Button>
        </div>
      </div>
      {evaluate.isPending && evaluate.variables === true && <Notice tone="info" title={t("Az AI értékel…", "The AI is evaluating…")}>{t("Ez fél percig is eltarthat.", "This can take half a minute.")}</Notice>}
      <p className="evaluation-card__summary">{pick(data.summary)}</p>
      <dl className="operator-review__facts">
        <div><dt>VMAF</dt><dd>{number(facts.vmaf.mean, 2)} · 1% low {number(facts.vmaf.one_percent_low, 2)}</dd></div>
        <div><dt>SSIM</dt><dd>{number(facts.metrics.ssim_mean, 4)}</dd></div>
        <div><dt>PSNR</dt><dd>{number(facts.metrics.psnr_mean_db, 1)} dB</dd></div>
        <div><dt>{t("Megtakarítás", "Saving")}</dt><dd>{typeof saving === "number" ? `${Math.round(saving * 100)}%` : "—"}</dd></div>
        <div><dt>{t("Videó bitráta", "Video bitrate")}</dt><dd>{number(facts.sizes.video_kbps, 0)} kb/s</dd></div>
      </dl>
      {data.findings.length > 0 && <ul className="operator-review__findings">{data.findings.map((item, index) => <li key={index}>{pick(item)}</li>)}</ul>}
      {data.suggestions.length > 0 ? (
        <div className="evaluation-card__suggestions">
          <strong>{t("Javasolt változtatás hasonló lemezhez", "Suggested change for a similar disc")}</strong>
          <ul className="operator-review__hosts" aria-label={t("Javasolt beállítások", "Suggested settings")}>
            {data.suggestions.map((item) => (
              <li key={item.field}>
                <strong>{t(...(FIELD_LABELS[item.field] ?? [item.field, item.field]))}: {String(item.current ?? "—")} → {item.value}</strong>
                {typeof item.estimated_size_change_percent === "number" && <Badge tone="info">{t("méret", "size")} {item.estimated_size_change_percent > 0 ? "+" : ""}{item.estimated_size_change_percent}%</Badge>}
                <small>{pick(item.reason)}</small>
              </li>
            ))}
          </ul>
        </div>
      ) : <p className="evaluation-card__none">{t("A beállításokon nincs mit változtatni.", "The settings need no change.")}</p>}
      {data.ai_error && <Notice tone="warning" title={t("Az AI-értékelés nem sikerült; a rögzített szabályok eredménye látszik", "The AI evaluation failed; the fixed-rule result is shown")}>{data.ai_error}</Notice>}
      {evaluate.isError && <Notice tone="danger" title={t("Az értékelés nem sikerült", "The evaluation failed")}>{evaluate.error instanceof ApiError ? evaluate.error.detail : evaluate.error.message}</Notice>}
    </Card>
  );
}
