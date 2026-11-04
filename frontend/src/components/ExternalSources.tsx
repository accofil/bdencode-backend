import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clapperboard, FileAudio, FolderOpen, Play, Search, Trash2, X } from "lucide-react";
import { useState } from "react";
import { api, ApiError, previewUrl } from "../api/client";
import type {
  ExternalMapSegment,
  ExternalProbe,
  ExternalReviewItem,
  ExternalSourceSelection,
  ExternalTrackSelection,
  Job,
} from "../api/types";
import { t } from "../i18n";
import { formatDuration } from "../utils";
import { Badge, Button, Card, Notice } from "./ui";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.detail : error instanceof Error ? error.message : String(error);
}

const LANGUAGE_CHOICES: [string, string][] = [
  ["hun", "magyar / Hungarian"],
  ["eng", "angol / English"],
  ["deu", "német / German"],
  ["ita", "olasz / Italian"],
  ["fra", "francia / French"],
  ["spa", "spanyol / Spanish"],
];

function languageOf(value: string | null | undefined): string {
  const code = (value ?? "").toLowerCase();
  const known: Record<string, string> = { hu: "hun", en: "eng", de: "deu", ger: "deu", it: "ita", fr: "fra", fre: "fra", es: "spa" };
  return known[code] ?? (code || "hun");
}

