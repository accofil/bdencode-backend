import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Clapperboard,
  Disc3,
  Film,
  Folder,
  FolderOpen,
  GraduationCap,
  HardDrive,
  Layers3,
  Music2,
  RefreshCw,
  Search,
  Sparkles,
  Tv2,
  UploadCloud,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { api, ApiError } from "../api/client";
import type { ContentType, DetailLevel, DiscType, ImageUploadProvider, SourceEntry, UploadImageSet } from "../api/types";
import { Badge, Button, Card, LoadingPanel, Notice, PageHeader } from "../components/ui";
import { t, useLanguage } from "../i18n";
import { IMAGE_UPLOAD_PROVIDER_LABELS, UPLOAD_IMAGE_SET_LABELS, uploadImageSet } from "../uploads";
import { basename, contentLabel } from "../utils";

interface Draft {
  sourcePath: string;
  sourceName: string;
  name: string;
  discType: DiscType;
  contentType: ContentType;
  detailLevel: DetailLevel;
  uploadImages: boolean;
  imageUploadProvider: ImageUploadProvider;
  uploadImageSet: UploadImageSet;
}

const defaultDraft: Draft = {
  sourcePath: "",
  sourceName: "",
  name: "",
  discType: "AUTO",
  contentType: "FILM",
  detailLevel: "beginner",
  uploadImages: true,
  imageUploadProvider: "auto",
  uploadImageSet: "all",
};

function contentOptions() {
  return [
    { value: "FILM" as const, icon: Film, title: "Film", description: t("Egy vagy több filmváltozat, fejezetekkel.", "One or more cuts of the film, with chapters.") },
    { value: "CONCERT" as const, icon: Music2, title: t("Koncert", "Concert"), description: t("Zene- és dinamikaérzékeny hangkezelés.", "Audio handling tuned for music and dynamics.") },
    { value: "ANIME" as const, icon: Sparkles, title: "Anime", description: t("Animációhoz hangolt pszichovizuális profil.", "Psychovisual profile tuned for animation.") },
    { value: "SERIES" as const, icon: Tv2, title: t("Sorozatlemez", "Series disc"), description: t("Epizódok és playlist-csoportok kezelése.", "Handles episodes and playlist groups.") },
  ];
}

function detailOptions() {
  return [
    { value: "beginner" as const, icon: GraduationCap, title: t("Kezdő", "Beginner"), description: t("A rendszer ajánl, neked csak a fontos döntéseket kell meghoznod.", "The system recommends; you only make the important decisions.") },
    { value: "advanced" as const, icon: Wrench, title: t("Haladó", "Advanced"), description: t("CRF, preset, GOP, AQ és a fontosabb képi paraméterek.", "CRF, preset, GOP, AQ and the main picture parameters.") },
    { value: "pro" as const, icon: Layers3, title: t("Profi", "Pro"), description: t("Minden támogatott x264/x265 paraméter, csoportosítva.", "Every supported x264/x265 parameter, grouped.") },
  ];
}

function loadDraft(): Draft {
  try {
    const stored = localStorage.getItem("bdencode:new-job-draft");
    if (!stored) return defaultDraft;
    const parsed = JSON.parse(stored) as unknown;
    if (!parsed || typeof parsed !== "object") return defaultDraft;
    const value = parsed as Record<string, unknown>;
    const discType = value.discType === "BD" || value.discType === "UHD" || value.discType === "AUTO"
      ? value.discType
      : defaultDraft.discType;
    const contentType = value.contentType === "CONCERT" || value.contentType === "ANIME" || value.contentType === "SERIES" || value.contentType === "FILM"
      ? value.contentType
      : defaultDraft.contentType;
    const detailLevel = value.detailLevel === "advanced" || value.detailLevel === "pro" || value.detailLevel === "beginner"
      ? value.detailLevel
      : defaultDraft.detailLevel;
    const imageUploadProvider = value.imageUploadProvider === "imgbb" || value.imageUploadProvider === "catbox" || value.imageUploadProvider === "freeimage"
      ? value.imageUploadProvider
      : "auto";
    return {
      sourcePath: typeof value.sourcePath === "string" ? value.sourcePath : "",
      sourceName: typeof value.sourceName === "string" ? value.sourceName : "",
      name: typeof value.name === "string" ? value.name : "",
      discType,
      contentType,
      detailLevel,
      uploadImages: typeof value.uploadImages === "boolean" ? value.uploadImages : true,
      imageUploadProvider,
      uploadImageSet: uploadImageSet(value.uploadImageSet),
    };
  } catch {
    return defaultDraft;
  }
}

