import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked, Download, Save, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { t } from "../i18n";
import type {
  AutoCrfConfig,
  DetailLevel,
  DynamicHdrMode,
  LibraryImportResult,
  LibraryProfile,
  LibraryProfileSelection,
} from "../api/types";
import { downloadJson } from "../utils";
import { Badge, Button, Card, LoadingPanel, Modal, Notice } from "./ui";

/** Disc-specific or bitstream-policy fields: never part of a shared profile. */
export const NON_PORTABLE_SETTINGS = [
  "encoder",
  "detail_level",
  "profile",
  "level",
  "bit_depth",
  "pixel_format",
  "color",
  "vbv",
  "hdr10",
  "aud",
  "repeat_headers",
  "annexb",
] as const;

export function portableSettings(settings: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(settings).filter(([key]) => !(NON_PORTABLE_SETTINGS as readonly string[]).includes(key)),
  );
}

function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error(t("A fájl nem olvasható.", "The file cannot be read.")));
    reader.readAsText(file);
  });
}

function message(error: unknown): string {
  return error instanceof ApiError ? error.detail : error instanceof Error ? error.message : t("Ismeretlen hiba", "Unknown error");
}

export function ProfileLibraryPanel({
  encoder,
  detailLevel,
  settings,
  autoCrf,
  dynamicHdr,
  onApply,
}: {
  encoder: "x264" | "x265";
  detailLevel: DetailLevel;
  settings: Record<string, unknown>;
  autoCrf: AutoCrfConfig | null;
  dynamicHdr: DynamicHdrMode;
  onApply: (selection: LibraryProfileSelection, profile: LibraryProfile) => void;
}) {
  const queryClient = useQueryClient();
  const library = useQuery({ queryKey: ["profile-library"], queryFn: api.profileLibrary, retry: false });
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [applied, setApplied] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<LibraryProfile | null>(null);
  const [importResult, setImportResult] = useState<LibraryImportResult | null>(null);
  const [importMode, setImportMode] = useState<"rename" | "skip" | "overwrite">("rename");
  const [localError, setLocalError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["profile-library"] });
  const buildDocument = () => ({
    name: name.trim(),
    description: description.trim(),
    encoder,
    detail_level: detailLevel,
    settings: portableSettings(settings),
    ...(autoCrf?.enabled ? { auto_crf: autoCrf } : {}),
    ...(dynamicHdr !== "discard" ? { dynamic_hdr: dynamicHdr } : {}),
  });

  const save = useMutation({
    mutationFn: (overwrite: boolean) => api.saveLibraryProfile(buildDocument(), overwrite),
    onSuccess: () => {
      setConflict(false);
      setName("");
      setDescription("");
      refresh();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) setConflict(true);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteLibraryProfile(id),
    onSuccess: () => {
      setDeleteTarget(null);
      refresh();
    },
  });
  const importer = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.importLibraryProfiles(payload, importMode),
    onSuccess: (result) => {
      setImportResult(result);
      refresh();
    },
  });

  async function exportOne(profile: LibraryProfile) {
    try {
      downloadJson(`${profile.id}.bdencode-profile.json`, await api.exportLibraryProfile(profile.id));
    } catch (error) {
      setLocalError(message(error));
    }
  }
  async function exportAll() {
    try {
      downloadJson("bdencode-profiles.json", await api.exportLibrary());
    } catch (error) {
      setLocalError(message(error));
    }
  }
  async function readFile(file: File | undefined) {
    if (!file) return;
    setLocalError(null);
    setImportResult(null);
    try {
      const parsed: unknown = JSON.parse(await readText(file));
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error(t("A fájl nem BDEncode profil vagy profilcsomag.", "The file is not a BDEncode profile or profile bundle."));
      }
      importer.mutate(parsed as Record<string, unknown>);
    } catch (error) {
      setLocalError(error instanceof SyntaxError ? t("A fájl nem érvényes JSON.", "The file is not valid JSON.") : message(error));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const items = library.data?.items ?? [];
  const matching = items.filter((item) => item.encoder === encoder);
  const hidden = items.length - matching.length;

  return (
    <Card className="settings-card profile-library">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><BookMarked size={19} /></span>
          <div><h3>{t("Profilkönyvtár", "Profile library")}</h3><p>{t("Mentett és megosztható kódolási profilok · csak hordozható beállítások", "Saved, shareable encoding profiles · portable settings only")}</p></div>
        </div>
        <div className="profile-library__tools">
          <Button variant="ghost" icon={<Download size={16} />} onClick={() => void exportAll()} disabled={items.length === 0}>{t("Teljes export", "Export all")}</Button>
          <Button variant="ghost" icon={<Upload size={16} />} loading={importer.isPending} onClick={() => fileInput.current?.click()}>{t("Import", "Import")}</Button>
          <select value={importMode} onChange={(event) => setImportMode(event.target.value as typeof importMode)} aria-label={t("Név ütközése importnál", "Name conflict on import")}>
            <option value="rename">{t("Ütközés: átnevezés", "Conflict: rename")}</option>
            <option value="skip">{t("Ütközés: kihagyás", "Conflict: skip")}</option>
            <option value="overwrite">{t("Ütközés: felülírás", "Conflict: overwrite")}</option>
          </select>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            data-testid="profile-import-input"
            onChange={(event) => void readFile(event.target.files?.[0])}
          />
        </div>
      </div>

      {library.isLoading ? <LoadingPanel label={t("Profilok betöltése…", "Loading profiles…")} /> : library.isError ? (
        <Notice tone="warning">{t("A profilkönyvtár nem érhető el:", "The profile library is not available:")} {message(library.error)}</Notice>
      ) : matching.length === 0 ? (
        <p className="muted">{t(`Még nincs mentett ${encoder} profil. Állítsd be a kódolást, majd mentsd el lentebb.`, `No saved ${encoder} profile yet. Set up the encode, then save it below.`)}</p>
      ) : (
        <ul className="profile-library__list">
          {matching.map((profile) => (
            <li key={profile.id} className="profile-library__item">
              <div>
                <strong>{profile.name}</strong>
                <span className="profile-library__badges">
                  <Badge>{profile.detail_level}</Badge>
                  {profile.auto_crf?.enabled && <Badge tone="info">VMAF {profile.auto_crf.target_vmaf}</Badge>}
                  {profile.dynamic_hdr && profile.dynamic_hdr !== "discard" && <Badge tone="warning">{profile.dynamic_hdr}</Badge>}
                </span>
                {profile.description && <p>{profile.description}</p>}
              </div>
              <div className="profile-library__actions">
                <Button
                  variant="secondary"
                  onClick={() => {
                    onApply(profile.selection, profile);
                    setApplied(profile.name);
                  }}
                  aria-label={t(`${profile.name} alkalmazása`, `Apply ${profile.name}`)}
                >
                  {t("Alkalmaz", "Apply")}
                </Button>
                <Button variant="ghost" icon={<Download size={15} />} onClick={() => void exportOne(profile)} aria-label={t(`${profile.name} exportálása`, `Export ${profile.name}`)}>{t("Export", "Export")}</Button>
                <button type="button" className="icon-button" aria-label={t(`${profile.name} törlése`, `Delete ${profile.name}`)} onClick={() => { remove.reset(); setDeleteTarget(profile); }}>
                  <Trash2 size={15} aria-hidden="true" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {hidden > 0 && <p className="muted">{t(`${hidden} másik kodekhez tartozó profil rejtve.`, `${hidden} profile(s) for another codec hidden.`)}</p>}
      {applied && <Notice tone="success">{t(`A(z) „${applied}” profil bekerült a szerkeszthető mezőkbe. A végleges ellenőrzés továbbra is a Terv ellenőrzése lépésben történik.`, `The “${applied}” profile was loaded into the editable fields. The final check still happens at the Check plan step.`)}</Notice>}
      {localError && <Notice tone="danger">{localError}</Notice>}
      {importer.isError && <Notice tone="danger" title={t("Az import sikertelen", "Import failed")}>{message(importer.error)}</Notice>}
      {importResult && (
        <Notice tone={importResult.errors.length ? "warning" : "success"} title={t("Import eredménye", "Import result")}>
          {t(
            `${importResult.imported.length} importálva, ${importResult.skipped.length} kihagyva, ${importResult.errors.length} hibás.`,
            `${importResult.imported.length} imported, ${importResult.skipped.length} skipped, ${importResult.errors.length} failed.`,
          )}
          {importResult.errors.length > 0 && (
            <ul>{importResult.errors.map((item, index) => <li key={index}>{item.name}: {item.message}</li>)}</ul>
          )}
        </Notice>
      )}

      <form
        className="profile-library__save"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) save.mutate(false);
        }}
      >
        <label className="field">
          <span>{t("Aktuális beállítások mentése profilként", "Save the current settings as a profile")}</span>
          <input value={name} onChange={(event) => { setName(event.target.value); setConflict(false); }} placeholder={t("Profil neve", "Profile name")} maxLength={80} aria-label={t("Profil neve", "Profile name")} />
        </label>
        <label className="field">
          <span>{t("Leírás (nem kötelező)", "Description (optional)")}</span>
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder={t("Mire való?", "What is it for?")} maxLength={500} aria-label={t("Profil leírása", "Profile description")} />
        </label>
        <Button type="submit" icon={<Save size={16} />} loading={save.isPending} disabled={!name.trim()}>{t("Mentés", "Save")}</Button>
      </form>
      {save.isError && !conflict && <Notice tone="danger" title={t("A profil nem menthető", "The profile cannot be saved")}>{message(save.error)}</Notice>}
      {save.isSuccess && <Notice tone="success">{t("A profil elmentve.", "Profile saved.")}</Notice>}
      {conflict && (
        <Notice tone="warning" title={t("Már van ilyen nevű profil", "A profile with this name already exists")}>
          <Button variant="secondary" onClick={() => save.mutate(true)} loading={save.isPending}>{t("Felülírás", "Overwrite")}</Button>
        </Notice>
      )}

      <Modal
        open={deleteTarget !== null}
        title={t("Törlöd a profilt?", "Delete the profile?")}
        busy={remove.isPending}
        onClose={() => { if (!remove.isPending) setDeleteTarget(null); }}
        footer={
          <>
            <Button variant="ghost" disabled={remove.isPending} onClick={() => setDeleteTarget(null)}>{t("Mégse", "Cancel")}</Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => deleteTarget && remove.mutate(deleteTarget.id)}>{t("Törlés", "Delete")}</Button>
          </>
        }
      >
        <p>{t(`A(z) „${deleteTarget?.name ?? ""}” profil végleg törlődik a könyvtárból. A már elmentett munkák beállításait ez nem érinti.`, `The “${deleteTarget?.name ?? ""}” profile is permanently deleted from the library. Settings of jobs already saved are not affected.`)}</p>
        {remove.isError && <Notice tone="danger">{message(remove.error)}</Notice>}
      </Modal>
    </Card>
  );
}
