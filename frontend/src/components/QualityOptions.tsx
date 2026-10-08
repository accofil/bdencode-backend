import { useQuery } from "@tanstack/react-query";
import { Award, Gauge, Sparkles, Waves } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { t } from "../i18n";
import type { AutoCrfConfig, DynamicHdrMode, VideoProperties } from "../api/types";
import { Badge, Card, Notice } from "./ui";

export const DEFAULT_AUTO_CRF: AutoCrfConfig = { enabled: true, target_vmaf: 95 };
const DEFAULT_TARGET_SIZE_GB = 20;
// Size projection from 24 spread windows was within about +-12 % on a real UHD title.
const SIZE_MODE_SAMPLES = 24;

function hdrOptions(): Array<{ value: DynamicHdrMode; label: string; help: string }> {
  return [
    {
      value: "discard",
      label: t("Eldobás (alapértelmezett)", "Discard (default)"),
      help: t("Csak a statikus HDR10 marad meg; a dinamikus réteg nem.", "Only the static HDR10 is kept; the dynamic layer is not."),
    },
    {
      value: "auto",
      label: t("Automatikus", "Automatic"),
      help: t(
        "Ami a forrásban van és biztonságosan megtartható (előbb HDR10+, aztán Dolby Vision); különben eldobás.",
        "Whatever the source has and can be kept safely (HDR10+ first, then Dolby Vision); otherwise discard.",
      ),
    },
    {
      value: "hdr10plus",
      label: t("HDR10+ megtartása", "Keep HDR10+"),
      help: t(
        "Képkockánkénti HDR10+ metaadat; hdr10plus_tool és x265-támogatás kell.",
        "Per-frame HDR10+ metadata; needs hdr10plus_tool and x265 support.",
      ),
    },
    {
      value: "dolby_vision",
      label: t("Dolby Vision (8.1) megtartása — kísérleti", "Keep Dolby Vision (8.1) — experimental"),
      help: t(
        "A Dolby Vision RPU profil 8.1-ként marad meg; dovi_tool kell, és a kész MKV-nak igazolnia kell a konfigurációs rekordot.",
        "The Dolby Vision RPU is kept as profile 8.1; needs dovi_tool, and the finished MKV must prove the configuration record.",
      ),
    },
  ];
}

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
  const hdrOptionList = hdrOptions();

  return (
    <Card className="settings-card quality-options">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Sparkles size={19} /></span>
          <div><h3>{t("Minőségi opciók", "Quality options")}</h3><p>{t("Opcionális, alapból kikapcsolt képességek · a backend újra ellenőrzi őket", "Optional features, off by default · the backend checks them again")}</p></div>
        </div>
      </div>

      <div className="quality-option">
        <div className="quality-option__title"><Award size={17} aria-hidden="true" /><strong>{t("Aither-preset", "Aither preset")}</strong></div>
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
            aria-label={t("Aither-preset", "Aither preset")}
          >
            <option value="">{t("— nincs kiválasztva (jelenlegi értékek) —", "— none selected (current values) —")}</option>
            {aither.data?.presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
          </select>
        </label>
        {selectedAither && <p className="field-help">{selectedAither.description} <strong>{selectedAither.crf_hint}</strong></p>}
        {aither.isError && <Notice tone="warning">{t("Az Aither-presetek nem tölthetők be.", "The Aither presets cannot be loaded.")}</Notice>}
        <p className="field-help">{t("Az Aither-kódolók gyakorlatát követő kiinduló beállítások; minden mező utána is szerkeszthető. Részletek a Súgó oldalon.", "Starting settings that follow the practice of Aither encoders; every field stays editable afterwards. Details on the Help page.")}</p>
      </div>

      <div className="quality-option">
        <div className="quality-option__title"><Waves size={17} aria-hidden="true" /><strong>{t("Zaj- és szemcseprofil", "Noise and grain profile")}</strong></div>
        <label className="field">
          <span>{t("Profil", "Profile")}</span>
          <select
            value={noiseId}
            onChange={(event) => {
              const id = event.target.value;
              setNoiseId(id);
              const profile = noise.data?.profiles.find((item) => item.id === id);
              if (profile) onApplyNoiseProfile(profile.settings);
            }}
            disabled={!noise.data}
            aria-label={t("Zaj- és szemcseprofil", "Noise and grain profile")}
          >
            <option value="">{t("— nincs kiválasztva (jelenlegi értékek) —", "— none selected (current values) —")}</option>
            {noise.data?.profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}
          </select>
        </label>
        {selectedNoise && <p className="field-help">{selectedNoise.description}</p>}
        {noise.isError && <Notice tone="warning">{t("A zajprofilok nem tölthetők be.", "The noise profiles cannot be loaded.")}</Notice>}
        <p className="field-help">
          {t(
            "A zajcsökkentés a kódolóban történik (nem előszűrő), ezért a minőségi kapuk továbbra is a kodek hűségét mérik. Erős zajszűrésnél a QC jelezheti a részletvesztést.",
            "Noise reduction happens inside the encoder (not as a pre-filter), so the quality gates still measure codec fidelity. With strong noise reduction, QC may flag lost detail.",
          )}
        </p>
      </div>

      <div className="quality-option">
        <div className="quality-option__title"><Gauge size={17} aria-hidden="true" /><strong>{t("Automatikus CRF (VMAF- vagy méretcél)", "Automatic CRF (VMAF or size target)")}</strong></div>
        <label className="check-row">
          <input
            type="checkbox"
            checked={Boolean(autoCrf?.enabled)}
            onChange={(event) => onAutoCrf(event.target.checked ? (autoCrf ?? DEFAULT_AUTO_CRF) : null)}
          />
          <span>{t("A worker rövid mintakódolásokból választ CRF-et a célhoz", "The worker picks a CRF for the target from short sample encodes")}</span>
        </label>
        {autoCrf?.enabled && (
          <label className="field">
            <span>{t("Cél", "Target")}</span>
            <select
              value={autoCrf.target_size_gb != null ? "size" : "vmaf"}
              onChange={(event) =>
                onAutoCrf(
                  event.target.value === "size"
                    ? { ...autoCrf, target_size_gb: autoCrf.target_size_gb ?? DEFAULT_TARGET_SIZE_GB, samples: autoCrf.samples ?? SIZE_MODE_SAMPLES }
                    : { ...autoCrf, target_size_gb: null }
                )
              }
              aria-label={t("Automatikus CRF célja", "Automatic CRF target")}
            >
              <option value="vmaf">{t("Minőségcél (VMAF)", "Quality target (VMAF)")}</option>
              <option value="size">{t("Méretcél (videó, GB)", "Size target (video, GB)")}</option>
            </select>
          </label>
        )}
        {autoCrf?.enabled && (
          <div className="quality-option__grid">
            {autoCrf.target_size_gb != null ? (
              <NumberField
                label={t("Cél videóméret (GB)", "Target video size (GB)")}
                value={autoCrf.target_size_gb}
                min={0.5}
                max={500}
                step={0.5}
                onValue={(value) => onAutoCrf({ ...autoCrf, target_size_gb: value })}
              />
            ) : (
              <NumberField
                label={t("Cél VMAF", "Target VMAF")}
                value={autoCrf.target_vmaf}
                min={80}
                max={99.5}
                step={0.5}
                onValue={(value) => onAutoCrf({ ...autoCrf, target_vmaf: value })}
              />
            )}
            <NumberField
              label={t("Legkisebb CRF", "Lowest CRF")}
              value={autoCrf.min_crf ?? 12}
              min={1}
              max={50}
              step={0.5}
              onValue={(value) => onAutoCrf({ ...autoCrf, min_crf: value })}
            />
            <NumberField
              label={t("Legnagyobb CRF", "Highest CRF")}
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
            {t(
              "A fent megadott CRF csak a keresés kiindulópontja. A keresés az előkészítésnél fut, 4–6 mintakódolással; ha a cél a tartományban nem érhető el, a munka felülvizsgálatot kér.",
              "The CRF set above is only where the search starts. The search runs during preparation, with 4–6 sample encodes; if the target cannot be reached within the range, the job asks for review.",
            )}
          </Notice>
        )}
        {autoCrf?.enabled && autoCrf.target_size_gb != null && (
          <Notice tone="info">
            {t(
              "A worker a film egészén szétszórt mintákat kódolja pontosan ezekkel a beállításokkal, a méretüket a teljes filmre vetíti, és azt a legkisebb CRF-et (legjobb minőséget) választja, amelyik még belefér a célba. A fenti CRF a kiindulópont. UHD-n mintakódolásonként kb. 15 perc (24 × 3 másodperc), általában 3–4 kell. A becslés a hang és a felirat méretét nem tartalmazza.",
              "The worker encodes samples spread across the whole film with exactly these settings, projects their size to the full film and picks the lowest CRF (best quality) that still fits the target. The CRF above is the starting point. On UHD each sample encode takes about 15 minutes (24 × 3 seconds); usually 3–4 are needed. The estimate does not include audio and subtitle size.",
            )}
          </Notice>
        )}
      </div>

      {hdrCapable && (
        <div className="quality-option">
          <div className="quality-option__title"><Sparkles size={17} aria-hidden="true" /><strong>{t("Dinamikus HDR", "Dynamic HDR")}</strong></div>
          <p className="field-help">
            {t("A forrás:", "Source:")}
            {" "}
            {hasPlus ? <Badge tone="info">HDR10+</Badge> : null}
            {hasDolby ? <Badge tone="info">Dolby Vision{sourceVideo?.dolby_vision_profile ? ` P${sourceVideo.dolby_vision_profile}` : ""}</Badge> : null}
            {!hasPlus && !hasDolby ? <Badge>{t("csak statikus HDR10", "static HDR10 only")}</Badge> : null}
          </p>
          <label className="field">
            <span>{t("Megtartás", "Keep")}</span>
            <select value={dynamicHdr} onChange={(event) => onDynamicHdr(event.target.value as DynamicHdrMode)} aria-label={t("Dinamikus HDR", "Dynamic HDR")}>
              {hdrOptionList.map((option) => (
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
          <p className="field-help">{hdrOptionList.find((option) => option.value === dynamicHdr)?.help}</p>
          {dynamicHdr !== "discard" && temporalFilter !== "progressive" && (
            <Notice tone="warning">{t("A dinamikus HDR forráskockánkénti; IVTC/deinterlace mellett nem vihető át. Válts progresszív időbeli szűrésre.", "Dynamic HDR is per source frame; it cannot be carried over with IVTC/deinterlacing. Switch to progressive temporal filtering.")}</Notice>
          )}
          {dynamicHdr === "dolby_vision" && (
            <Notice tone="warning">{t("Kísérleti: ha a kész MKV-ban hiányzik a Dolby Vision konfigurációs rekord, a QC megállítja a munkát.", "Experimental: if the finished MKV lacks the Dolby Vision configuration record, QC stops the job.")}</Notice>
          )}
        </div>
      )}
    </Card>
  );
}
