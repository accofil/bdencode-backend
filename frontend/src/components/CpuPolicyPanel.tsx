import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Moon, Save, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CpuPolicy, CpuPolicyView } from "../api/types";
import { t } from "../i18n";
import { formatDate } from "../utils";
import { Badge, Button, Card, LoadingPanel, Notice } from "./ui";

export function useCpuPolicy() {
  return useQuery({ queryKey: ["cpu-policy"], queryFn: api.cpuPolicy, refetchInterval: 60_000, retry: false });
}

/** The share the worker runs with now: what the helper applied, else the installed default. */
export function cpuShareInForce(view: CpuPolicyView | undefined): { percent: number; mode: "day" | "night" } | null {
  if (!view) return null;
  const applied = view.applied;
  if (applied?.state === "applied" && typeof applied.percent === "number") {
    return { percent: applied.percent, mode: applied.mode === "night" ? "night" : "day" };
  }
  return { percent: view.install_default_percent, mode: "day" };
}

function browserTimezone(): string | null {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone && /^[A-Za-z0-9_+-]+(?:\/[A-Za-z0-9_+-]+){0,2}$/.test(zone) ? zone : null;
  } catch {
    return null;
  }
}

function PercentSlider({ label, value, min, max, disabled, onChange }: { label: string; value: number; min: number; max: number; disabled?: boolean; onChange: (value: number) => void }) {
  return (
    <label className="cpu-slider">
      <span>{label}<strong>{value}%</strong></span>
      <input type="range" min={min} max={max} step={5} value={value} disabled={disabled} aria-label={label} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

export function CpuPolicyPanel() {
  const queryClient = useQueryClient();
  const view = useCpuPolicy();
  const [draft, setDraft] = useState<CpuPolicy | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (view.data && !dirty) setDraft(view.data.policy);
  }, [dirty, view.data]);
  const save = useMutation({
    mutationFn: (policy: CpuPolicy) => api.saveCpuPolicy({ ...policy, timezone: browserTimezone() }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["cpu-policy"], updated);
      setDirty(false);
      setDraft(updated.policy);
      // The helper applies the file within seconds: look again shortly.
      window.setTimeout(() => void queryClient.invalidateQueries({ queryKey: ["cpu-policy"] }), 4000);
      void queryClient.invalidateQueries({ queryKey: ["capabilities"] });
    },
  });

  if (view.isLoading) return <Card className="cpu-policy-card"><LoadingPanel label={t("CPU-keret betöltése…", "Loading the CPU share…")} /></Card>;
  if (view.isError || !view.data || !draft) {
    return <Card className="cpu-policy-card"><Notice tone="warning" title={t("A CPU-keret nem olvasható", "The CPU share cannot be read")}>{view.error instanceof ApiError ? view.error.detail : t("Az API nem adta vissza a CPU-beállítást.", "The API did not return the CPU setting.")}</Notice></Card>;
  }
  const data = view.data;
  const { min_percent: min, max_percent: max } = data.limits;
  const cpus = data.logical_cpus;
  const inForce = cpuShareInForce(data);
  const applied = data.applied;
  const update = (change: Partial<CpuPolicy> | ((current: CpuPolicy) => CpuPolicy)) => {
    setDirty(true);
    setDraft((current) => (current === null ? current : typeof change === "function" ? change(current) : { ...current, ...change }));
  };
  const night = draft.night;

  return (
    <Card className="cpu-policy-card">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Cpu size={19} /></span>
          <div><h2>{t("CPU-keret", "CPU share")}</h2><p>{t(
            `A kódoló legfeljebb ekkora részt kap a gép ${cpus ?? "?"} logikai CPU-jából. Futó kódolásnál is azonnal érvényes.`,
            `The encoder gets at most this share of the machine's ${cpus ?? "?"} logical CPUs. It takes effect at once, even during an encode.`,
          )}</p></div>
        </div>
        {inForce && <Badge tone="info">{t(
          `Most: ${inForce.percent}% · ${inForce.mode === "night" ? "éjszakai" : "nappali"}`,
          `Now: ${inForce.percent}% · ${inForce.mode === "night" ? "night" : "day"}`,
        )}</Badge>}
      </div>
      <div className="cpu-policy-grid">
        <div className="cpu-policy-block">
          <span className="cpu-policy-block__title"><Sun size={16} aria-hidden="true" /> {t("Nappal", "Day")}</span>
          <PercentSlider label={t("Nappali CPU-keret", "Day CPU share")} value={draft.day_percent} min={min} max={max} onChange={(value) => update({ day_percent: value })} />
          {cpus !== null && <small>{t(`≈ ${((cpus * draft.day_percent) / 100).toFixed(1)} logikai CPU`, `≈ ${((cpus * draft.day_percent) / 100).toFixed(1)} logical CPUs`)}</small>}
        </div>
        <div className="cpu-policy-block">
          <label className="toggle-row toggle-row--compact">
            <span><strong><Moon size={15} aria-hidden="true" /> {t("Éjszakai mód", "Night mode")}</strong><small>{t("Más keret a megadott idősávban (például éjjel teljes gőzzel).", "A different share in the given time window (for example full speed at night).")}</small></span>
            <input type="checkbox" checked={night.enabled} onChange={(event) => update((current) => ({ ...current, night: { ...current.night, enabled: event.target.checked } }))} />
            <span className="toggle" aria-hidden="true" />
          </label>
          <PercentSlider label={t("Éjszakai CPU-keret", "Night CPU share")} value={night.percent} min={min} max={max} disabled={!night.enabled} onChange={(value) => update((current) => ({ ...current, night: { ...current.night, percent: value } }))} />
          <div className="cpu-policy-times">
            <label className="field"><span>{t("Kezdete", "Start")}</span><input type="time" value={night.start} disabled={!night.enabled} aria-label={t("Éjszakai mód kezdete", "Night mode start")} onChange={(event) => update((current) => ({ ...current, night: { ...current.night, start: event.target.value } }))} /></label>
            <label className="field"><span>{t("Vége", "End")}</span><input type="time" value={night.end} disabled={!night.enabled} aria-label={t("Éjszakai mód vége", "Night mode end")} onChange={(event) => update((current) => ({ ...current, night: { ...current.night, end: event.target.value } }))} /></label>
          </div>
        </div>
      </div>
      <div className="cpu-policy-footer">
        <small>
          {applied?.state === "applied"
            ? t(
              `A worker ${applied.percent}%-os kerettel fut (${applied.mode === "night" ? "éjszakai" : "nappali"}), beállítva: ${formatDate(applied.applied_at ?? null)}.`,
              `The worker runs with a ${applied.percent}% share (${applied.mode === "night" ? "night" : "day"}), set: ${formatDate(applied.applied_at ?? null)}.`,
            )
            : t(
              `A telepítéskori ${data.install_default_percent}%-os keret van érvényben.`,
              `The ${data.install_default_percent}% share from the install is in effect.`,
            )}
        </small>
        <Button icon={<Save size={16} />} loading={save.isPending} disabled={!dirty || (night.enabled && (!night.start || !night.end))} onClick={() => save.mutate(draft)}>{t("Mentés", "Save")}</Button>
      </div>
      {applied === null && data.saved && <Notice tone="info" title={t("Az alkalmazó még nem futott", "The applier has not run yet")}>{t(
        "A mentett keretet a rendszerszintű segéd (bdencode-cpu-policy) állítja be; a 2.10-es telepítés óta pár másodpercen belül. Addig a telepítéskori keret marad érvényben.",
        "The system helper (bdencode-cpu-policy) applies the saved share; since the 2.10 install, within a few seconds. Until then the share from the install stays in effect.",
      )}</Notice>}
      {(applied?.state === "invalid" || applied?.state === "failed") && <Notice tone="warning" title={t("A keret beállítása nem sikerült", "Setting the share failed")}>{applied.message ?? t("Ismeretlen hiba", "Unknown error")}</Notice>}
      {save.isError && <Notice tone="danger" title={t("A mentés nem sikerült", "Saving failed")}>{save.error instanceof ApiError ? save.error.detail : save.error.message}</Notice>}
    </Card>
  );
}
