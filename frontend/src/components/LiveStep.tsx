import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, LoaderCircle, PauseCircle, Timer, XCircle } from "lucide-react";
import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { JobLive, LiveStep, LiveStepMetrics, LiveTimelineEntry } from "../api/types";
import { formatDuration, formatGB } from "../utils";
import { Badge, Card, ProgressBar } from "./ui";

/** How often a page asks for the live step while the worker runs the job. */
export const LIVE_POLL_MS = 2000;

/** The size search accepts a projection this far above the target. */
const SIZE_TOLERANCE = 0.04;

export function useJobLive(jobId: string, running: boolean) {
  const queryClient = useQueryClient();
  const wasRunning = useRef(running);
  useEffect(() => {
    // Polling stops with the job: fetch once more so the last finished step
    // lands in the timeline (and once when the worker picks the job up).
    if (wasRunning.current === running) return;
    wasRunning.current = running;
    void queryClient.invalidateQueries({ queryKey: ["job-live", jobId] });
  }, [jobId, queryClient, running]);
  return useQuery({
    queryKey: ["job-live", jobId],
    queryFn: () => api.jobLive(jobId),
    refetchInterval: running ? LIVE_POLL_MS : false,
    enabled: jobId.length > 0,
  });
}

function serverNow(live: JobLive): number {
  return typeof live.now === "number" && Number.isFinite(live.now) ? live.now : Date.now() / 1000;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** One decimal, rounded down: a step never shows 100% before it has finished. */
export function stepPercent(fraction: number): string {
  const tenths = Math.floor(Math.max(0, Math.min(1, fraction)) * 1000);
  return `${(tenths / 10).toFixed(1)}%`;
}

/** Seconds left: the encoder's own estimate when it gives one, aged to now. */
export function remainingSeconds(step: LiveStep, now: number): number | null {
  const eta = finite(step.metrics?.eta_seconds) ?? finite(step.eta_seconds);
  if (eta === null) return null;
  return Math.max(0, eta - Math.max(0, now - step.updated_at));
}

function clockTime(epochSeconds: number): string {
  return new Intl.DateTimeFormat("hu-HU", { hour: "2-digit", minute: "2-digit" }).format(new Date(epochSeconds * 1000));
}

function fullTime(epochSeconds: number): string {
  return new Intl.DateTimeFormat("hu-HU", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(epochSeconds * 1000));
}

function SizeVerdict({ projected, target }: { projected: number; target: number }) {
  const over = projected / target - 1;
  if (over <= SIZE_TOLERANCE) return <Badge tone="success">célon belül</Badge>;
  return <Badge tone="warning">{`+${Math.round(over * 100)}% a cél felett`}</Badge>;
}

function EncodeFacts({ metrics }: { metrics: LiveStepMetrics }) {
  const fps = finite(metrics.fps);
  const speed = finite(metrics.speed);
  const output = finite(metrics.output_bytes);
  const projected = finite(metrics.projected_bytes);
  const target = finite(metrics.target_bytes);
  return (
    <>
      {fps !== null && (
        <div><dt>Sebesség</dt><dd>{`${fps.toFixed(fps < 10 ? 2 : 1)} fps${speed !== null ? ` · ${speed.toFixed(3)}×` : ""}`}</dd></div>
      )}
      {output !== null && <div><dt>Eddig kiírva</dt><dd>{formatGB(output, 2)}</dd></div>}
      {projected !== null && (
        <div>
          <dt>Várható videóméret</dt>
          <dd>
            {formatGB(projected)}
            {target !== null && <> / cél {formatGB(target)} <SizeVerdict projected={projected} target={target} /></>}
          </dd>
        </div>
      )}
      {projected === null && target !== null && <div><dt>Méretcél</dt><dd>{formatGB(target)}</dd></div>}
    </>
  );
}

/** The running step with its own percentage, times and side tasks. */
export function LiveStepPanel({ live }: { live: JobLive }) {
  const step = live.step;
  if (!step) return null;
  const now = serverNow(live);
  const elapsed = Math.max(0, now - step.started_at);
  const remaining = remainingSeconds(step, now);
  const fraction = finite(step.fraction);
  const sides = Object.entries(step.side ?? {});
  return (
    <div className="live-step" data-step={step.key}>
      <div className="live-step__head">
        <div>
          <span className="eyebrow">Most fut</span>
          <strong>{step.label}</strong>
          {step.detail && <small>{step.detail}</small>}
        </div>
        <span className="live-step__percent">
          {fraction !== null ? stepPercent(fraction) : <LoaderCircle className="spin" size={20} role="img" aria-label="Folyamatban, az aránya nem mérhető" />}
        </span>
      </div>
      <ProgressBar value={fraction ?? 0} indeterminate={fraction === null} ariaLabel={`${step.label} folyamata`} />
      <dl className="live-step__facts">
        <div><dt>Eltelt</dt><dd>{formatDuration(elapsed)}</dd></div>
        {remaining !== null && <div><dt>Hátralévő</dt><dd>~{formatDuration(remaining)}</dd></div>}
        <EncodeFacts metrics={step.metrics ?? {}} />
      </dl>
      {sides.length > 0 && (
        <div className="live-step__side" aria-label="Párhuzamosan futó feladatok">
          {sides.map(([key, task]) => {
            const sideFraction = finite(task.fraction);
            return (
              <div key={key} className="live-side">
                <span>{task.label}</span>
                {task.done ? (
                  <span className="live-side__done"><CheckCircle2 size={13} aria-hidden="true" /> kész</span>
                ) : (
                  <span>{sideFraction !== null ? stepPercent(sideFraction) : "fut…"}</span>
                )}
                {!task.done && (
                  <ProgressBar
                    className="progress-wrap--thin"
                    value={sideFraction ?? 0}
                    indeterminate={sideFraction === null}
                    ariaLabel={`${task.label} folyamata`}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** The running step in one line, for the dashboard's active-job card. */
export function LiveStepLine({ jobId, running }: { jobId: string; running: boolean }) {
  const live = useJobLive(jobId, running);
  const step = running ? live.data?.step : null;
  if (!step) return null;
  const fraction = finite(step.fraction);
  return (
    <div className="live-line">
      <div className="live-line__text">
        <span>Most: <strong>{step.label}</strong></span>
        <span>{fraction !== null ? stepPercent(fraction) : "folyamatban"}</span>
      </div>
      <ProgressBar
        className="progress-wrap--thin"
        value={fraction ?? 0}
        indeterminate={fraction === null}
        ariaLabel={`${step.label} folyamata`}
      />
      {step.detail && <small>{step.detail}</small>}
    </div>
  );
}

const OUTCOMES: Record<string, { label: string; icon: typeof CheckCircle2 }> = {
  done: { label: "kész", icon: CheckCircle2 },
  failed: { label: "hiba", icon: XCircle },
  interrupted: { label: "megszakítva", icon: PauseCircle },
  review: { label: "ellenőrzést kért", icon: AlertTriangle },
};

function TimelineRow({ entry }: { entry: LiveTimelineEntry }) {
  const outcome = OUTCOMES[entry.outcome] ? entry.outcome : "done";
  const { label, icon: Icon } = OUTCOMES[outcome];
  return (
    <li className={`step-timeline__item step-timeline__item--${outcome}`}>
      <Icon size={15} role="img" aria-label={label} />
      <span>{entry.label}{outcome !== "done" && <small> · {label}</small>}</span>
      <time dateTime={new Date(entry.started_at * 1000).toISOString()} title={fullTime(entry.started_at)}>{clockTime(entry.started_at)}</time>
      <strong>{formatDuration(entry.seconds)}</strong>
    </li>
  );
}

/** Every finished step with its duration, and the running one with its time so far. */
export function StepTimelineCard({ live, showStep }: { live: JobLive | undefined; showStep: boolean }) {
  if (!live) return null;
  const step = showStep ? live.step : null;
  if (live.timeline.length === 0 && !step) return null;
  const now = serverNow(live);
  const total = live.timeline.reduce((sum, entry) => sum + (finite(entry.seconds) ?? 0), 0);
  return (
    <Card className="step-timeline-card">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Timer size={19} /></span>
          <div><h2>Lépések időtartama</h2><p>A worker részfolyamatai időrendben</p></div>
        </div>
        {total > 0 && <Badge>{`Összesen ${formatDuration(total)}`}</Badge>}
      </div>
      <ol className="step-timeline">
        {live.timeline.map((entry, index) => <TimelineRow key={`${entry.key}-${entry.started_at}-${index}`} entry={entry} />)}
        {step && (
          <li className="step-timeline__item step-timeline__item--running">
            <LoaderCircle className="spin" size={15} role="img" aria-label="fut" />
            <span>{step.label}<small> · fut</small></span>
            <time dateTime={new Date(step.started_at * 1000).toISOString()} title={fullTime(step.started_at)}>{clockTime(step.started_at)}</time>
            <strong>{formatDuration(Math.max(0, now - step.started_at))}</strong>
          </li>
        )}
      </ol>
    </Card>
  );
}
