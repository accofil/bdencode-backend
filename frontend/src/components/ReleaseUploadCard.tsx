import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileDigit, RefreshCw, SearchCheck, Sprout, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { DupeMatch, ReleasePreparation, UploadFields, UploadPlan } from "../api/types";
import { t } from "../i18n";
import { Badge, Button, Card, LoadingPanel, Modal, Notice } from "./ui";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.detail : error instanceof Error ? error.message : String(error);
}

function receiptValue(receipt: Record<string, unknown> | null | undefined, key: string): string | null {
  const value = receipt?.[key];
  return typeof value === "string" && value ? value : null;
}

function matchesOf(preparation: ReleasePreparation): DupeMatch[] {
  const matches = preparation.dupe_receipt?.matches;
  return Array.isArray(matches) ? (matches as DupeMatch[]) : [];
}

/** The plan's facts in the interface's language. */
function factLabel(key: string): string {
  const labels: Record<string, [string, string]> = {
    type: ["Típus", "Type"],
    category: ["Kategória", "Category"],
    resolution: ["Felbontás", "Resolution"],
    tmdb: ["TMDB", "TMDB"],
    imdb: ["IMDb", "IMDb"],
    year: ["Év", "Year"],
    dynamic_range: ["HDR-jelölés", "Dynamic range"],
    mediainfo_characters: ["MediaInfo hossza (karakter)", "MediaInfo length (characters)"],
    sample: ["Sample a torrentben", "Sample in the torrent"],
  };
  const label = labels[key];
  return label ? t(label[0], label[1]) : key;
}

function factValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ") || "—";
  if (typeof value === "boolean") return value ? t("igen", "yes") : t("nem", "no");
  return String(value ?? "—");
}

const AITHER_TEXT_FIELDS: Array<[keyof UploadFields, string, string]> = [["name", "Név az Aitheren", "Name on Aither"]];
const NCORE_TEXT_FIELDS: Array<[keyof UploadFields, string, string]> = [
  ["name", "Név az nCore-on", "Name on nCore"],
  ["title_hu", "Magyar cím", "Hungarian title"],
  ["title_en", "Angol cím", "English title"],
  ["title_other", "Egyéb cím", "Other title"],
  ["country", "Ország", "Country"],
  ["runtime", "Hossz (perc)", "Runtime (minutes)"],
  ["directors", "Rendező", "Director"],
  ["cast", "Szereplők", "Cast"],
  ["audio", "Hangsávok", "Audio tracks"],
  ["subtitles", "Feliratok", "Subtitles"],
  ["extras", "Extrák", "Extras"],
];

