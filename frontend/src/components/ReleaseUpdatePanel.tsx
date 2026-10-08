import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { t } from "../i18n";
import { formatDate } from "../utils";
import { Badge, Card, LoadingPanel, Notice } from "./ui";

type Tone = "success" | "warning" | "danger" | "neutral";

function states(): Record<string, { label: string; tone: Tone }> {
  return {
    up_to_date: { label: t("Naprakész", "Up to date"), tone: "success" },
    installed: { label: t("Frissítve", "Updated"), tone: "success" },
    update_available: { label: t("Új kiadás érhető el", "New release available"), tone: "warning" },
    manual_update_required: { label: t("Kézi telepítés kell", "Manual install needed"), tone: "warning" },
    deferred: { label: t("Halasztva", "Deferred"), tone: "neutral" },
    check_failed: { label: t("A keresés nem sikerült", "The check failed"), tone: "danger" },
    install_failed: { label: t("A telepítés nem sikerült", "The install failed"), tone: "danger" },
    blocked: { label: t("Leállítva", "Blocked"), tone: "danger" },
    invalid_release: { label: t("Érvénytelen kiadás", "Invalid release"), tone: "danger" },
  };
}

/** Outcome of the daily release check and unattended update (System page). */
export function ReleaseUpdatePanel() {
  const query = useQuery({ queryKey: ["release-update"], queryFn: api.releaseUpdate, retry: false });
  const status = query.data?.status ?? null;
  const state = status ? (states()[status.state] ?? { label: status.state, tone: "neutral" as Tone }) : null;
  return (
    <Card className="backups-panel">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><RefreshCw size={19} /></span>
          <div><h3>{t("Kiadáskeresés és frissítés", "Release check and update")}</h3><p>{t("A napi időzítő új kiadást keres, és felügyelet nélkül telepíti", "A daily timer looks for a new release and installs it unattended")}</p></div>
        </div>
        {state && <Badge tone={state.tone}>{state.label}</Badge>}
      </div>
      {query.isLoading ? <LoadingPanel label={t("Frissítési állapot lekérdezése…", "Checking the update state…")} /> : status ? (
        <>
          <dl className="summary-list">
            <div><dt>{t("Telepített", "Installed")}</dt><dd>{status.installed_version ?? "—"}</dd></div>
            <div><dt>{t("Legújabb kiadás", "Latest release")}</dt><dd>{status.latest_tag ?? "—"}</dd></div>
            <div><dt>{t("Utolsó ellenőrzés", "Last check")}</dt><dd>{formatDate(status.checked_at)}</dd></div>
            <div><dt>{t("Utolsó telepítés", "Last install")}</dt><dd>{status.installed_at ? formatDate(status.installed_at) : "—"}</dd></div>
          </dl>
          <p className="muted">{status.message}</p>
          {status.media_updates && status.media_updates.length > 0 && (
            <Notice tone="warning" title={t("Médiacsomag-frissítés vár (nem települ automatikusan)", "Media package update pending (not installed automatically)")}>
              <ul>{status.media_updates.map((item) => <li key={item}>{item}</li>)}</ul>
            </Notice>
          )}
        </>
      ) : <p className="muted">{t("Még nincs adat: az első napi ellenőrzés után jelenik meg (vagy a frissítő nincs telepítve).", "No data yet: it appears after the first daily check (or the updater is not installed).")}</p>}
      <p className="field-help">{t("Kézi indítás:", "Manual start:")} <code>sudo systemctl start bdencode-update.service</code>. {t("Egy adott kiadás (visszaállás régebbire is):", "A specific release (also to go back to an older one):")} <code>sudo /usr/local/libexec/bdencode-release-update install --tag vX.Y.Z</code>.</p>
    </Card>
  );
}
