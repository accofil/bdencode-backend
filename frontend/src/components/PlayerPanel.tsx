import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Film, Trash2, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError, previewUrl } from "../api/client";
import type { PreviewRecord } from "../api/types";
import { t } from "../i18n";
import { formatBytes, formatDuration } from "../utils";
import { Badge, Button, Card, EmptyState, LoadingPanel, Notice } from "./ui";

const DURATION_CHOICES = [10, 20, 30];

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.detail : error instanceof Error ? error.message : t("Ismeretlen hiba", "Unknown error");
}

/**
 * Built-in player for the finished MKV.
 *
 * Browsers cannot play most release MKVs (HEVC, DTS, FLAC, HDR), so the backend
 * cuts a short H.264/AAC excerpt on demand.  The excerpt is only a viewing aid;
 * it is never part of the release.
 */
export function PlayerPanel({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient();
  const info = useQuery({
    queryKey: ["player", jobId],
    queryFn: () => api.playerInfo(jobId),
    retry: false,
  });
  const [start, setStart] = useState(0);
  const [duration, setDuration] = useState(20);
  const [height, setHeight] = useState(720);
  const [active, setActive] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.createPreview(jobId, { start_seconds: Math.floor(start), duration_seconds: duration, height }),
    onSuccess: (record) => {
      setActive(record.name);
      void queryClient.invalidateQueries({ queryKey: ["player", jobId] });
    },
  });
  const remove = useMutation({
    mutationFn: (name: string) => api.deletePreview(jobId, name),
    onSuccess: (_result, name) => {
      if (active === name) setActive(null);
      void queryClient.invalidateQueries({ queryKey: ["player", jobId] });
    },
  });

  const data = info.data;
  const heights = data?.limits.heights ?? [360, 480, 720];
  useEffect(() => {
    if (data && !heights.includes(height)) setHeight(heights[heights.length - 1]);
  }, [data, heights, height]);

  if (info.isLoading) return <LoadingPanel label={t("A lejátszó adatainak betöltése…", "Loading player data…")} />;
  if (info.isError || !data) {
    const error = info.error;
    const unavailable = error instanceof ApiError && error.status === 503;
    return (
      <EmptyState
        icon={<Clapperboard size={30} />}
        title={unavailable ? t("A lejátszó ezen a szerveren nem érhető el", "The player is not available on this server") : t("A lejátszó még nem használható", "The player is not usable yet")}
        description={
          unavailable
            ? t("A kivonatok készítéséhez az ffmpeg és az ffprobe szükséges.", "Making excerpts needs ffmpeg and ffprobe.")
            : `${errorText(error)}. ${t("A lejátszó a kész MKV elkészülte után nyílik meg.", "The player opens once the finished MKV exists.")}`
        }
      />
    );
  }

  const total = data.duration_seconds ?? 0;
  const maxStart = Math.max(0, Math.floor(total) - data.limits.min_duration_seconds);
  const video = data.video;

  return (
    <div className="player-panel">
      <Card className="player-card">
        <div className="section-heading">
          <div>
            <span className="section-heading__icon"><Film size={19} /></span>
            <div>
              <h2>{t("Beépített lejátszó", "Built-in player")}</h2>
              <p>{t("Böngészőbarát H.264/AAC kivonat a kész MKV-ból · nem része a kiadásnak", "Browser-friendly H.264/AAC excerpt of the finished MKV · not part of the release")}</p>
            </div>
          </div>
        </div>

        <div className="player-stage" data-testid="player-stage">
          {active ? (
            <video
              key={active}
              className="player-video"
              controls
              playsInline
              preload="metadata"
              src={previewUrl(jobId, active)}
              aria-label={t("A kész MKV kivonata", "Excerpt of the finished MKV")}
            />
          ) : (
            <div className="player-placeholder">
              <Clapperboard size={34} aria-hidden="true" />
              <p>{t("Válassz kezdőpontot, és készíts kivonatot a lejátszáshoz.", "Pick a start point and make an excerpt to play.")}</p>
            </div>
          )}
        </div>

        <div className="player-controls">
          <label className="field player-start">
            <span>{t("Kezdőpont", "Start")}: {formatDuration(start)} / {formatDuration(total)}</span>
            <input
              type="range"
              min={0}
              max={maxStart}
              step={1}
              value={Math.min(start, maxStart)}
              onChange={(event) => setStart(Number(event.target.value))}
              aria-label={t("Kivonat kezdőpontja", "Excerpt start point")}
            />
          </label>
          <div className="player-nudge" role="group" aria-label={t("Kezdőpont léptetése", "Step the start point")}>
            <Button variant="ghost" onClick={() => setStart((value) => Math.max(0, value - 60))}>{t("−1 perc", "−1 min")}</Button>
            <Button variant="ghost" onClick={() => setStart((value) => Math.min(maxStart, value + 60))}>{t("+1 perc", "+1 min")}</Button>
          </div>
          <label className="field">
            <span>{t("Hossz", "Length")}</span>
            <select value={duration} onChange={(event) => setDuration(Number(event.target.value))} aria-label={t("Kivonat hossza", "Excerpt length")}>
              {DURATION_CHOICES.filter((value) => value >= data.limits.min_duration_seconds && value <= data.limits.max_duration_seconds).map((value) => (
                <option key={value} value={value}>{value} {t("másodperc", "seconds")}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{t("Felbontás", "Resolution")}</span>
            <select value={height} onChange={(event) => setHeight(Number(event.target.value))} aria-label={t("Kivonat felbontása", "Excerpt resolution")}>
              {heights.map((value) => <option key={value} value={value}>{value}p</option>)}
            </select>
          </label>
          <Button icon={<Clapperboard size={17} />} loading={create.isPending} onClick={() => create.mutate()}>
            {t("Kivonat készítése", "Make excerpt")}
          </Button>
        </div>
        {create.isPending && <p className="muted">{t("A kivonat készül; UHD forrásnál ez akár fél percig is tarthat…", "Making the excerpt; with a UHD source this can take up to half a minute…")}</p>}
        {create.isError && <Notice tone="danger" title={t("A kivonat nem készült el", "The excerpt was not made")}>{errorText(create.error)}</Notice>}
        {remove.isError && <Notice tone="danger">{errorText(remove.error)}</Notice>}
        {video?.hdr && (
          <Notice tone="info">{t("HDR forrás: a kivonat SDR-re tone-map-elt, ezért a színek eltérnek a valódi HDR megjelenéstől.", "HDR source: the excerpt is tone-mapped to SDR, so its colours differ from the real HDR look.")}</Notice>
        )}
      </Card>

      {data.chapters.length > 0 && (
        <Card>
          <span className="eyebrow">{t("Fejezetek", "Chapters")}</span>
          <ul className="player-chapters">
            {data.chapters.map((chapter, index) => (
              <li key={`${chapter.start_seconds}-${index}`}>
                <button type="button" onClick={() => setStart(Math.min(maxStart, Math.floor(chapter.start_seconds)))}>
                  <time>{formatDuration(chapter.start_seconds)}</time> {chapter.title}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <span className="eyebrow">{t("Elkészült kivonatok", "Finished excerpts")}</span>
        {data.previews.length === 0 ? (
          <p className="muted">{t("Még nincs kivonat ehhez a munkához.", "No excerpt for this job yet.")}</p>
        ) : (
          <ul className="preview-list">
            {data.previews.map((preview: PreviewRecord) => (
              <li key={preview.name} className={preview.name === active ? "preview-list__item preview-list__item--active" : "preview-list__item"}>
                <button type="button" onClick={() => setActive(preview.name)} aria-pressed={preview.name === active}>
                  {formatDuration(preview.start_seconds)} · {preview.duration_seconds} s · {preview.height}p
                  <small>{formatBytes(preview.size_bytes)}</small>
                </button>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`${t("Kivonat törlése", "Delete excerpt")} (${formatDuration(preview.start_seconds)})`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(preview.name)}
                >
                  <Trash2 size={15} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <span className="eyebrow">{t("Az MKV adatai", "MKV details")}</span>
        <dl className="summary-list summary-list--stacked">
          <div><dt>{t("Hossz", "Length")}</dt><dd>{formatDuration(data.duration_seconds)}</dd></div>
          {video && (
            <div>
              <dt>{t("Videó", "Video")}</dt>
              <dd>
                {(video.codec ?? "?").toUpperCase()} · {video.width}×{video.height}
                {video.hdr && <> <Badge tone="info">HDR</Badge></>}
              </dd>
            </div>
          )}
          <div>
            <dt><Volume2 size={13} aria-hidden="true" /> {t("Hangsávok", "Audio tracks")}</dt>
            <dd>
              {data.audio.length === 0
                ? "—"
                : data.audio.map((track, index) => (
                  <span key={index} className="player-track">
                    {(track.codec ?? "?").toUpperCase()}{track.channels ? ` ${track.channels}ch` : ""}{track.language ? ` · ${track.language}` : ""}
                  </span>
                ))}
            </dd>
          </div>
          <div><dt>{t("Feliratok", "Subtitles")}</dt><dd>{data.subtitles}</dd></div>
        </dl>
      </Card>
    </div>
  );
}
