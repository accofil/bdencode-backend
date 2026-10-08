import { useQuery } from "@tanstack/react-query";
import { Award, Gauge, Sparkles, Waves } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AutoCrfConfig, DynamicHdrMode, VideoProperties } from "../api/types";
import { Badge, Card, Notice } from "./ui";

export const DEFAULT_AUTO_CRF: AutoCrfConfig = { enabled: true, target_vmaf: 95 };
const DEFAULT_TARGET_SIZE_GB = 20;
// Size projection from 24 spread windows was within about +-12 % on a real UHD title.
const SIZE_MODE_SAMPLES = 24;

const HDR_OPTIONS: Array<{ value: DynamicHdrMode; label: string; help: string }> = [
  { value: "discard", label: "Eldobás (alapértelmezett)", help: "Csak a statikus HDR10 marad meg; a dinamikus réteg nem." },
  { value: "auto", label: "Automatikus", help: "Ami a forrásban van és biztonságosan megtartható (előbb HDR10+, aztán Dolby Vision); különben eldobás." },
  { value: "hdr10plus", label: "HDR10+ megtartása", help: "Képkockánkénti HDR10+ metaadat; hdr10plus_tool és x265-támogatás kell." },
  { value: "dolby_vision", label: "Dolby Vision (8.1) megtartása — kísérleti", help: "A Dolby Vision RPU profil 8.1-ként marad meg; dovi_tool kell, és a kész MKV-nak igazolnia kell a konfigurációs rekordot." },
];

/**
 * Number input that keeps the raw text while typing ("93." must stay "93.") and
 * only reports finite values, so a controlled decimal field stays editable.
 */
function NumberField({
  label,
  value,
  min,
  max,
  step,
  onValue,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onValue: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => {
    setText((current) => (Number.parseFloat(current) === value ? current : String(value)));
  }, [value]);
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          const parsed = Number.parseFloat(event.target.value);
          if (Number.isFinite(parsed)) onValue(parsed);
        }}
        aria-label={label}
      />
    </label>
  );
}

/**
 * Optional quality features of the 2.2 release: noise/grain presets, the
 * automatic VMAF-based CRF search and dynamic HDR retention.  Everything here is
 * off by default and is validated again by the backend.
 */