/** Shows exactly what goes up; nothing is sent until the operator confirms this one release. */
function UploadDialog({
  preparation,
  open,
  onClose,
}: {
  preparation: ReleasePreparation;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const id = preparation.id ?? "";
  const planQuery = useQuery({
    queryKey: ["release-upload-plan", id, preparation.version],
    queryFn: () => api.releaseUploadPlan(id),
    enabled: open && Boolean(id),
    staleTime: Infinity,
    retry: false,
  });
  const plan: UploadPlan | undefined = planQuery.data;
  const [fields, setFields] = useState<UploadFields | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (plan) setFields(plan.fields);
    setConfirmed(false);
  }, [plan]);

  const upload = useMutation({
    mutationFn: () => api.uploadRelease(id, plan!.tracker, {
      expected_version: preparation.version!,
      confirm_release_name: plan!.release_name,
      torrent_sha256: plan!.torrent_sha256,
      ...fields!,
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["release-preparation", id], updated);
      void queryClient.invalidateQueries({ queryKey: ["release-preparations", preparation.job_id] });
      onClose();
    },
  });
  const set = (key: keyof UploadFields, value: string | boolean) =>
    setFields((current) => (current ? { ...current, [key]: value } : current));
  const textFields = plan?.tracker === "ncore" ? NCORE_TEXT_FIELDS : AITHER_TEXT_FIELDS;
  const trackerName = plan?.tracker === "ncore" ? "nCore" : "Aither";

  return (
    <Modal
      open={open}
      size="wide"
      title={t(`Feltöltés: ${trackerName}`, `Upload to ${trackerName}`)}
      busy={upload.isPending}
      onClose={() => { if (!upload.isPending) onClose(); }}
      footer={
        <>
          <Button variant="ghost" disabled={upload.isPending} onClick={onClose}>{t("Mégse", "Cancel")}</Button>
          <Button
            icon={<UploadCloud size={16} />}
            loading={upload.isPending}
            disabled={!plan || !fields || !confirmed}
            onClick={() => upload.mutate()}
          >
            {t("Feltöltés most", "Upload now")}
          </Button>
        </>
      }
    >
      {planQuery.isLoading && <LoadingPanel label={t("A feltöltési terv készül…", "Preparing the upload plan…")} />}
      {planQuery.isError && <Notice tone="danger" title={t("A terv nem készíthető el", "The plan cannot be made")}>{errorText(planQuery.error)}</Notice>}
      {plan && fields && (
        <div className="upload-plan">
          <Notice tone="warning" title={t("Ez valódi feltöltés a trackerre", "This is a real upload to the tracker")}>
            {t("Csak egyszer küldi el. Ha a válasz nem egyértelmű, a program nem próbálja újra: előbb meg kell nézni a trackeren.", "It is sent once. If the answer is unclear, the program does not try again: look at the tracker first.")}
          </Notice>
          {plan.problems.length > 0 && (
            <Notice tone="danger" title={t("Ezt még javítani kell", "This still needs fixing")}>
              <ul>{plan.problems.map((item) => <li key={item}>{item}</li>)}</ul>
            </Notice>
          )}
          <dl className="summary-list summary-list--stacked">
            {Object.entries(plan.facts).map(([key, value]) => (
              <div key={key}><dt>{factLabel(key)}</dt><dd>{factValue(value)}</dd></div>
            ))}
            <div><dt>{t("Fájlok", "Files")}</dt><dd>{plan.files.join(", ")}</dd></div>
            <div>
              <dt>{t("Seedelés", "Seeding")}</dt>
              <dd>{plan.seeding.automatic
                ? t(`automatikus, qBittorrent „${plan.seeding.category}” kategória`, `automatic, qBittorrent category “${plan.seeding.category}”`)
                : t("kézi: nincs qBittorrent-cím a Rendszer oldalon", "by hand: no qBittorrent address on the System page")}</dd>
            </div>
          </dl>
          <div className="release-form-grid">
            {textFields.map(([key, hungarian, english]) => (
              <label className="field release-field--wide" key={key}>
                {t(hungarian, english)}
                <input value={String(fields[key] ?? "")} onChange={(event) => set(key, event.target.value)} />
              </label>
            ))}
            <label className="field release-field--wide">
              {t("Leírás", "Description")}
              <textarea rows={plan.tracker === "ncore" ? 8 : 12} value={fields.description} onChange={(event) => set("description", event.target.value)} />
            </label>
          </div>
          {plan.tracker === "ncore" && (
            <p className="muted">{t("A leírás végén legyen a forrás: „Forrás: …”. A menüt, feliratot, hangot és extrát az nCore az űrlapból teszi elé.", "End the description with the source: “Forrás: …”. nCore puts the menu, subtitles, audio and extras before it from the form.")}</p>
          )}
          {plan.tracker === "aither" && (
            <div className="upload-plan__flags">
              <label><input type="checkbox" checked={Boolean(fields.anonymous)} onChange={(event) => set("anonymous", event.target.checked)} /> {t("Névtelen feltöltés", "Anonymous upload")}</label>
              <label><input type="checkbox" checked={Boolean(fields.personal_release)} onChange={(event) => set("personal_release", event.target.checked)} /> {t("Saját kiadás", "Personal release")}</label>
              <label><input type="checkbox" checked={Boolean(fields.mod_queue)} onChange={(event) => set("mod_queue", event.target.checked)} /> {t("Moderátori sorba kérem", "Send to the moderation queue")}</label>
            </div>
          )}
          {plan.tracker === "ncore" && (
            <div className="upload-plan__flags">
              <label><input type="checkbox" checked={Boolean(fields.menu)} onChange={(event) => set("menu", event.target.checked)} /> {t("Van menü", "Has a menu")}</label>
            </div>
          )}
          <label className="upload-plan__confirm">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            <span>{t(`Átnéztem, és ezt töltöm fel: ${plan.release_name}`, `I checked it and I upload this: ${plan.release_name}`)}</span>
          </label>
          {upload.isError && <Notice tone="danger" title={t("A feltöltés nem indult el", "The upload did not start")}>{errorText(upload.error)}</Notice>}
        </div>
      )}
    </Modal>
  );
}

