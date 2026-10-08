import { useQuery } from "@tanstack/react-query";
import {
  AudioWaveform,
  Check,
  Clipboard,
  ExternalLink,
  Eye,
  Gauge,
  Images,
  Maximize2,
  ZoomIn,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  Artifact,
  AudioComparisonManifest,
  AudioComparisonTrack,
  VideoComparisonManifest,
  VideoComparisonPair,
  VmafWindow,
} from "../api/types";
import { artifactContentUrl, fetchArtifactJson, fetchArtifactText } from "../api/client";
import { copyText, formatDuration } from "../utils";
import { ImageInspector } from "./ImageInspector";
import { Badge, Button, Card, EmptyState, LoadingPanel, Notice } from "./ui";

type CompareMode = "slider" | "side" | "blink" | "difference";
type MeasuredWindow = VmafWindow & { mean: number };

/** The weakest sampled windows are highlighted; frame pairs this close to one are marked. */
const WEAK_WINDOW_COUNT = 3;
const NEAR_WEAK_WINDOW_SECONDS = 60;

function measuredWindows(manifest: VideoComparisonManifest | undefined): MeasuredWindow[] {
  if (manifest?.vmaf?.status !== "measured") return [];
  return (manifest.vmaf.windows ?? []).filter(
    (window): window is MeasuredWindow => typeof window.mean === "number" && Number.isFinite(window.mean),
  );
}

/** The sampled windows from the weakest up. */
export function windowsByScore(windows: MeasuredWindow[]): MeasuredWindow[] {
  return [...windows].sort((left, right) => left.mean - right.mean || left.start_frame - right.start_frame);
}

function windowTime(window: VmafWindow): string | null {
  if (typeof window.start_seconds !== "number" || typeof window.end_seconds !== "number") return null;
  return `${formatDuration(window.start_seconds)}–${formatDuration(window.end_seconds)}`;
}

/** The weak window a frame pair lies in or near, if any. */
export function nearbyWeakWindow(pair: VideoComparisonPair, weak: MeasuredWindow[]): MeasuredWindow | null {
  const at = Number(pair.reference_pts_seconds);
  if (!Number.isFinite(at)) return null;
  return weak.find((window) => typeof window.start_seconds === "number"
    && typeof window.end_seconds === "number"
    && at >= window.start_seconds - NEAR_WEAK_WINDOW_SECONDS
    && at <= window.end_seconds + NEAR_WEAK_WINDOW_SECONDS) ?? null;
}

