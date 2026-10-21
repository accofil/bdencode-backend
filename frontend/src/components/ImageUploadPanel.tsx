import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ImageUp, KeyRound, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ImageUploadHost, ImageUploadHostStatus, ImageUploadKeyRequest } from "../api/types";
import { t } from "../i18n";
import { IMAGE_HOST_NAMES, IMAGE_UPLOAD_STATUS_QUERY_KEY, imageHostOrderText } from "../uploads";
import { Badge, Button, Card, LoadingPanel, Notice } from "./ui";

/** How long the page waits for the root helper before suggesting a reinstall. */
const KEY_REQUEST_TIMEOUT_MS = 60_000;

/** The same formats the backend and the root helper accept. */
const KEY_PATTERNS: Record<ImageUploadHost, RegExp> = {
  imgbb: /^[A-Za-z0-9]{32}$/,
  freeimage: /^[A-Za-z0-9]{32}$/,
  catbox: /^[A-Za-z0-9]{16,64}$/,
};

function keyHint(host: ImageUploadHost): string {
  if (host === "catbox") return t("userhash (catbox.moe → fiókod oldala)", "user hash (catbox.moe → your account page)");
  if (host === "imgbb") return t("32 karakter (api.imgbb.com)", "32 characters (api.imgbb.com)");
  return t("32 karakter (freeimage.host → API)", "32 characters (freeimage.host → API)");
}

function keyFormatError(host: ImageUploadHost): string {
  if (host === "catbox") return t("A Catbox userhash 16–64 karakter, csak betű és szám.", "The Catbox user hash is 16–64 characters, letters and digits only.");
  const label = IMAGE_HOST_NAMES[host];
  return t(`A(z) ${label} API-kulcsa pontosan 32 karakter, csak betű és szám.`, `The ${label} API key is exactly 32 characters, letters and digits only.`);
}

function keyName(host: ImageUploadHost): string {
  return host === "catbox" ? "userhash" : t("API-kulcs", "API key");
}

interface PendingRequest extends ImageUploadKeyRequest {
  sentAt: number;
}

function HostRow({
  host,
  keyManagement,
  busy,
  onSetKey,
  onDeleteKey,
}: {
  host: ImageUploadHostStatus;
  keyManagement: boolean;
  busy: boolean;
  onSetKey: (key: string) => void;
  onDeleteKey: () => void;
}) {
  const [key, setKey] = useState("");
  const [formatError, setFormatError] = useState<string | null>(null);
  const badge = host.configured
    ? <Badge tone="success">{t("Kulcs beállítva", "Key set")}</Badge>
    : host.key_required
      ? <Badge tone="neutral">{t("Nincs kulcs", "No key")}</Badge>
      : <Badge tone="neutral">{t("Névtelen feltöltés", "Anonymous upload")}</Badge>;
  return (
    <div className="ai-provider-row">
      <div className="ai-provider-row__heading">
        <strong>{host.label}</strong>
        {badge}
      </div>
      {!host.key_required && <p className="muted-copy">{t("A userhash nem kötelező: nélküle a képek névtelenül kerülnek fel.", "The user hash is optional: without it the images are uploaded anonymously.")}</p>}
      {keyManagement && (
        <form
          className="ai-provider-row__key"
          onSubmit={(event) => {
            event.preventDefault();
            const value = key.trim();
            if (!value) return;
            if (!KEY_PATTERNS[host.id].test(value)) {
              setFormatError(keyFormatError(host.id));
              return;
            }
            setFormatError(null);
            onSetKey(value);
            setKey("");
          }}
        >
          <label className="field">
            <span>{host.configured ? t(`Új ${keyName(host.id)} (csere)`, `New ${keyName(host.id)} (replace)`) : keyName(host.id)}</span>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              placeholder={keyHint(host.id)}
              aria-label={t(`${host.label} ${keyName(host.id)}`, `${host.label} ${keyName(host.id)}`)}
              aria-invalid={formatError ? true : undefined}
              onChange={(event) => { setKey(event.target.value); setFormatError(null); }}
            />
          </label>
          {formatError && <p className="upload-key-error" role="alert">{formatError}</p>}
          <div className="ai-provider-row__actions">
            <Button type="submit" icon={<KeyRound size={16} />} disabled={!key.trim() || busy} aria-label={t(`${host.label} kulcs mentése`, `Save the ${host.label} key`)}>{t("Mentés", "Save")}</Button>
            {host.configured && <Button type="button" variant="secondary" icon={<Trash2 size={16} />} disabled={busy} aria-label={t(`${host.label} kulcs törlése`, `Delete the ${host.label} key`)} onClick={onDeleteKey}>{t("Törlés", "Delete")}</Button>}
          </div>
        </form>
      )}
    </div>
  );
}

