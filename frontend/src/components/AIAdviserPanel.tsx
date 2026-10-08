import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Save, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { AIKeyRequest, AIProvider, AIProviderStatus, AIRecommendationStatus, AISettings } from "../api/types";
import { t } from "../i18n";
import { Badge, Button, Card, LoadingPanel, Notice } from "./ui";

/** How long the page waits for the root helper before suggesting a reinstall. */
const KEY_REQUEST_TIMEOUT_MS = 60_000;

const keyHints: Record<AIProvider, string> = {
  openai: "sk-… (OpenAI Platform → API keys)",
  anthropic: "sk-ant-… (Claude Console → API Keys)",
};

function settingsFrom(status: AIRecommendationStatus): AISettings {
  const model = (id: AIProvider) => {
    const provider = status.providers?.find((item) => item.id === id);
    return provider && provider.model !== provider.default_model ? provider.model : null;
  };
  return {
    default_provider: status.default_provider ?? null,
    openai_model: model("openai"),
    anthropic_model: model("anthropic"),
  };
}

interface PendingRequest extends AIKeyRequest {
  sentAt: number;
}

function ProviderRow({
  provider,
  model,
  onModel,
  keyManagement,
  busy,
  onSetKey,
  onDeleteKey,
}: {
  provider: AIProviderStatus;
  model: string;
  onModel: (value: string) => void;
  keyManagement: boolean;
  busy: boolean;
  onSetKey: (key: string) => void;
  onDeleteKey: () => void;
}) {
  const [key, setKey] = useState("");
  return (
    <div className="ai-provider-row">
      <div className="ai-provider-row__heading">
        <strong>{provider.label}</strong>
        <Badge tone={provider.configured ? "success" : "neutral"}>{provider.configured ? t("Kulcs beállítva", "Key set") : t("Nincs kulcs", "No key")}</Badge>
      </div>
      <label className="field">
        <span>{t("Modell", "Model")}</span>
        <input value={model} maxLength={100} placeholder={provider.default_model} onChange={(event) => onModel(event.target.value)} />
      </label>
      {keyManagement && (
        <form
          className="ai-provider-row__key"
          onSubmit={(event) => {
            event.preventDefault();
            if (key.trim()) {
              onSetKey(key.trim());
              setKey("");
            }
          }}
        >
          <label className="field">
            <span>{provider.configured ? t("Új API-kulcs (csere)", "New API key (replace)") : t("API-kulcs", "API key")}</span>
            <input type="password" autoComplete="off" spellCheck={false} value={key} placeholder={keyHints[provider.id]} aria-label={t(`${provider.label} API-kulcs`, `${provider.label} API key`)} onChange={(event) => setKey(event.target.value)} />
          </label>
          <div className="ai-provider-row__actions">
            <Button type="submit" icon={<KeyRound size={16} />} disabled={!key.trim() || busy}>{t("Kulcs mentése", "Save key")}</Button>
            {provider.configured && <Button type="button" variant="secondary" icon={<Trash2 size={16} />} disabled={busy} onClick={onDeleteKey}>{t("Kulcs törlése", "Delete key")}</Button>}
          </div>
        </form>
      )}
    </div>
  );
}