/** External tracks of a job: chosen in the wizard, fitted before anything is encoded. */
export function ExternalSourcesCard({
  value,
  onChange,
  available,
}: {
  value: ExternalSourceSelection[];
  onChange: (next: ExternalSourceSelection[]) => void;
  available: boolean;
}) {
  const [path, setPath] = useState("");
  const [browsing, setBrowsing] = useState<string | null>(null);
  const [subtitlePath, setSubtitlePath] = useState("");
  const [subtitleLanguage, setSubtitleLanguage] = useState("hun");
  const probe = useMutation({ mutationFn: (location: string) => api.probeExternalSource(location) });
  const folders = useQuery({
    queryKey: ["external-browse", browsing],
    queryFn: () => api.sources(browsing || undefined),
    enabled: browsing !== null,
  });
  const info: ExternalProbe | undefined = probe.data;
  const current = value.find((item) => item.path === info?.path);

  function update(next: ExternalSourceSelection | null, id: string) {
    const others = value.filter((item) => item.id !== id);
    onChange(next && (next.tracks.length || next.subtitles.length) ? [...others, next] : others);
  }

  function source(): ExternalSourceSelection {
    return current ?? { id: `e${value.length + 1}`, path: info?.path ?? path, tracks: [], subtitles: [] };
  }

  function toggleTrack(stream: string, language: string | null) {
    const entry = source();
    const chosen = entry.tracks.find((item) => item.stream === stream);
    const tracks: ExternalTrackSelection[] = chosen
      ? entry.tracks.filter((item) => item.stream !== stream)
      : [...entry.tracks, { stream, language: languageOf(language), position: 0, default: false, pitch: "restore" }];
    update({ ...entry, tracks, approved_map_sha256: null }, entry.id);
  }

  function changeTrack(stream: string, change: Partial<ExternalTrackSelection>) {
    const entry = source();
    update({
      ...entry,
      approved_map_sha256: null,
      tracks: entry.tracks.map((item) => (item.stream === stream ? { ...item, ...change } : item)),
    }, entry.id);
  }

  function addSubtitle() {
    const location = subtitlePath.trim();
    if (!location) return;
    const entry = source();
    update({
      ...entry,
      approved_map_sha256: null,
      subtitles: [...entry.subtitles, { path: location, language: subtitleLanguage, default: false, forced: false }],
    }, entry.id);
    setSubtitlePath("");
  }

  return (
    <Card className="external-card">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><FileAudio size={18} /></span>
          <div>
            <h3>{t("Hang vagy felirat más forrásból", "Audio or subtitles from another source")}</h3>
            <p>{t("Például PAL DVD magyar szinkronja. A program a két kép összehasonlításából illeszti a sávot, akár eltérő sebesség és eltérő vágás esetén is. Kódolás előtt meghallgathatod és jóvá kell hagynod.", "For example a PAL DVD's dub. The track is fitted by comparing the two pictures, even with another speed and another cut. You can listen to it and must approve it before the encode.")}</p>
          </div>
        </div>
      </div>
      {!available && <Notice tone="warning">{t("Ezen a szerveren hiányzik az ehhez szükséges eszköz (lásd a Rendszer oldalt).", "A tool this needs is missing on this server (see the System page).")}</Notice>}
      <label className="field">
        {t("A forrás helye: videófájl, DVD-mappa vagy DVD-képfájlt tartalmazó mappa", "Where the source is: a video file, a DVD folder or a folder with a DVD image")}
        <input value={path} disabled={!available} onChange={(event) => setPath(event.target.value)} spellCheck={false} />
      </label>
      <div className="release-actions">
        <Button variant="secondary" icon={<Search size={15} />} loading={probe.isPending} disabled={!available || !path.trim()} onClick={() => probe.mutate(path.trim())}>{t("Beolvasás", "Read")}</Button>
        <Button variant="ghost" icon={<FolderOpen size={15} />} disabled={!available} onClick={() => setBrowsing(browsing === null ? "" : null)}>{t("Tallózás", "Browse")}</Button>
      </div>
      {browsing !== null && folders.data && (
        <div className="external-browser">
          <div className="external-browser__roots">
            {folders.data.roots.map((root) => <Button key={root} variant="ghost" onClick={() => setBrowsing(root)}>{root}</Button>)}
          </div>
          <ul>
            {folders.data.entries.map((entry) => (
              <li key={entry.path}>
                <button type="button" onClick={() => setBrowsing(entry.path)}>{entry.name}</button>
                <Button variant="ghost" onClick={() => { setPath(entry.path); setBrowsing(null); probe.mutate(entry.path); }}>{t("Ezt választom", "Choose")}</Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {probe.isError && <Notice tone="danger">{errorText(probe.error)}</Notice>}
      {info && (
        <div className="external-tracks">
          <p className="muted">{info.fps} fps · {formatDuration(info.duration_seconds)} · {info.width}×{info.height}</p>
          {info.tracks.length === 0 && <p className="muted">{t("Nincs benne hangsáv.", "It holds no audio track.")}</p>}
          {info.tracks.map((track) => {
            const chosen = current?.tracks.find((item) => item.stream === track.stream);
            return (
              <div key={track.stream} className="external-track">
                <label className="check-row">
                  <input type="checkbox" checked={Boolean(chosen)} onChange={() => toggleTrack(track.stream, track.language)} />
                  <span>{track.codec.toUpperCase()} {track.channels} {t("csatorna", "channels")}{track.language ? ` · ${track.language}` : ""}{track.title ? ` · ${track.title}` : ""}</span>
                </label>
                {chosen && (
                  <div className="release-form-grid">
                    <label className="field">{t("Nyelv", "Language")}
                      <select value={chosen.language} onChange={(event) => changeTrack(track.stream, { language: event.target.value })}>
                        {LANGUAGE_CHOICES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
                      </select>
                    </label>
                    <label className="field">{t("Hely a hangsávok között (0 = első)", "Place among the audio tracks (0 = first)")}
                      <input type="number" min={0} max={16} value={chosen.position} onChange={(event) => changeTrack(track.stream, { position: Math.max(0, Number(event.target.value) || 0) })} />
                    </label>
                    <label className="check-row">
                      <input type="checkbox" checked={Boolean(chosen.default)} onChange={(event) => changeTrack(track.stream, { default: event.target.checked })} />
                      <span>{t("Alapértelmezett hangsáv", "Default audio track")}</span>
                    </label>
                  </div>
                )}
              </div>
            );
          })}
          <div className="release-form-grid">
            <label className="field">{t("SRT-felirat ehhez a forráshoz (teljes útvonal)", "SRT subtitle for this source (full path)")}
              <input value={subtitlePath} spellCheck={false} onChange={(event) => setSubtitlePath(event.target.value)} />
            </label>
            <label className="field">{t("Nyelv", "Language")}
              <select value={subtitleLanguage} onChange={(event) => setSubtitleLanguage(event.target.value)}>
                {LANGUAGE_CHOICES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}
              </select>
            </label>
          </div>
          <Button variant="ghost" disabled={!subtitlePath.trim()} onClick={addSubtitle}>{t("Felirat hozzáadása", "Add the subtitle")}</Button>
        </div>
      )}
      {value.length > 0 && (
        <ul className="external-chosen">
          {value.map((item) => (
            <li key={item.id}>
              <span>{item.path} · {t(`${item.tracks.length} hangsáv, ${item.subtitles.length} felirat`, `${item.tracks.length} audio, ${item.subtitles.length} subtitles`)}</span>
              <button type="button" className="icon-button" aria-label={t("Forrás eltávolítása", "Remove the source")} onClick={() => update(null, item.id)}><X size={15} /></button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function clock(seconds: number): string {
  const whole = Math.floor(seconds);
  return `${formatDuration(whole)}.${Math.floor((seconds - whole) * 10)}`;
}

interface ListeningPoint {
  seconds: number;
  label: string;
  kind: "splice" | "gap" | "sample";
}

/** Where to listen: every change in the fit, and a few plain places. */
export function listeningPoints(segments: ExternalMapSegment[], fps: number, frames: number): ListeningPoint[] {
  const points: ListeningPoint[] = [];
  segments.slice(1).forEach((segment, index) => {
    const previous = segments[index];
    const jump = segment.offset - previous.offset;
    const missing = segment.target_start - previous.target_end;
    if (missing > 0) {
      const length = missing / fps < 1 ? `${Math.round((missing / fps) * 1000)} ms` : t(`${(missing / fps).toFixed(1)} mp`, `${(missing / fps).toFixed(1)} s`);
      points.push({ seconds: previous.target_end / fps, kind: "gap", label: t(`Hiányzó rész: ${length} csend`, `Missing part: ${length} of silence`) });
    } else {
      points.push({ seconds: segment.target_start / fps, kind: "splice", label: t(`Illesztés: ${jump > 0 ? "+" : ""}${jump} kocka`, `Splice: ${jump > 0 ? "+" : ""}${jump} frames`) });
    }
  });
  [0.2, 0.5, 0.8].forEach((share) => points.push({ seconds: (frames * share) / fps, kind: "sample", label: t("Egyszerű szakasz", "Plain part") }));
  return points.sort((a, b) => a.seconds - b.seconds);
}

function FitTimeline({ segments, frames }: { segments: ExternalMapSegment[]; frames: number }) {
  return (
    <svg className="fit-timeline" viewBox={`0 0 1000 18`} preserveAspectRatio="none" role="img" aria-label={t("Az illesztett szakaszok a film hosszán", "The fitted parts along the film")}>
      <rect x="0" y="0" width="1000" height="18" className="fit-timeline__empty" />
      {segments.map((segment) => (
        <rect
          key={segment.target_start}
          x={(segment.target_start / frames) * 1000}
          y="0"
          width={Math.max(0.5, ((segment.target_end - segment.target_start) / frames) * 1000 - 0.8)}
          height="18"
          className={segment.similarity_median >= 0.8 ? "fit-timeline__good" : "fit-timeline__weak"}
        >
          <title>{`${segment.offset} · ${segment.similarity_median}`}</title>
        </rect>
      ))}
    </svg>
  );
}

function ReviewSource({ job, item }: { job: Job; item: ExternalReviewItem }) {
  const queryClient = useQueryClient();
  const { review, selection } = item;
  const map = review.map;
  const [fpsNumerator, fpsDenominator] = review.target_fps.split("/").map(Number);
  const fps = fpsNumerator / (fpsDenominator || 1);
  const [audio, setAudio] = useState<"fitted" | "original" | "both">("both");
  const [trackIndex, setTrackIndex] = useState(0);
  const [subtitleIndex, setSubtitleIndex] = useState<number | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [activeAt, setActiveAt] = useState<number | null>(null);
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: ["job", job.id] });
    void queryClient.invalidateQueries({ queryKey: ["external-review", job.id] });
  };
  const excerpt = useMutation({
    mutationFn: (seconds: number) => api.createExternalExcerpt(job.id, review.id, {
      track: trackIndex,
      subtitle: subtitleIndex,
      audio,
      start_seconds: Math.max(0, Math.floor(seconds) - 8),
      duration_seconds: 20,
      height: 480,
    }),
    onSuccess: (record, seconds) => { setActive(record.name); setActiveAt(seconds); },
  });
  const approve = useMutation({ mutationFn: () => api.approveExternalSource(job.id, review.id, review.map_sha256), onSuccess: done });
  const discard = useMutation({ mutationFn: () => api.discardExternalSource(job.id, review.id), onSuccess: done });
  const pitch = useMutation({
    mutationFn: (change: { stream: string; pitch: "restore" | "keep" }) => api.setExternalPitch(job.id, review.id, change.stream, change.pitch),
    onSuccess: done,
  });
  const points = listeningPoints(map.segments, fps, map.target_frames);
  const failure = approve.error ?? discard.error ?? pitch.error ?? excerpt.error;
  const missing = map.segments.slice(1).flatMap((segment, index) => {
    const end = map.segments[index].target_end;
    return segment.target_start > end ? [{ from: end, to: segment.target_start }] : [];
  });
  const speed = review.fps !== review.target_fps && map.mode === "frame-locked";
  return (
    <div className="external-review">
      <dl className="summary-list">
        <div><dt>{t("Forrás", "Source")}</dt><dd className="external-path">{review.path}</dd></div>
        <div><dt>{t("Sebesség", "Speed")}</dt><dd>{speed ? t(`${review.fps} fps → a cím sebessége, kockáról kockára`, `${review.fps} fps → the title's speed, frame for frame`) : t("változatlan", "unchanged")}</dd></div>
        <div><dt>{t("Szakaszok", "Parts")}</dt><dd>{map.segments.length}</dd></div>
        <div><dt>{t("Kép-egyezés (medián)", "Picture match (median)")}</dt><dd>{map.similarity_median} · {Math.round(map.share_at_least_0_8 * 100)}% ≥ 0,8</dd></div>
        <div><dt>{t("A forrásban nem szereplő rész", "Not in the source")}</dt><dd>{((map.unmatched_frames / fps)).toFixed(1)} {t("mp", "s")}</dd></div>
      </dl>
      <FitTimeline segments={map.segments} frames={map.target_frames} />
      {missing.length > 0 && <Notice tone="warning" title={t("A külső sáv itt néma lesz", "The external track is silent here")}>{missing.map((part) => <span key={part.from} className="player-track">{clock(part.from / fps)} – {clock(part.to / fps)}</span>)}<p>{t("A HU szabályok a hiányos hangsávot nukeolhatják (incomplete.audio), ezt mérlegeld.", "The HU rules can nuke an incomplete track (incomplete.audio); weigh this.")}</p></Notice>}
      {review.tracks.map((report, index) => {
        const chosen = selection.tracks.find((entry) => entry.stream === report.stream);
        return (
          <div key={report.stream} className="external-track">
            <div className="tracker-secret__head">
              <strong>{report.language} · {report.codec.toUpperCase()} {report.channels} {t("csatorna", "channels")}</strong>
              {report.copy ? <Badge tone="success">{t("újrakódolás nélkül", "not re-encoded")}</Badge> : <Badge tone="info">{report.encoding?.codec.toUpperCase()} {Math.round((report.encoding?.bit_rate ?? 0) / 1000)} kbps</Badge>}
            </div>
            {speed && (
              <label className="field">{t("Hangmagasság", "Pitch")}
                <select value={chosen?.pitch ?? "restore"} disabled={pitch.isPending} onChange={(event) => pitch.mutate({ stream: report.stream, pitch: event.target.value as "restore" | "keep" })}>
                  <option value="restore">{t("Visszaállítás (lassítás, a PAL-gyorsítás pontos visszafordítása)", "Restore (slow down, exactly undoes the PAL speed-up)")}</option>
                  <option value="keep">{t("Megtartás (csak a tempó változik)", "Keep (only the tempo changes)")}</option>
                </select>
              </label>
            )}
            {review.tracks.length > 1 && <label className="check-row"><input type="radio" name={`track-${review.id}`} checked={trackIndex === index} onChange={() => setTrackIndex(index)} /> <span>{t("Ezt hallgatom", "Listen to this")}</span></label>}
          </div>
        );
      })}
      {review.subtitles.map((report, index) => (
        <div key={report.file} className="external-track">
          <label className="check-row">
            <input type="checkbox" checked={subtitleIndex === index} onChange={(event) => setSubtitleIndex(event.target.checked ? index : null)} />
            <span>{t("Felirat a kivonatban", "Subtitle in the excerpt")}: {report.language} · {t(`${report.kept} sor, ${report.dropped} kimaradt, ${report.clipped} levágva`, `${report.kept} cues, ${report.dropped} dropped, ${report.clipped} clipped`)}</span>
          </label>
        </div>
      ))}
      {review.tracks.length > 0 && (
        <>
          <div className="player-stage">
            {active ? (
              <video key={active} className="player-video" controls playsInline autoPlay preload="metadata" src={previewUrl(job.id, active)} aria-label={t("Kivonat az illesztett hanggal", "Excerpt with the fitted audio")} />
            ) : (
              <div className="player-placeholder"><Clapperboard size={34} aria-hidden="true" /><p>{t("Válassz egy pontot a listából. Semmit nem kell letöltened.", "Pick a point from the list. Nothing needs downloading.")}</p></div>
            )}
          </div>
          <label className="field">{t("Mit hallgass", "What to listen to")}
            <select value={audio} onChange={(event) => setAudio(event.target.value as typeof audio)}>
              <option value="both">{t("Fülpróba: bal fül az eredeti, jobb fül az illesztett (a csúszás visszhangként hallatszik)", "Ear test: left the original, right the fitted (a slip is heard as an echo)")}</option>
              <option value="fitted">{t("Csak az illesztett hang", "The fitted audio only")}</option>
              <option value="original">{t("Csak a cím saját első hangja", "Only the title's own first track")}</option>
            </select>
          </label>
          {excerpt.isPending && <p className="muted">{t("A kivonat készül; ez akár fél percig is tarthat…", "Making the excerpt; this can take up to half a minute…")}</p>}
          <ul className="fit-points">
            {points.map((point) => (
              <li key={`${point.kind}-${point.seconds}`} className={activeAt === point.seconds ? "fit-points__active" : ""}>
                <time>{clock(point.seconds)}</time>
                <span>{point.label}</span>
                <Button variant="ghost" icon={<Play size={14} />} disabled={excerpt.isPending} onClick={() => excerpt.mutate(point.seconds)}>{t("Meghallgatom", "Listen")}</Button>
              </li>
            ))}
          </ul>
        </>
      )}
      {failure && <Notice tone="danger">{errorText(failure)}</Notice>}
      <div className="release-actions">
        <Button icon={<Check size={15} />} loading={approve.isPending} onClick={() => approve.mutate()}>{t("Jóváhagyom, mehet tovább", "Approve, go on")}</Button>
        <Button variant="ghost" icon={<Trash2 size={15} />} loading={discard.isPending} onClick={() => discard.mutate()}>{t("Ezt a forrást kihagyom", "Leave this source out")}</Button>
      </div>
    </div>
  );
}

/** The operator's look at a fit: what was found, where to listen, approve or leave out. */
export function ExternalReviewCard({ job }: { job: Job }) {
  const review = useQuery({
    queryKey: ["external-review", job.id, job.version],
    queryFn: () => api.externalReview(job.id),
    retry: false,
  });
  const items = (review.data?.items ?? []).filter((item) => item.selection.approved_map_sha256 !== item.review.map_sha256);
  if (items.length === 0) return null;
  return (
    <Card className="external-card">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><FileAudio size={18} /></span>
          <div>
            <h2>{t("A külső forrás illesztése", "The external source's fit")}</h2>
            <p>{t("Kódolás még nem indult. Hallgasd meg a kritikus pontokat, utána hagyd jóvá.", "Nothing has been encoded yet. Listen to the critical points, then approve.")}</p>
          </div>
        </div>
      </div>
      {items.map((item) => <ReviewSource key={item.review.id} job={job} item={item} />)}
    </Card>
  );
}
