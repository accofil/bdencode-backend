import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Moon, Save, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CpuPolicy, CpuPolicyView } from "../api/types";
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

  if (view.isLoading) return <Card className="cpu-policy-card"><LoadingPanel label="CPU-keret betöltése…" /></Card>;
  if (view.isError || !view.data || !draft) {
    return <Card className="cpu-policy-card"><Notice tone="warning" title="A CPU-keret nem olvasható">{view.error instanceof ApiError ? view.error.detail : "Az API nem adta vissza a CPU-beállítást."}</Notice></Card>;
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
          <div><h2>CPU-keret</h2><p>A kódoló legfeljebb ekkora részt kap a gép {cpus ?? "?"} logikai CPU-jából. Futó kódolásnál is azonnal érvényes.</p></div>
        </div>
        {inForce && <Badge tone="info">{`Most: ${inForce.percent}% · ${inForce.mode === "night" ? "éjszakai" : "nappali"}`}</Badge>}
      </div>
      <div className="cpu-policy-grid">
        <div className="cpu-policy-block">
          <span className="cpu-policy-block__title"><Sun size={16} aria-hidden="true" /> Nappal</span>
          <PercentSlider label="Nappali CPU-keret" value={draft.day_percent} min={min} max={max} onChange={(value) => update({ day_percent: value })} />
          {cpus !== null && <small>{`≈ ${((cpus * draft.day_percent) / 100).toFixed(1)} logikai CPU`}</small>}
        </div>
        <div className="cpu-policy-block">
          <label className="toggle-row toggle-row--compact">
            <span><strong><Moon size={15} aria-hidden="true" /> Éjszakai mód</strong><small>Más keret a megadott idősávban (például éjjel teljes gőzzel).</small></span>
            <input type="checkbox" checked={night.enabled} onChange={(event) => update((current) => ({ ...current, night: { ...current.night, enabled: event.target.checked } }))} />
            <span className="toggle" aria-hidden="true" />
          </label>
          <PercentSlider label="Éjszakai CPU-keret" value={night.percent} min={min} max={max} disabled={!night.enabled} onChange={(value) => update((current) => ({ ...current, night: { ...current.night, percent: value } }))} />
          <div className="cpu-policy-times">
            <label className="field"><span>Kezdete</span><input type="time" value={night.start} disabled={!night.enabled} aria-label="Éjszakai mód kezdete" onChange={(event) => update((current) => ({ ...current, night: { ...current.night, start: event.target.value } }))} /></label>
            <label className="field"><span>Vége</span><input type="time" value={night.end} disabled={!night.enabled} aria-label="Éjszakai mód vége" onChange={(event) => update((current) => ({ ...current, night: { ...current.night, end: event.target.value } }))} /></label>
          </div>
        </div>
      </div>
      <div className="cpu-policy-footer">
        <small>
          {applied?.state === "applied"
            ? `A worker ${applied.percent}%-os kerettel fut (${applied.mode === "night" ? "éjszakai" : "nappali"}), beállítva: ${formatDate(applied.applied_at ?? null)}.`
            : `A telepítéskori ${data.install_default_percent}%-os keret van érvényben.`}
        </small>
        <Button icon={<Save size={16} />} loading={save.isPending} disabled={!dirty || (night.enabled && (!night.start || !night.end))} onClick={() => save.mutate(draft)}>Mentés</Button>
      </div>
      {applied === null && data.saved && <Notice tone="info" title="Az alkalmazó még nem futott">A mentett keretet a rendszerszintű segéd (bdencode-cpu-policy) állítja be; a 2.10-es telepítés óta pár másodpercen belül. Addig a telepítéskori keret marad érvényben.</Notice>}
      {(applied?.state === "invalid" || applied?.state === "failed") && <Notice tone="warning" title="A keret beállítása nem sikerült">{applied.message ?? "Ismeretlen hiba"}</Notice>}
      {save.isError && <Notice tone="danger" title="A mentés nem sikerült">{save.error instanceof ApiError ? save.error.detail : save.error.message}</Notice>}
    </Card>
  );
}