export function ImageUploadPanel() {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<PendingRequest | null>(null);
  const [outcome, setOutcome] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);
  const [orderDraft, setOrderDraft] = useState<ImageUploadHost[] | null>(null);
  const status = useQuery({
    queryKey: IMAGE_UPLOAD_STATUS_QUERY_KEY,
    queryFn: api.imageUploadStatus,
    // The helper answers within seconds; the API does not restart for these keys.
    refetchInterval: pending ? 2000 : false,
    retry: pending ? true : 1,
  });

  useEffect(() => {
    if (!pending) return;
    const data = status.data;
    const result = data?.key_management?.results.find((item) => item.request_id === pending.request_id);
    const host = data?.hosts.find((item) => item.id === pending.host);
    const label = host?.label ?? IMAGE_HOST_NAMES[pending.host] ?? pending.host;
    if (result && result.state === "applied" && host?.configured === (pending.action === "set")) {
      setOutcome({ tone: "success", text: pending.action === "set"
        ? t(`A(z) ${label} kulcsa elmentve; a worker a következő feltöltésnél már ezt használja.`, `The ${label} key is saved; the worker uses it from the next upload.`)
        : t(`A(z) ${label} kulcsa törölve.`, `The ${label} key is deleted.`) });
      setPending(null);
    } else if (result && result.state !== "applied") {
      setOutcome({ tone: "danger", text: t(`A kulcsot a szerver nem mentette el: ${result.message ?? result.state}`, `The server did not save the key: ${result.message ?? result.state}`) });
      setPending(null);
    } else if (Date.now() - pending.sentAt > KEY_REQUEST_TIMEOUT_MS) {
      setOutcome({ tone: "warning", text: t(
        "A kulcsmentő segédprogram nem válaszolt egy percen belül. Ellenőrizd, hogy a 3.11-es telepítés lefutott-e (bdencode-credentials.path).",
        "The key helper did not answer within a minute. Check that the 3.11 install has run (bdencode-credentials.path).",
      ) });
      setPending(null);
    }
  }, [pending, status.data]);

  const saveOrder = useMutation({
    mutationFn: (order: ImageUploadHost[] | null) => api.saveImageUploadSettings({ provider_order: order }),
    onSuccess: (updated) => {
      queryClient.setQueryData(IMAGE_UPLOAD_STATUS_QUERY_KEY, updated);
      setOrderDraft(null);
    },
  });
  const keyChange = useMutation({
    mutationFn: ({ host, key }: { host: ImageUploadHost; key: string | null }) =>
      key === null ? api.deleteImageUploadKey(host) : api.setImageUploadKey(host, key),
    onMutate: () => setOutcome(null),
    onSuccess: (request) => setPending({ ...request, sentAt: Date.now() }),
  });

  if (status.isLoading) {
    return <Card><LoadingPanel label={t("Képfeltöltési beállítások betöltése…", "Loading the image upload settings…")} /></Card>;
  }
  if (!status.data) {
    return <Card><Notice tone="danger" title={t("A képfeltöltési beállítások nem olvashatók", "The image upload settings cannot be read")}>{t("Frissítsd az oldalt, vagy ellenőrizd a backend verzióját.", "Reload the page or check the backend version.")}</Notice></Card>;
  }
  const data = status.data;
  const keyManagement = data.key_management?.available === true;
  const order = orderDraft ?? data.provider_order;
  const byId = new Map(data.hosts.map((host) => [host.id, host]));
  const configuredCount = data.hosts.filter((host) => host.configured).length;
  const dirty = orderDraft !== null && orderDraft.join() !== data.provider_order.join();
  const isDefault = order.join() === data.default_order.join();
  const move = (index: number, step: -1 | 1) => {
    const next = [...order];
    [next[index], next[index + step]] = [next[index + step], next[index]];
    setOrderDraft(next);
  };

  return (
    <Card className="ai-adviser-panel image-upload-panel">
      <div className="section-heading">
        <div><span className="section-heading__icon"><ImageUp size={19} /></span><div><h3>{t("Képfeltöltés", "Image upload")}</h3><p>{t("A comparison képek tárhelyeinek kulcsai és sorrendje", "The keys and the order of the comparison image hosts")}</p></div></div>
        <Badge tone={configuredCount > 0 ? "success" : "neutral"}>{t(`${configuredCount} / ${data.hosts.length} kulcs beállítva`, `${configuredCount} / ${data.hosts.length} keys set`)}</Badge>
      </div>
      <p className="muted-copy">{t(
        "A kulcs titkosított systemd credentialként kerül a szerverre; az oldal sosem kapja vissza. A futó worker újraindítás nélkül, a következő feltöltésnél már az új kulcsot használja.",
        "The key is stored on the server as an encrypted systemd credential; the page never gets it back. The running worker uses the new key from its next upload, without a restart.",
      )}</p>
      {!keyManagement && (
        <Notice tone="warning" title={t("A képfeltöltők kulcsa itt nem állítható be", "The image host keys cannot be set here")}>
          {t(
            "Ez a szerver még nem futtatja a kulcsmentő segédprogramot (régebbi telepítés vagy fejlesztői mód). Futtasd újra a telepítőt, vagy használd a README 8. pontjának parancsát.",
            "This server does not run the key helper yet (older install or developer mode). Run the installer again, or use the command in section 8 of the README.",
          )}
        </Notice>
      )}
      <div>
        <strong>{t("Sorrend automatikus módban", "Order in automatic mode")}</strong>
        <p className="muted-copy">{t(
          `Az első tárhellyel kezd; ha az nem érhető el, a következővel próbálkozik. Most: ${imageHostOrderText(order)}.`,
          `It starts with the first host and tries the next one when a host is unavailable. Now: ${imageHostOrderText(order)}.`,
        )}</p>
        <ol className="upload-order" aria-label={t("Képtárhelyek sorrendje", "Image host order")}>
          {order.map((id, index) => {
            const label = byId.get(id)?.label ?? IMAGE_HOST_NAMES[id] ?? id;
            return (
              <li key={id}>
                <span className="upload-order__position">{index + 1}</span>
                <strong>{label}</strong>
                <button type="button" className="upload-order__move" disabled={index === 0} aria-label={t(`${label} előrébb`, `Move ${label} up`)} onClick={() => move(index, -1)}><ArrowUp size={15} /></button>
                <button type="button" className="upload-order__move" disabled={index === order.length - 1} aria-label={t(`${label} hátrébb`, `Move ${label} down`)} onClick={() => move(index, 1)}><ArrowDown size={15} /></button>
              </li>
            );
          })}
        </ol>
      </div>
      <div className="ai-adviser-panel__actions">
        <Button icon={<Save size={16} />} disabled={!dirty} loading={saveOrder.isPending} onClick={() => saveOrder.mutate(order)}>{t("Sorrend mentése", "Save order")}</Button>
        <Button variant="secondary" icon={<RotateCcw size={16} />} disabled={!data.custom_order && isDefault} loading={saveOrder.isPending} onClick={() => saveOrder.mutate(null)}>{t("Alapértelmezett sorrend", "Default order")}</Button>
      </div>
      <div className="ai-provider-list upload-host-list">
        {order.map((id) => {
          const host = byId.get(id);
          if (!host) return null;
          return (
            <HostRow
              key={id}
              host={host}
              keyManagement={keyManagement}
              busy={pending !== null || keyChange.isPending}
              onSetKey={(key) => keyChange.mutate({ host: id, key })}
              onDeleteKey={() => keyChange.mutate({ host: id, key: null })}
            />
          );
        })}
      </div>
      {pending && <Notice tone="info" title={t("A képfeltöltő kulcsának mentése…", "Saving the image host key…")}>{t("A szerver titkosítja a kulcsot, és átadja a workernek; ehhez semmi sem indul újra.", "The server encrypts the key and hands it to the worker; nothing restarts for this.")}</Notice>}
      {outcome && <Notice tone={outcome.tone}>{outcome.text}</Notice>}
      {keyChange.isError && <Notice tone="danger" title={t("A kulcs nem küldhető el", "The key cannot be sent")}>{keyChange.error instanceof ApiError ? keyChange.error.detail : t("Ismeretlen hiba történt.", "An unknown error occurred.")}</Notice>}
      {saveOrder.isError && <Notice tone="danger" title={t("A sorrend nem menthető", "The order cannot be saved")}>{saveOrder.error instanceof ApiError ? saveOrder.error.detail : t("Ismeretlen hiba történt.", "An unknown error occurred.")}</Notice>}
    </Card>
  );
}