export function NewEncodePage() {
  const [step, setStep] = useState(1);
  const [browsePath, setBrowsePath] = useState<string | undefined>();
  const [folderFilter, setFolderFilter] = useState("");
  const [draft, setDraft] = useState<Draft>(loadDraft);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useLanguage();

  useEffect(() => {
    try {
      localStorage.setItem("bdencode:new-job-draft", JSON.stringify(draft));
    } catch {
      // A böngésző letilthatja vagy megtöltheti a helyi tárhelyet; a varázsló ettől még használható.
    }
  }, [draft]);

  const sources = useQuery({
    queryKey: ["sources", browsePath ?? "root"],
    queryFn: () => api.sources(browsePath),
  });

  const create = useMutation({
    mutationFn: () => api.createJob({
      source_path: draft.sourcePath,
      name: draft.name.trim() || draft.sourceName,
      disc_type: draft.discType,
      content_type: draft.contentType,
      priority: 0,
      settings: {
        detail_level: draft.detailLevel,
        upload_images: draft.uploadImages,
        image_upload_provider: draft.imageUploadProvider,
        upload_image_set: draft.uploadImageSet,
      },
    }),
    onSuccess: (job) => {
      try {
        localStorage.removeItem("bdencode:new-job-draft");
      } catch {
        // A kész munka szerveroldalon már létrejött, a navigáció folytatható.
      }
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate(`/jobs/${job.id}`, { state: { newlyCreated: true } });
    },
  });

  const entries = useMemo(() => {
    const needle = folderFilter.trim().toLocaleLowerCase("hu");
    const values = sources.data?.entries ?? [];
    return needle ? values.filter((entry) => entry.name.toLocaleLowerCase("hu").includes(needle)) : values;
  }, [folderFilter, sources.data]);

  const root = sources.data?.roots.find((value) => (sources.data?.path ?? "").startsWith(value)) ?? sources.data?.roots[0];
  const breadcrumbs = useMemo(() => {
    const current = sources.data?.path;
    if (!current || !root) return [];
    const relative = current.slice(root.length).replace(/^[/\\]+/, "");
    const parts = relative ? relative.split(/[/\\]+/) : [];
    return [{ label: basename(root), path: root }, ...parts.map((part, index) => ({
      label: part,
      path: `${root}/${parts.slice(0, index + 1).join("/")}`,
    }))];
  }, [root, sources.data?.path]);

  function chooseSource(entry: SourceEntry) {
    setDraft((value) => ({
      ...value,
      sourcePath: entry.path,
      sourceName: entry.name,
      // The name follows the chosen disc until the operator types their own.
      name: !value.name.trim() || value.name === value.sourceName ? entry.name : value.name,
    }));
  }

  const stepTitle = step === 1
    ? t("Forrás kiválasztása", "Choose the source")
    : step === 2 ? t("Tartalom megadása", "Describe the content") : t("Munkamód és ellenőrzés", "Mode and review");
  const canContinue = step === 1 ? Boolean(draft.sourcePath) : step === 2 ? Boolean(draft.name.trim()) : true;

  return (
    <div className="page page--wizard">
      <PageHeader
        eyebrow={t("Új kódolás", "New encode")}
        title={stepTitle}
        description={t(
          "A lemez először biztonságos, írásmentes scanen megy át, ez egy futó encode mellett is elkészülhet. Kódolás csak a későbbi beállítás-jóváhagyás és a sorra kerülés után indul.",
          "The disc first goes through a safe, read-only scan, which can run alongside an encode in progress. Encoding starts only after you approve the settings and the job reaches the front of the queue.",
        )}
      />

      <div className="wizard-steps" aria-label={t("Lépések", "Steps")}>
        {[t("Forrás", "Source"), t("Tartalom", "Content"), t("Munkamód", "Mode")].map((label, index) => (
          <button
            type="button"
            key={label}
            className={index + 1 === step ? "wizard-step wizard-step--active" : index + 1 < step ? "wizard-step wizard-step--complete" : "wizard-step"}
            onClick={() => index + 1 < step && setStep(index + 1)}
            disabled={index + 1 > step}
            aria-current={index + 1 === step ? "step" : undefined}
          >
            <span>{index + 1 < step ? <Check size={15} /> : index + 1}</span>
            {label}
          </button>
        ))}
      </div>

      {step === 1 && (
        <Card className="wizard-panel source-browser">
          <div className="source-browser__header">
            <div>
              <span className="eyebrow">{t("Szerver tárhely", "Server storage")}</span>
              <h2>{t("Válassz BDMV-forrást", "Choose a BDMV source")}</h2>
            </div>
            <Button variant="ghost" icon={<RefreshCw size={16} />} onClick={() => void sources.refetch()} loading={sources.isFetching}>{t("Frissítés", "Refresh")}</Button>
          </div>

          <div className="source-browser__toolbar">
            <nav className="breadcrumbs" aria-label={t("Mappaútvonal", "Folder path")}>
              {breadcrumbs.map((item, index) => (
                <button type="button" key={item.path} onClick={() => setBrowsePath(item.path)}>
                  {index === 0 && <HardDriveIcon />}{item.label}
                </button>
              ))}
            </nav>
            <label className="search-field search-field--small">
              <Search size={16} aria-hidden="true" /><input aria-label={t("Mappa keresése", "Search folders")} value={folderFilter} onChange={(event) => setFolderFilter(event.target.value)} placeholder={t("Mappa keresése…", "Search folders…")} />
            </label>
          </div>

          {sources.isLoading ? <LoadingPanel label={t("Mappák beolvasása…", "Reading folders…")} /> : sources.isError ? (
            <Notice tone="danger" title={t("A tárhely nem olvasható", "The storage cannot be read")}>{sources.error instanceof Error ? sources.error.message : t("Ismeretlen kapcsolati hiba", "Unknown connection error")}</Notice>
          ) : (
            <div className="folder-grid">
              {entries.map((entry) => (
                <div key={entry.path} className={draft.sourcePath === entry.path ? "folder-tile folder-tile--selected" : "folder-tile"}>
                  <button type="button" className="folder-tile__open" onClick={() => entry.is_bluray ? chooseSource(entry) : setBrowsePath(entry.path)}>
                    <span className="folder-tile__icon">{entry.is_bluray ? <Disc3 size={25} /> : <Folder size={25} />}</span>
                    <span><strong>{entry.name}</strong><small>{entry.is_bluray ? t("Blu-ray forrás", "Blu-ray source") : t("Mappa", "Folder")}</small></span>
                  </button>
                  {entry.is_bluray && (
                    <button type="button" className="folder-tile__select" onClick={() => chooseSource(entry)} aria-label={t(`${entry.name} kiválasztása`, `Select ${entry.name}`)}>
                      {draft.sourcePath === entry.path ? <Check size={17} /> : t("Kiválasztás", "Select")}
                    </button>
                  )}
                  {!entry.is_bluray && <button type="button" className="folder-tile__chevron" onClick={() => setBrowsePath(entry.path)} aria-label={t(`${entry.name} megnyitása`, `Open ${entry.name}`)}><ArrowRight size={17} aria-hidden="true" /></button>}
                </div>
              ))}
              {!entries.length && <div className="folder-empty"><FolderOpen size={25} /><span>{t("Ebben a mappában nincs további könyvtár.", "This folder has no further subfolders.")}</span></div>}
            </div>
          )}

          {draft.sourcePath && (
            <div className="selected-source">
              <Check size={18} />
              <div><strong>{draft.sourceName}</strong><span>{draft.sourcePath}</span></div>
              <Badge tone="success">{t("Kiválasztva", "Selected")}</Badge>
              <button type="button" className="selected-source__clear" onClick={() => setDraft((value) => ({ ...value, sourcePath: "", sourceName: "", name: value.name === value.sourceName ? "" : value.name }))} aria-label={t("Kijelölés törlése", "Clear the selection")}><X size={16} aria-hidden="true" /></button>
            </div>
          )}
        </Card>
      )}

      {step === 2 && (
        <div className="wizard-content-grid">
          <Card className="wizard-panel">
            <span className="eyebrow">{t("Elnevezés", "Naming")}</span>
            <h2>{t("Hogyan jelenjen meg?", "How should it appear?")}</h2>
            <label className="field">
              <span>{t("Munka neve", "Job name")}</span>
              <input value={draft.name} onChange={(event) => setDraft((value) => ({ ...value, name: event.target.value }))} maxLength={255} placeholder={t("Például: A film címe (2024)", "For example: Film Title (2024)")} autoFocus />
              <small>{t("Az MKV végleges fájlnevét a playlist kiválasztásakor még módosíthatod.", "You can still change the final MKV file name when you choose the playlist.")}</small>
            </label>
            <div className="field">
              <span>{t("Lemeztípus", "Disc type")}</span>
              <div className="segmented-control" role="group" aria-label={t("Lemeztípus", "Disc type")}>
                {(["AUTO", "BD", "UHD"] as DiscType[]).map((value) => (
                  <button type="button" key={value} className={draft.discType === value ? "active" : ""} aria-pressed={draft.discType === value} onClick={() => setDraft((draftValue) => ({ ...draftValue, discType: value }))}>
                    {value === "AUTO" ? t("Automatikus", "Automatic") : value}
                  </button>
                ))}
              </div>
              <small>{t("Az automatikus felismerés az ajánlott; UHD esetén x265 lesz a kimenet.", "Automatic detection is recommended; a UHD disc is encoded with x265.")}</small>
            </div>
          </Card>

          <Card className="wizard-panel wizard-panel--wide">
            <span className="eyebrow">{t("Tartalomtípus", "Content type")}</span>
            <h2>{t("Mi található a lemezen?", "What is on the disc?")}</h2>
            <div className="choice-grid choice-grid--content" role="group" aria-label={t("Tartalomtípus", "Content type")}>
              {contentOptions().map(({ value, icon: Icon, title, description }) => (
                <button type="button" key={value} className={draft.contentType === value ? "choice-card choice-card--selected" : "choice-card"} aria-pressed={draft.contentType === value} onClick={() => setDraft((draftValue) => ({ ...draftValue, contentType: value }))}>
                  <span className="choice-card__icon"><Icon size={23} /></span>
                  <span><strong>{title}</strong><small>{description}</small></span>
                  <span className="choice-card__check">{draft.contentType === value && <Check size={15} />}</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      )}

      {step === 3 && (
        <div className="wizard-content-grid">
          <Card className="wizard-panel wizard-panel--wide">
            <span className="eyebrow">{t("Részletesség", "Detail level")}</span>
            <h2>{t("Mennyi beállítást szeretnél látni?", "How many settings do you want to see?")}</h2>
            <div className="choice-grid choice-grid--detail" role="group" aria-label={t("Beállítások részletessége", "Settings detail level")}>
              {detailOptions().map(({ value, icon: Icon, title, description }) => (
                <button type="button" key={value} className={draft.detailLevel === value ? "choice-card choice-card--selected" : "choice-card"} aria-pressed={draft.detailLevel === value} onClick={() => setDraft((draftValue) => ({ ...draftValue, detailLevel: value }))}>
                  <span className="choice-card__icon"><Icon size={23} /></span>
                  <span><strong>{title}</strong><small>{description}</small></span>
                  <span className="choice-card__check">{draft.detailLevel === value && <Check size={15} />}</span>
                </button>
              ))}
            </div>

            <label className="toggle-row">
              <span className="toggle-row__icon"><UploadCloud size={20} /></span>
              <span><strong>{t("Comparison képek feltöltése", "Upload comparison images")}</strong><small>{t("Az I/P/B framek és spektrumképek az általad választott, ellenőrzött képtárhelyre kerülnek, BBCode-dal együtt.", "The I/P/B frames and spectrum images go to the verified image host you choose, together with BBCode.")}</small></span>
              <input type="checkbox" checked={draft.uploadImages} onChange={(event) => setDraft((value) => ({ ...value, uploadImages: event.target.checked }))} />
              <span className="toggle" aria-hidden="true" />
            </label>
            <label className="field">
              <span>{t("Képtárhely", "Image host")}</span>
              <select aria-label={t("Képtárhely", "Image host")} value={draft.imageUploadProvider} disabled={!draft.uploadImages} onChange={(event) => setDraft((value) => ({ ...value, imageUploadProvider: event.target.value as ImageUploadProvider }))}>
                {Object.entries(IMAGE_UPLOAD_PROVIDER_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
              <small>{t("Kézi választásnál a rendszer nem vált át másik szolgáltatóra.", "With a manual choice the system does not fall back to another provider.")}</small>
            </label>
            <label className="field">
              <span>{t("Feltöltött képek", "Uploaded images")}</span>
              <select aria-label={t("Feltöltött képek köre", "Set of uploaded images")} value={draft.uploadImageSet} disabled={!draft.uploadImages} onChange={(event) => setDraft((value) => ({ ...value, uploadImageSet: event.target.value as UploadImageSet }))}>
                {Object.entries(UPLOAD_IMAGE_SET_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
              <small>{t("HDR-filmnél az egyik nézet elhagyása felezi a feltöltendő képek számát.", "For an HDR film, leaving out one view halves the number of images to upload.")}</small>
            </label>
          </Card>

          <Card className="review-card">
            <span className="eyebrow">{t("Összegzés", "Summary")}</span>
            <h2>{t("Scan indítása", "Start the scan")}</h2>
            <dl className="summary-list">
              <div><dt>{t("Forrás", "Source")}</dt><dd>{draft.sourceName}</dd></div>
              <div><dt>{t("Név", "Name")}</dt><dd>{draft.name}</dd></div>
              <div><dt>{t("Tartalom", "Content")}</dt><dd>{contentLabel(draft.contentType)}</dd></div>
              <div><dt>{t("Lemez", "Disc")}</dt><dd>{draft.discType === "AUTO" ? t("Automatikus felismerés", "Automatic detection") : draft.discType}</dd></div>
              <div><dt>{t("Nézet", "View")}</dt><dd>{detailOptions().find((item) => item.value === draft.detailLevel)?.title}</dd></div>
              <div><dt>{t("Képfeltöltés", "Image upload")}</dt><dd>{draft.uploadImages ? `${IMAGE_UPLOAD_PROVIDER_LABELS[draft.imageUploadProvider]} · ${UPLOAD_IMAGE_SET_LABELS[draft.uploadImageSet]}` : t("Kikapcsolva", "Off")}</dd></div>
            </dl>
            <Notice tone="info">{t(
              "A scan nem módosítja a forrást, és a futó encode-ot sem állítja le. A playlistet, sávokat és videóbeállításokat az eredmény után hagyod jóvá; ezután a munka kész paraméterekkel kerül a kódolási sorba.",
              "The scan does not modify the source and does not stop a running encode. You approve the playlist, tracks and video settings after the result; the job then enters the encode queue with its parameters set.",
            )}</Notice>
            {create.isError && <Notice tone="danger" title={t("A munka nem hozható létre", "The job could not be created")}>{create.error instanceof ApiError ? create.error.detail : create.error.message}</Notice>}
          </Card>
        </div>
      )}

      <div className="wizard-footer">
        <Button variant="ghost" icon={<ArrowLeft size={17} />} onClick={() => step === 1 ? navigate(-1) : setStep((value) => value - 1)}>
          {step === 1 ? t("Mégse", "Cancel") : t("Vissza", "Back")}
        </Button>
        {step < 3 ? (
          <Button icon={<ArrowRight size={17} />} onClick={() => setStep((value) => value + 1)} disabled={!canContinue}>{t("Tovább", "Next")}</Button>
        ) : (
          <Button icon={<Clapperboard size={18} />} onClick={() => create.mutate()} loading={create.isPending}>{t("Munka létrehozása és scan", "Create job and scan")}</Button>
        )}
      </div>
    </div>
  );
}

function HardDriveIcon() {
  return <HardDrive size={14} aria-hidden="true" />;
}