export function AIAdviserPanel() {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<PendingRequest | null>(null);
  const [outcome, setOutcome] = useState<{ tone: "success" | "danger" | "warning"; text: string } | null>(null);
  const status = useQuery({
    queryKey: ["ai-recommendation-status"],
    queryFn: api.aiRecommendationStatus,
    // While the helper works the API restarts: keep asking until it answers.
    refetchInterval: pending ? 2000 : false,
    retry: pending ? true : 1,
  });
  const [draft, setDraft] = useState<AISettings | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (status.data && !dirty) setDraft(settingsFrom(status.data));
  }, [dirty, status.data]);

  useEffect(() => {
    if (!pending) return;
    const result = status.data?.key_management?.results.find((item) => item.request_id === pending.request_id);
    const label = status.data?.providers?.find((item) => item.id === pending.provider)?.label ?? pending.provider;
    if (result && result.state === "applied" && status.data?.providers?.find((item) => item.id === pending.provider)?.configured === (pending.action === "set")) {
      setOutcome({ tone: "success", text: pending.action === "set"
        ? t(`A(z) ${label} kulcsa elmentve, az AI-tanácsadó használhatja.`, `The ${label} key is saved; the AI adviser can use it.`)
        : t(`A(z) ${label} kulcsa törölve.`, `The ${label} key is deleted.`) });
      setPending(null);
    } else if (result && result.state !== "applied") {
      setOutcome({ tone: "danger", text: t(`A kulcsot a szerver nem mentette el: ${result.message ?? result.state}`, `The server did not save the key: ${result.message ?? result.state}`) });
      setPending(null);
    } else if (Date.now() - pending.sentAt > KEY_REQUEST_TIMEOUT_MS) {
      setOutcome({ tone: "warning", text: t(
        "A kulcsmentő segédprogram nem válaszolt egy percen belül. Ellenőrizd, hogy a 3.2-es telepítés lefutott-e (bdencode-credentials.path).",
        "The key helper did not answer within a minute. Check that the 3.2 install has run (bdencode-credentials.path).",
      ) });
      setPending(null);
    }
  }, [pending, status.data]);

  const saveSettings = useMutation({
    mutationFn: (settings: AISettings) => api.saveAISettings(settings),
    onSuccess: (updated) => {
      queryClient.setQueryData(["ai-recommendation-status"], updated);
      setDirty(false);
      setDraft(settingsFrom(updated));
    },
  });
  const keyChange = useMutation({
    mutationFn: ({ provider, key }: { provider: AIProvider; key: string | null }) =>
      key === null ? api.deleteAIKey(provider) : api.setAIKey(provider, key),
    onMutate: () => setOutcome(null),
    onSuccess: (request) => setPending({ ...request, sentAt: Date.now() }),
  });

  if (status.isLoading || !draft) {
    return <Card><LoadingPanel label={t("AI-tanácsadó betöltése…", "Loading the AI adviser…")} /></Card>;
  }
  if (status.isError && !pending) {
    return <Card><Notice tone="danger" title={t("Az AI-tanácsadó állapota nem olvasható", "The AI adviser state cannot be read")}>{t("Frissítsd az oldalt, vagy ellenőrizd a backend verzióját.", "Reload the page or check the backend version.")}</Notice></Card>;
  }
  const data = status.data;
  const providers = data?.providers ?? [];
  const keyManagement = data?.key_management?.available === true;
  const active = providers.find((item) => item.id === data?.provider);
  const update = (patch: Partial<AISettings>) => {
    setDraft({ ...draft, ...patch });
    setDirty(true);
  };

  return (
    <Card className="ai-adviser-panel">
      <div className="section-heading">
        <div><span className="section-heading__icon"><Sparkles size={19} /></span><div><h3>{t("AI tanácsadó", "AI adviser")}</h3><p>{t("Scan-alapú x264/x265 profiljavaslat OpenAI vagy Claude modellel", "Scan-based x264/x265 profile suggestion with an OpenAI or Claude model")}</p></div></div>
        <Badge tone={data?.configured ? "success" : "neutral"}>{data?.configured ? `${t("Használatra kész", "Ready to use")} · ${active?.label ?? ""}` : t("Nincs beállítva", "Not configured")}</Badge>
      </div>
      <p className="muted-copy">{t(
        "A javaslatot a backend újra validálja, és csak kézi alkalmazás után használja. A kulcs titkosított systemd credentialként kerül a szerverre; az oldal sosem kapja vissza.",
        "The backend validates the suggestion again and uses it only after you apply it by hand. The key is stored on the server as an encrypted systemd credential; the page never gets it back.",
      )}</p>
      {!keyManagement && (
        <Notice tone="warning" title={t("A kulcs itt nem állítható be", "The key cannot be set here")}>
          {t(
            "Ez a szerver még nem futtatja a kulcsmentő segédprogramot (régebbi telepítés vagy fejlesztői mód). Futtasd újra a telepítőt, vagy használd a README 5.2.1. pontjának parancsát.",
            "This server does not run the key helper yet (older install or developer mode). Run the installer again, or use the command in section 5.2.1 of the README.",
          )}
        </Notice>
      )}
      <label className="field ai-default-provider">
        <span>{t("Alapértelmezett szolgáltató", "Default provider")}</span>
        <select value={draft.default_provider ?? ""} onChange={(event) => update({ default_provider: (event.target.value || null) as AIProvider | null })}>
          <option value="">{t("Automatikus (az első beállított kulcs)", "Automatic (the first key set)")}</option>
          {providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <div className="ai-provider-list">
        {providers.map((provider) => (
          <ProviderRow
            key={provider.id}
            provider={provider}
            model={(provider.id === "openai" ? draft.openai_model : draft.anthropic_model) ?? ""}
            onModel={(value) => update(provider.id === "openai" ? { openai_model: value || null } : { anthropic_model: value || null })}
            keyManagement={keyManagement}
            busy={pending !== null || keyChange.isPending}
            onSetKey={(key) => keyChange.mutate({ provider: provider.id, key })}
            onDeleteKey={() => keyChange.mutate({ provider: provider.id, key: null })}
          />
        ))}
      </div>
      {pending && <Notice tone="info" title={t("Kulcs mentése folyamatban", "Saving the key")}>{t("A szerver titkosítja a kulcsot, majd az API néhány másodpercre újraindul.", "The server encrypts the key, then the API restarts for a few seconds.")}</Notice>}
      {outcome && <Notice tone={outcome.tone}>{outcome.text}</Notice>}
      {keyChange.isError && <Notice tone="danger" title={t("A kulcs nem küldhető el", "The key cannot be sent")}>{keyChange.error instanceof ApiError ? keyChange.error.detail : t("Ismeretlen hiba történt.", "An unknown error occurred.")}</Notice>}
      {saveSettings.isError && <Notice tone="danger" title={t("A beállítás nem menthető", "The setting cannot be saved")}>{saveSettings.error instanceof ApiError ? saveSettings.error.detail : t("Ismeretlen hiba történt.", "An unknown error occurred.")}</Notice>}
      <div className="ai-adviser-panel__actions">
        <Button icon={<Save size={16} />} disabled={!dirty} loading={saveSettings.isPending} onClick={() => saveSettings.mutate(draft)}>{t("Szolgáltató és modellek mentése", "Save provider and models")}</Button>
      </div>
    </Card>
  );
}