export function ComparisonPanel({ artifacts }: { artifacts: Artifact[] }) {
  const videoManifestArtifact = artifacts.find((artifact) => artifact.kind === "VIDEO_COMPARISON" && artifact.mime_type === "application/json");
  const audioManifestArtifact = artifacts.find((artifact) => artifact.kind === "AUDIO_COMPARISON" && artifact.mime_type === "application/json");
  const bbcodeArtifact = artifacts.find((artifact) => artifact.kind === "BBCODE");
  const imagesByName = useMemo(() => new Map(
    artifacts
      .filter((artifact) => artifact.mime_type === "image/png")
      .map((artifact) => [artifact.name, artifact]),
  ), [artifacts]);

  const video = useQuery({
    queryKey: ["artifact-json", videoManifestArtifact?.id],
    queryFn: () => fetchArtifactJson<VideoComparisonManifest>(videoManifestArtifact!.id),
    enabled: Boolean(videoManifestArtifact),
  });
  const audio = useQuery({
    queryKey: ["artifact-json", audioManifestArtifact?.id],
    queryFn: () => fetchArtifactJson<AudioComparisonManifest>(audioManifestArtifact!.id),
    enabled: Boolean(audioManifestArtifact),
  });
  const bbcode = useQuery({
    queryKey: ["artifact-text", bbcodeArtifact?.id],
    queryFn: () => fetchArtifactText(bbcodeArtifact!.id),
    enabled: Boolean(bbcodeArtifact),
  });
  const [copied, setCopied] = useState(false);
  const [inspect, setInspect] = useState<number | null>(null);

  async function copyBbcode() {
    if (!bbcode.data) return;
    await copyText(bbcode.data);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  const scoredWindows = useMemo(() => windowsByScore(measuredWindows(video.data)), [video.data]);
  const weakWindows = scoredWindows.slice(0, WEAK_WINDOW_COUNT);
  const inspectedPair = inspect !== null ? video.data?.pairs[inspect] : undefined;
  const inspectedSource = inspectedPair ? imagesByName.get(inspectedPair.reference_sdr_png || inspectedPair.reference_png) : undefined;
  const inspectedEncode = inspectedPair ? imagesByName.get(inspectedPair.encode_sdr_png || inspectedPair.encode_png) : undefined;
  const inspected = inspectedPair && inspectedSource && inspectedEncode
    ? { pair: inspectedPair, source: inspectedSource, encode: inspectedEncode }
    : null;

  if (!videoManifestArtifact && !audioManifestArtifact) {
    return <EmptyState icon={<Images size={30} />} title="A comparison még nem készült el" description="Az I/P/B framek és az audióspektrumok a QC után jelennek meg ezen a lapon." />;
  }

  return (
    <div className="comparison-panel">
      {bbcodeArtifact && (
        <Card className="bbcode-card">
          <div><span className="eyebrow">Megosztás</span><h3>BBCode csomag</h3><p>Az ellenőrzött képtárhelyre feltöltött source/encode párok fórumba illeszthető kódja.</p></div>
          <Button variant="secondary" icon={copied ? <Check size={17} /> : <Clipboard size={17} />} onClick={() => void copyBbcode()} disabled={!bbcode.data}>{copied ? "Másolva" : "BBCode másolása"}</Button>
        </Card>
      )}

      <section className="comparison-section">
        <div className="section-heading">
          <div><span className="section-heading__icon"><Images size={19} /></span><div><h2>Videó-összehasonlítás</h2><p>Azonos presentation index, külön source/encode PTS, veszteségmentes PNG</p></div></div>
          {video.data && <div className="frame-counts">{["I", "P", "B"].map((type) => <Badge key={type}>{type}: {video.data?.counts[type] ?? 0}</Badge>)}</div>}
        </div>
        {video.data?.metrics?.aggregate && (
          <Card className="video-metrics-card">
            <div className="section-heading">
              <div><span className="section-heading__icon"><Eye size={18} /></span><div><h3>Mintavételezett képmetrikák</h3><p>{video.data.metrics.sample_count ?? video.data.pairs.length} lossless PNG-pár átlaga · nem teljes filmes mérés</p></div></div>
              <div className="frame-counts">
                <Badge tone="info">SSIM: {formatMetric(video.data.metrics.aggregate.ssim_all_mean, 6)}</Badge>
                <Badge tone="info">PSNR: {formatMetric(video.data.metrics.aggregate.psnr_average_db_mean, 2, " dB")}</Badge>
              </div>
            </div>
          </Card>
        )}
        {video.data?.vmaf && <VmafWindowsCard vmaf={video.data.vmaf} windows={scoredWindows} />}
        {video.isLoading ? <LoadingPanel label="Videó comparison betöltése…" /> : video.isError ? <Notice tone="danger">A videó comparison manifestje nem olvasható.</Notice> : (
          <div className="frame-pair-grid">
            {video.data?.pairs.map((pair, index) => (
              <FramePairCard key={`${pair.category}-${pair.presentation_index}-${index}`} pair={pair} images={imagesByName} nearWeak={nearbyWeakWindow(pair, weakWindows)} onInspect={() => setInspect(index)} />
            ))}
          </div>
        )}
      </section>

      <section className="comparison-section">
        <div className="section-heading">
          <div><span className="section-heading__icon"><AudioWaveform size={19} /></span><div><h2>Hang-összehasonlítás</h2><p>Azonos skálájú source/encode spektrum és bitpontos ellenőrzések</p></div></div>
        </div>
        {audio.isLoading ? <LoadingPanel label="Audióelemzés betöltése…" /> : audio.isError ? <Notice tone="danger">Az audió comparison manifestje nem olvasható.</Notice> : audio.data?.tracks.length ? (
          <div className="audio-comparison-list">
            {audio.data.tracks.map((track) => <AudioTrackComparison key={track.stream_id} track={track} images={imagesByName} />)}
          </div>
        ) : <EmptyState title="Nincs megtartott hangsáv" description="Ehhez a munkához nem készült audióspektrum." />}
      </section>

      {inspected && (
        <ImageInspector
          open
          title={`${inspected.pair.category}-frame #${inspected.pair.presentation_index} — pixelnézet`}
          sourceUrl={artifactContentUrl(inspected.source.id)}
          encodeUrl={artifactContentUrl(inspected.encode.id)}
          onClose={() => setInspect(null)}
          onPrevious={inspect !== null && inspect > 0 ? () => setInspect(inspect - 1) : undefined}
          onNext={inspect !== null && inspect < (video.data?.pairs.length ?? 0) - 1 ? () => setInspect(inspect + 1) : undefined}
        />
      )}
    </div>
  );
}

function VmafWindowsCard({ vmaf, windows }: { vmaf: NonNullable<VideoComparisonManifest["vmaf"]>; windows: MeasuredWindow[] }) {
  if (vmaf.status !== "measured") {
    return <Notice tone="info" title="A kész fájl VMAF-mérése nem készült el">A mérés tájékoztató jellegű; az SSIM/PSNR-ellenőrzés és a képpárok ettől függetlenül érvényesek.</Notice>;
  }
  const lowest = windows[0]?.mean ?? vmaf.minimum ?? 0;
  // The bars start a little below the weakest window so differences stay visible.
  const floor = Math.max(0, Math.floor(lowest) - 5);
  return (
    <Card className="video-metrics-card vmaf-card">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><Gauge size={18} /></span>
          <div><h3>VMAF a kész fájlon</h3><p>{vmaf.frames ?? "—"} képkocka {windows.length} mintaszakaszból · {vmaf.model ?? "VMAF"} · tájékoztató mérés</p></div>
        </div>
        <div className="frame-counts">
          <Badge tone="info">Átlag: {formatMetric(vmaf.mean, 2)}</Badge>
          <Badge tone="info">Harmonikus: {formatMetric(vmaf.harmonic_mean, 2)}</Badge>
          <Badge tone="info">1% low: {formatMetric(vmaf.percentile_1, 2)}</Badge>
        </div>
      </div>
      {windows.length > 0 && (
        <ol className="vmaf-windows" aria-label="Mintaszakaszok a leggyengébbtől">
          {windows.map((window, index) => {
            const weak = index < WEAK_WINDOW_COUNT;
            const share = Math.max(0, Math.min(1, (window.mean - floor) / Math.max(1, 100 - floor)));
            return (
              <li key={window.start_frame} className={weak ? "vmaf-window vmaf-window--weak" : "vmaf-window"}>
                <span className="vmaf-window__time">{windowTime(window) ?? `#${window.start_frame}`}</span>
                <span className="vmaf-window__bar" aria-hidden="true"><span style={{ width: `${(share * 100).toFixed(1)}%` }} /></span>
                <strong>{window.mean.toFixed(2)}</strong>
                <small>{typeof window.minimum === "number" ? `min ${window.minimum.toFixed(2)}` : ""}</small>
                {weak ? <Badge tone="warning">gyenge</Badge> : <span />}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

function FramePairCard({ pair, images, nearWeak, onInspect }: { pair: VideoComparisonPair; images: Map<string, Artifact>; nearWeak: MeasuredWindow | null; onInspect: () => void }) {
  const [mode, setMode] = useState<CompareMode>("slider");
  const [position, setPosition] = useState(50);
  const [blinkSource, setBlinkSource] = useState(true);
  const sourceName = pair.reference_sdr_png || pair.reference_png;
  const encodeName = pair.encode_sdr_png || pair.encode_png;
  const source = images.get(sourceName);
  const encode = images.get(encodeName);

  useEffect(() => {
    if (mode !== "blink" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setInterval(() => setBlinkSource((value) => !value), 650);
    return () => window.clearInterval(timer);
  }, [mode]);

  if (!source || !encode) return (
    <Notice tone="warning">A(z) {pair.category}-frame egyik PNG melléklete hiányzik.</Notice>
  );

  const sourceUrl = artifactContentUrl(source.id);
  const encodeUrl = artifactContentUrl(encode.id);
  return (
    <Card className="frame-pair-card">
      <div className="frame-pair-card__header">
        <div>
          <Badge tone={pair.category === "I" ? "success" : pair.category === "P" ? "info" : "warning"}>{pair.category}-frame</Badge>
          <span>#{pair.presentation_index} · Source PTS {String(pair.reference_pts_seconds)} · Encode PTS {String(pair.encoded_pts_seconds)}</span>
          {nearWeak && <Badge tone="warning">{`Gyenge VMAF-szakasz közelében · ${windowTime(nearWeak) ?? nearWeak.mean.toFixed(2)}`}</Badge>}
          {pair.source_pict_type === null ? (
            <Badge tone="neutral">Source képtípus nem értelmezhető · azonos frame</Badge>
          ) : (
            <Badge tone={pair.dual_type_match ? "success" : "danger"}>
              {pair.source_pict_type} ↔ {pair.encoded_pict_type}{pair.dual_type_match ? " · azonos típus" : " · eltérő típus"}
            </Badge>
          )}
        </div>
        <div className="compare-mode" role="group" aria-label="Összehasonlítási mód">
          {(["slider", "side", "blink", "difference"] as CompareMode[]).map((value) => (
            <button type="button" key={value} className={mode === value ? "active" : ""} aria-pressed={mode === value} onClick={() => setMode(value)} title={value === "slider" ? "Húzható elválasztó" : value === "side" ? "Egymás mellett" : value === "blink" ? "A/B villogtatás" : "Különbségkiemelés"}>
              {value === "slider" ? "Csúszka" : value === "side" ? "A/B" : value === "blink" ? "Villog" : "Diff"}
            </button>
          ))}
        </div>
      </div>
      <div className={`image-compare image-compare--${mode}`}>
        {mode === "side" ? (
          <><figure><img src={sourceUrl} alt={`${pair.category}-frame forrás`} loading="lazy" /><figcaption>Source</figcaption></figure><figure><img src={encodeUrl} alt={`${pair.category}-frame encode`} loading="lazy" /><figcaption>Encode</figcaption></figure></>
        ) : mode === "blink" ? (
          <figure><img src={blinkSource ? sourceUrl : encodeUrl} alt={`${pair.category}-frame ${blinkSource ? "forrás" : "encode"}`} /><figcaption>{blinkSource ? "Source" : "Encode"}</figcaption></figure>
        ) : mode === "difference" ? (
          <figure className="difference-view"><img src={sourceUrl} alt="Forrás" /><img src={encodeUrl} alt="Különbségkiemelés" /><figcaption>CSS difference nézet</figcaption></figure>
        ) : (
          <div className="slider-compare">
            <img src={encodeUrl} alt={`${pair.category}-frame encode`} loading="lazy" />
            <img className="slider-compare__source-image" src={sourceUrl} alt={`${pair.category}-frame forrás`} loading="lazy" style={{ clipPath: `inset(0 ${100 - position}% 0 0)` }} />
            <span className="slider-compare__line" style={{ left: `${position}%` }} aria-hidden="true"><Eye size={17} /></span>
            <input type="range" min="0" max="100" value={position} onChange={(event) => setPosition(Number(event.target.value))} aria-label="Source és encode elválasztása" />
            <span className="slider-label slider-label--left">Source</span><span className="slider-label slider-label--right">Encode</span>
          </div>
        )}
      </div>
      <div className="frame-pair-card__footer">
        <button type="button" className="link-button" onClick={onInspect}><ZoomIn size={15} aria-hidden="true" /> Nagyítás és pixelnézet</button>
        <a href={sourceUrl} target="_blank" rel="noreferrer"><Maximize2 size={15} aria-hidden="true" /> Source PNG</a>
        <a href={encodeUrl} target="_blank" rel="noreferrer"><Maximize2 size={15} aria-hidden="true" /> Encode PNG</a>
      </div>
    </Card>
  );
}

function formatMetric(value: number | null | undefined, digits: number, suffix = ""): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(digits)}${suffix}`
    : "—";
}

const AUDIO_COMPARISON_LABELS: Record<AudioComparisonTrack["action"], string> = {
  copy: "Veszteségmentes másolás",
  flac: "FLAC konverzió",
  ac3: "AC-3 konverzió",
  eac3: "E-AC-3 konverzió",
  dts: "DTS core kimenet",
  omit: "Kihagyott sáv",
};

function AudioTrackComparison({ track, images }: { track: AudioComparisonTrack; images: Map<string, Artifact> }) {
  const source = images.get(track.source_spectrum);
  const encode = images.get(track.encode_spectrum);
  const pcmRequired = track.decoded_pcm_sha256_required ?? (track.action === "copy" || track.action === "flac");
  const timingMatch = track.timing_within_tolerance ?? track.delay_within_one_sample;
  return (
    <Card className="audio-track-card">
      <div className="audio-track-card__header">
        <div><span className="audio-track-card__icon"><AudioWaveform size={20} /></span><div><h3>{track.stream_id}</h3><p>{AUDIO_COMPARISON_LABELS[track.action]}</p></div></div>
        <div className="audio-checks">
          {pcmRequired
            ? <Badge tone={track.decoded_pcm_sha256_match ? "success" : "danger"}>{track.decoded_pcm_sha256_match ? "PCM egyezik" : "PCM eltérés"}</Badge>
            : <Badge tone="info">Veszteséges cél · PCM hash nem elvárt</Badge>}
          <Badge tone={timingMatch ? "success" : "danger"}>{timingMatch ? "Időzítés rendben" : "Időzítési eltérés"}</Badge>
        </div>
      </div>
      {source && encode ? (
        <div className="spectrum-pair">
          <figure><a href={artifactContentUrl(source.id)} target="_blank" rel="noreferrer"><img src={artifactContentUrl(source.id)} alt={`${track.stream_id} source spektrum`} loading="lazy" /></a><figcaption>Source <ExternalLink size={13} /></figcaption></figure>
          <figure><a href={artifactContentUrl(encode.id)} target="_blank" rel="noreferrer"><img src={artifactContentUrl(encode.id)} alt={`${track.stream_id} encode spektrum`} loading="lazy" /></a><figcaption>Encode <ExternalLink size={13} /></figcaption></figure>
        </div>
      ) : <Notice tone="warning">A spektrumképek még nem érhetők el mellékletként.</Notice>}
      <details className="metric-details"><summary>Mérési részletek</summary><pre>{JSON.stringify({ effective_target: track.effective_target, verification: track.verification, comparison: track.comparison }, null, 2)}</pre></details>
    </Card>
  );
}