export function QualityOptions({
  encoder,
  contentType,
  sourceVideo,
  temporalFilter,
  autoCrf,
  onAutoCrf,
  dynamicHdr,
  onDynamicHdr,
  onApplyNoiseProfile,
}: {
  encoder: "x264" | "x265";
  contentType: string;
  sourceVideo: Pick<VideoProperties, "hdr10" | "hdr10_plus" | "dolby_vision" | "dolby_vision_profile" | "hdr10_base_layer"> | undefined;
  temporalFilter: string;
  autoCrf: AutoCrfConfig | null;
  onAutoCrf: (value: AutoCrfConfig | null) => void;
  dynamicHdr: DynamicHdrMode;
  onDynamicHdr: (mode: DynamicHdrMode) => void;
  onApplyNoiseProfile: (settings: Record<string, unknown>) => void;
}) {
  const [noiseId, setNoiseId] = useState("");
  const [aitherId, setAitherId] = useState("");
  const aither = useQuery({
    queryKey: ["aither-presets", encoder, contentType],
    queryFn: () => api.aitherPresets(encoder, contentType),
    retry: false,
  });
  const selectedAither = aither.data?.presets.find((preset) => preset.id === aitherId);
  const noise = useQuery({
    queryKey: ["noise-profiles", encoder, contentType],
    queryFn: () => api.noiseProfiles(encoder, contentType),
    retry: false,
  });
  const selectedNoise = noise.data?.profiles.find((profile) => profile.id === noiseId);
  const hdrCapable = encoder === "x265" && Boolean(sourceVideo?.hdr10);
  const hasPlus = Boolean(sourceVideo?.hdr10_plus);
  const hasDolby = Boolean(sourceVideo?.dolby_vision);

  return (
    <Card className="settings-card quality-options">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Sparkles size={19} /></span>
          <div><h3>Minőségi opciók</h3><p>Opcionális, alapból kikapcsolt képességek · a backend újra ellenőrzi őket</p></div>
        </div>
      </div>

      <div className="quality-option">
        <div className="quality-option__title"><Award size={17} aria-hidden="true" /><strong>Aither-preset</strong></div>
        <label className="field">
          <span>Preset</span>
          <select
            value={aitherId}
            onChange={(event) => {
              const id = event.target.value;
              setAitherId(id);
              const preset = aither.data?.presets.find((item) => item.id === id);
              if (preset) onApplyNoiseProfile(preset.settings);
            }}
            disabled={!aither.data}
            aria-label="Aither-preset"
          >
            <option value="">— nincs kiválasztva (jelenlegi értékek) —</option>
            {aither.data?.presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
          </select>
        </label>
        {selectedAither && <p className="field-help">{selectedAither.description} <strong>{selectedAither.crf_hint}</strong></p>}
        {aither.isError && <Notice tone="warning">Az Aither-presetek nem tölthetők be.</Notice>}
        <p className="field-help">Az Aither-kódolók gyakorlatát követő kiinduló beállítások; minden mező utána is szerkeszthető. Részletek a Súgó oldalon.</p>
      </div>

      <div className="quality-option">
        <div className="quality-option__title"><Waves size={17} aria-hidden="true" /><strong>Zaj- és szemcseprofil</strong></div>
        <label className="field">
          <span>Profil</span>
          <select
            value={noiseId}
            onChange={(event) => {
              const id = event.target.value;
              setNoiseId(id);
              const profile = noise.data?.profiles.find((item) => item.id === id);
              if (profile) onApplyNoiseProfile(profile.settings);
            }}
            disabled={!noise.data}
            aria-label="Zaj- és szemcseprofil"
          >
            <option value="">— nincs kiválasztva (jelenlegi értékek) —</option>
            {noise.data?.profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
          </select>
        </label>
        {selectedNoise && <p className="field-help">{selectedNoise.description}</p>}
        {noise.isError && <Notice tone="warning">A zajprofilok nem tölthetők be.</Notice>}
        <p className="field-help">
          A zajcsökkentés a kódolóban történik (nem előszűrő), ezért a minőségi kapuk továbbra is a kodek hűségét mérik. Erős zajszűrésnél a QC jelezheti a részletvesztést.
        </p>
      </div>

      <div className="quality-option">
        <div className="quality-option__title"><Gauge size={17} aria-hidden="true" /><strong>Automatikus CRF (VMAF- vagy méretcél)</strong></div>
        <label className="check-row">
          <input
            type="checkbox"
            checked={Boolean(autoCrf?.enabled)}
            onChange={(event) => onAutoCrf(event.target.checked ? (autoCrf ?? DEFAULT_AUTO_CRF) : null)}
          />
          <span>A worker rövid mintakódolásokból választ CRF-et a célhoz</span>
        </label>
        {autoCrf?.enabled && (
          <label className="field">
            <span>Cél</span>
            <select
              value={autoCrf.target_size_gb != null ? "size" : "vmaf"}
              onChange={(event) =>
                onAutoCrf(
                  event.target.value === "size"
                    ? { ...autoCrf, target_size_gb: autoCrf.target_size_gb ?? DEFAULT_TARGET_SIZE_GB, samples: autoCrf.samples ?? SIZE_MODE_SAMPLES }
                    : { ...autoCrf, target_size_gb: null }
                )
              }
              aria-label="Automatikus CRF célja"
            >
              <option value="vmaf">Minőségcél (VMAF)</option>
              <option value="size">Méretcél (videó, GB)</option>
            </select>
          </label>
        )}
        {autoCrf?.enabled && (
          <div className="quality-option__grid">
            {autoCrf.target_size_gb != null ? (
              <NumberField
                label="Cél videóméret (GB)"
                value={autoCrf.target_size_gb}
                min={0.5}
                max={500}
                step={0.5}
                onValue={(value) => onAutoCrf({ ...autoCrf, target_size_gb: value })}
              />
            ) : (
              <NumberField
                label="Cél VMAF"
                value={autoCrf.target_vmaf}
                min={80}
                max={99.5}
                step={0.5}
                onValue={(value) => onAutoCrf({ ...autoCrf, target_vmaf: value })}
              />
            )}
            <NumberField
              label="Legkisebb CRF"
              value={autoCrf.min_crf ?? 12}
              min={1}
              max={50}
              step={0.5}
              onValue={(value) => onAutoCrf({ ...autoCrf, min_crf: value })}
            />
            <NumberField
              label="Legnagyobb CRF"
              value={autoCrf.max_crf ?? 26}
              min={2}
              max={51}
              step={0.5}
              onValue={(value) => onAutoCrf({ ...autoCrf, max_crf: value })}
            />
          </div>
        )}
        {autoCrf?.enabled && autoCrf.target_size_gb == null && (
          <Notice tone="info">
            A fent megadott CRF csak a keresés kiindulópontja. A keresés az előkészítésnél fut, 4–6 mintakódolással; ha a cél a tartományban nem érhető el, a munka felülvizsgálatot kér.
          </Notice>
        )}
        {autoCrf?.enabled && autoCrf.target_size_gb != null && (
          <Notice tone="info">
            A worker a film egészén szétszórt mintákat kódolja pontosan ezekkel a beállításokkal, a méretüket a teljes filmre vetíti, és azt a legkisebb CRF-et (legjobb minőséget) választja, amelyik még belefér a célba. A fenti CRF a kiindulópont. UHD-n mintakódolásonként kb. 15 perc (24 × 3 másodperc), általában 3–4 kell. A becslés a hang és a felirat méretét nem tartalmazza.
          </Notice>
        )}
      </div>

      {hdrCapable && (
        <div className="quality-option">
          <div className="quality-option__title"><Sparkles size={17} aria-hidden="true" /><strong>Dinamikus HDR</strong></div>
          <p className="field-help">
            A forrás:
            {" "}
            {hasPlus ? <Badge tone="info">HDR10+</Badge> : null}
            {hasDolby ? <Badge tone="info">Dolby Vision{sourceVideo?.dolby_vision_profile ? ` P${sourceVideo.dolby_vision_profile}` : ""}</Badge> : null}
            {!hasPlus && !hasDolby ? <Badge>csak statikus HDR10</Badge> : null}
          </p>
          <label className="field">
            <span>Megtartás</span>
            <select value={dynamicHdr} onChange={(event) => onDynamicHdr(event.target.value as DynamicHdrMode)} aria-label="Dinamikus HDR">
              {HDR_OPTIONS.map((option) => (
                <option
                  key={option.value}
                  value={option.value}
                  disabled={(option.value === "hdr10plus" && !hasPlus) || (option.value === "dolby_vision" && !hasDolby)}
                >
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <p className="field-help">{HDR_OPTIONS.find((option) => option.value === dynamicHdr)?.help}</p>
          {dynamicHdr !== "discard" && temporalFilter !== "progressive" && (
            <Notice tone="warning">A dinamikus HDR forráskockánkénti; IVTC/deinterlace mellett nem vihető át. Válts progresszív időbeli szűrésre.</Notice>
          )}
          {dynamicHdr === "dolby_vision" && (
            <Notice tone="warning">Kísérleti: ha a kész MKV-ban hiányzik a Dolby Vision konfigurációs rekord, a QC megállítja a munkát.</Notice>
          )}
        </div>
      )}
    </Card>
  );
}