export function ReleaseUploadCard({ preparation }: { preparation: ReleasePreparation }) {
  const queryClient = useQueryClient();
  const id = preparation.id ?? "";
  const version = preparation.version ?? 0;
  const state = preparation.state ?? "";
  const [uploading, setUploading] = useState(false);
  const [reason, setReason] = useState("");
  const settle = (updated: ReleasePreparation) => {
    queryClient.setQueryData(["release-preparation", id], updated);
    void queryClient.invalidateQueries({ queryKey: ["release-preparations", preparation.job_id] });
  };
  const torrent = useMutation({ mutationFn: () => api.buildReleaseTorrent(id, version), onSuccess: settle });
  const dupe = useMutation({ mutationFn: () => api.releasePreparationAction(id, "dupe-check", version), onSuccess: settle });
  const acknowledge = useMutation({
    mutationFn: () => api.acknowledgeReleaseDuplicates(id, version, reason),
    onSuccess: (updated) => { setReason(""); settle(updated); },
  });
  const seed = useMutation({ mutationFn: () => api.seedRelease(id, version), onSuccess: settle });

  const hasTorrent = Boolean(preparation.torrent_infohash);
  const building = state === "BUILDING_TORRENT";
  const publishing = state === "PUBLISHING";
  const seeding = state === "SEEDING";
  const published = state === "PUBLISHED";
  const receipt = preparation.dupe_receipt;
  const outcome = receiptValue(receipt, "outcome");
  const blocked = receiptValue(receipt, "blocked_reason");
  const matches = matchesOf(preparation);
  const exact = matches.some((item) => item.exact);
  const seedOutcome = receiptValue(preparation.qbittorrent_receipt, "outcome");
  const link = receiptValue(preparation.publication_receipt, "url");
  const busy = torrent.isPending || dupe.isPending || acknowledge.isPending || seed.isPending;
  const failure = torrent.error ?? dupe.error ?? acknowledge.error ?? seed.error;

  return (
    <Card className="release-actions-card" aria-busy={building || publishing || seeding}>
      <div>
        <span className="eyebrow">{t("Feltöltés", "Upload")}</span>
        <h2>{t("Torrent, dupe check, feltöltés, seed", "Torrent, dupe check, upload, seed")}</h2>
        <p>{t("Minden lépést te indítasz. Magától semmi nem kerül fel a trackerre.", "You start every step. Nothing reaches the tracker by itself.")}</p>
      </div>
      <div className="release-actions">
        <Button
          icon={<FileDigit size={16} />}
          loading={torrent.isPending || building}
          disabled={busy || building || hasTorrent || state !== "READY"}
          onClick={() => torrent.mutate()}
        >
          {hasTorrent ? t("A torrent kész", "The torrent is ready") : building ? t("Torrent készül…", "Making the torrent…") : t("Torrent készítése", "Make the torrent")}
        </Button>
        <Button
          variant="secondary"
          icon={<SearchCheck size={16} />}
          loading={dupe.isPending}
          disabled={busy || !hasTorrent || !["READY", "NEEDS_REVIEW", "UNKNOWN"].includes(state)}
          onClick={() => dupe.mutate()}
        >
          {t("Dupe check", "Dupe check")}
        </Button>
        <Button
          icon={<UploadCloud size={16} />}
          loading={publishing}
          disabled={busy || state !== "READY_TO_PUBLISH"}
          onClick={() => setUploading(true)}
        >
          {publishing ? t("Feltöltés…", "Uploading…") : t("Feltöltés…", "Upload…")}
        </Button>
        {published && (
          <>
            <Button variant="secondary" icon={<RefreshCw size={16} />} loading={seed.isPending} disabled={busy || seedOutcome === "SEEDING"} onClick={() => seed.mutate()}>
              {t("Seed újra", "Seed again")}
            </Button>
            <a className="button button--ghost" href={api.releaseSiteTorrentUrl(id)} download>
              <Download size={16} /> {t("Tracker torrentje", "The tracker's torrent")}
            </a>
          </>
        )}
      </div>

      {building && <Notice tone="info">{t("A hashelés egy nagy fájlnál több perc is lehet; a lap magától frissül.", "Hashing a large file can take minutes; the page refreshes by itself.")}</Notice>}
      {seeding && <Notice tone="info" title={t("A qBittorrent ellenőrzi az adatot", "qBittorrent is checking the data")}><Sprout size={15} /> {t("A feltöltés kész. A seed az ellenőrzés után indul.", "The upload is done. The seed starts after the check.")}</Notice>}
      {state === "UNKNOWN" && <Notice tone="warning" title={t("Nem tudni, felment-e", "It is not known whether it went up")}>{t("Nézd meg a trackeren. Utána a Dupe check újra megkeresi; ha ott van, a program nem engedi még egyszer.", "Look at the tracker. The dupe check then looks it up again; if it is there, the program does not allow it twice.")}</Notice>}

      {outcome === "CLEAR" && <Notice tone="success">{t("A dupe check nem talált ilyen kiadást.", "The dupe check found no such release.")}</Notice>}
      {blocked && <Notice tone="danger" title={t("Ez nem tölthető fel", "This cannot be uploaded")}>{blocked}</Notice>}
      {matches.length > 0 && !published && (
        <Notice tone={exact ? "danger" : "warning"} title={exact ? t("Pontosan ez a név már fent van", "This exact name is already there") : t("Ehhez a filmhez már van feltöltés", "This film already has uploads")}>
          <ul>
            {matches.slice(0, 20).map((item) => (
              <li key={`${item.url}-${item.name}`}>
                {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.name}</a> : item.name}
                {item.exact && <> <Badge tone="danger">{t("azonos név", "same name")}</Badge></>}
                {item.trumpable && <> <Badge tone="warning">trumpable</Badge></>}
              </li>
            ))}
          </ul>
          {state === "NEEDS_REVIEW" && outcome === "DUPLICATE" && !exact && (
            <div className="upload-plan__acknowledge">
              <label className="field">
                {t("Miért férhet el mellettük? (legalább 12 karakter)", "Why can it stand next to them? (at least 12 characters)")}
                <input maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} />
              </label>
              <Button variant="secondary" loading={acknowledge.isPending} disabled={busy || reason.trim().length < 12} onClick={() => acknowledge.mutate()}>
                {t("Átnéztem, mehet tovább", "Checked, go on")}
              </Button>
            </div>
          )}
        </Notice>
      )}

      {published && (
        <Notice tone="success" title={t("Feltöltve", "Uploaded")}>
          {link ? <a href={link} target="_blank" rel="noreferrer">{link}</a> : t("A tracker elfogadta.", "The tracker accepted it.")}
          {seedOutcome === "SEEDING" && <p>{t("A qBittorrent seedeli.", "qBittorrent seeds it.")}</p>}
        </Notice>
      )}
      {failure && <Notice tone="danger" title={t("A művelet nem sikerült", "The action failed")}>{errorText(failure)}</Notice>}
      <UploadDialog preparation={preparation} open={uploading} onClose={() => setUploading(false)} />
    </Card>
  );
}
