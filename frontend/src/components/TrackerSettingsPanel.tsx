import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, PlugZap, Save, Trash2, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { TrackerSecretKind } from "../api/types";
import { t } from "../i18n";
import { Badge, Button, Card, LoadingPanel, Notice } from "./ui";

const QUERY_KEY = ["tracker-settings"];

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.detail : error instanceof Error ? error.message : String(error);
}

function SecretRow({
  kind,
  label,
  hint,
  multiline,
  configured,
  canManage,
  canCheck,
}: {
  kind: TrackerSecretKind;
  label: string;
  hint: string;
  multiline?: boolean;
  configured: boolean;
  canManage: boolean;
  canCheck: boolean;
}) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const refresh = () => {
    window.setTimeout(() => void queryClient.invalidateQueries({ queryKey: QUERY_KEY }), 3000);
  };
  const save = useMutation({
    mutationFn: () => api.setTrackerSecret(kind, value),
    onSuccess: () => { setValue(""); refresh(); },
  });
  const remove = useMutation({ mutationFn: () => api.deleteTrackerSecret(kind), onSuccess: refresh });
  const check = useMutation({ mutationFn: () => api.checkTrackerConnection(kind) });
  const failure = save.error ?? remove.error;
  return (
    <div className="tracker-secret">
      <div className="tracker-secret__head">
        <strong>{label}</strong>
        {configured ? <Badge tone="success">{t("Beállítva", "Set")}</Badge> : <Badge tone="neutral">{t("Nincs beállítva", "Not set")}</Badge>}
      </div>
      <label className="field">
        {hint}
        {multiline
          ? <textarea rows={3} autoComplete="off" spellCheck={false} disabled={!canManage} value={value} onChange={(event) => setValue(event.target.value)} />
          : <input type="password" autoComplete="off" disabled={!canManage} value={value} onChange={(event) => setValue(event.target.value)} />}
      </label>
      <div className="release-actions">
        <Button variant="secondary" icon={<KeyRound size={15} />} loading={save.isPending} disabled={!canManage || !value} onClick={() => save.mutate()}>{t("Mentés", "Save")}</Button>
        {configured && <Button variant="ghost" icon={<Trash2 size={15} />} loading={remove.isPending} disabled={!canManage} onClick={() => remove.mutate()}>{t("Törlés", "Delete")}</Button>}
        <Button variant="ghost" icon={<PlugZap size={15} />} loading={check.isPending} disabled={!canCheck} onClick={() => check.mutate()}>{t("Kapcsolat ellenőrzése", "Check the connection")}</Button>
      </div>
      {save.isSuccess && <Notice tone="info">{t("Elküldve. A háttérszolgáltatás újraindul, hogy betöltse.", "Sent. The API restarts to load it.")}</Notice>}
      {check.isSuccess && <Notice tone="success">{check.data.result}</Notice>}
      {check.isError && <Notice tone="danger">{errorText(check.error)}</Notice>}
      {failure && <Notice tone="danger">{errorText(failure)}</Notice>}
    </div>
  );
}

export function TrackerSettingsPanel() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: QUERY_KEY, queryFn: api.trackerSettings });
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  useEffect(() => {
    if (status.data) {
      setUrl(status.data.qbittorrent.url);
      setUsername(status.data.qbittorrent.username);
    }
  }, [status.data]);
  const save = useMutation({
    mutationFn: () => api.saveTrackerSettings({ schema_version: 1, qbittorrent_url: url, qbittorrent_username: username }),
    onSuccess: (data) => queryClient.setQueryData(QUERY_KEY, data),
  });
  if (status.isLoading) return <LoadingPanel label={t("Tracker-beállítások betöltése…", "Loading the tracker settings…")} />;
  if (!status.data) return status.isError ? <Notice tone="danger">{errorText(status.error)}</Notice> : null;
  const data = status.data;
  const canManage = data.key_management?.available === true;
  return (
    <Card className="tracker-settings">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><UploadCloud size={18} /></span>
          <div>
            <h2>{t("Trackerek és seedelés", "Trackers and seeding")}</h2>
            <p>{t("Csak Aither és nCore. A belépési adatok titkosítva, a szerveren maradnak; a program soha nem mutatja vissza őket.", "Aither and nCore only. The logins stay encrypted on the server; the program never shows them again.")}</p>
          </div>
        </div>
      </div>
      {!canManage && <Notice tone="warning">{t("Ezen a szerveren a belépési adatok a weboldalról nem állíthatók be.", "The logins cannot be set from the web page on this server.")}</Notice>}
      <SecretRow kind="aither" label="Aither" hint={t("API-kulcs (az Aither-profilod beállításaiból)", "API key (from your Aither profile settings)")} configured={data.aither.configured} canManage={canManage} canCheck={data.aither.configured} />
      <SecretRow kind="ncore" label="nCore" multiline hint={t("A böngészőből exportált cookies.txt tartalma; ha lejár, újra be kell illeszteni", "The contents of the cookies.txt exported from the browser; paste it again when it expires")} configured={data.ncore.configured} canManage={canManage} canCheck={data.ncore.configured} />
      <div className="tracker-secret">
        <div className="tracker-secret__head"><strong>qBittorrent</strong></div>
        <p className="muted">{t("Feltöltés után ide kerül a torrent, „bdencode” kategóriával, ezért a többi automatizmusod nem nyúl hozzá. Üresen hagyva a seedelés kézi marad.", "After the upload the torrent goes here in the “bdencode” category, so your other automations leave it alone. Left empty, seeding stays manual.")}</p>
        <div className="release-form-grid">
          <label className="field">{t("Cím", "Address")}<input placeholder="http://127.0.0.1:8080" value={url} onChange={(event) => setUrl(event.target.value)} /></label>
          <label className="field">{t("Felhasználó", "User name")}<input autoComplete="off" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        </div>
        <div className="release-actions">
          <Button variant="secondary" icon={<Save size={15} />} loading={save.isPending} onClick={() => save.mutate()}>{t("Cím mentése", "Save the address")}</Button>
        </div>
        {save.isError && <Notice tone="danger">{errorText(save.error)}</Notice>}
      </div>
      <SecretRow kind="qbittorrent" label={t("qBittorrent jelszó", "qBittorrent password")} hint={t("A WebUI jelszava; ha a helyi címről nem kér belépést, nem kell", "The WebUI password; not needed when it asks for no login from the local address")} configured={data.qbittorrent.password_set} canManage={canManage} canCheck={data.qbittorrent.configured} />
    </Card>
  );
}
