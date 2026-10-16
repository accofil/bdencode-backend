import {
  Activity,
  Archive,
  AudioWaveform,
  BarChart3,
  BookOpen,
  CirclePlus,
  Gauge,
  ListOrdered,
  Menu,
  RefreshCw,
  Settings,
  X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router";
import clsx from "clsx";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { LANGUAGES, setLanguage, t, useLanguage } from "../i18n";
import { cpuShareInForce, useCpuPolicy } from "./CpuPolicyPanel";
import type { HealthResponse } from "../api/types";
import { Notice } from "./ui";

function navigation() {
  return [
    { to: "/", label: t("Áttekintés", "Overview"), icon: Gauge, end: true },
    { to: "/new", label: t("Új kódolás", "New encode"), icon: CirclePlus },
    { to: "/queue", label: t("Várólista", "Queue"), icon: ListOrdered },
    { to: "/archive", label: t("Elkészült munkák", "Finished jobs"), icon: Archive },
    { to: "/comparisons", label: t("Összehasonlítások", "Comparisons"), icon: AudioWaveform },
    { to: "/statistics", label: t("Statisztika", "Statistics"), icon: BarChart3 },
    { to: "/settings", label: t("Rendszer", "System"), icon: Settings },
    { to: "/help", label: t("Súgó", "Help"), icon: BookOpen },
  ];
}

/** HU / EN switch; backend texts are fetched again in the new language. */
function LanguageSwitch() {
  const language = useLanguage();
  const queryClient = useQueryClient();
  return (
    <div className="language-switch" role="group" aria-label={t("Nyelv", "Language")}>
      {LANGUAGES.map((option) => (
        <button
          key={option}
          type="button"
          className={clsx("language-switch__option", option === language && "language-switch__option--active")}
          aria-pressed={option === language}
          lang={option}
          title={option === "hu" ? "Magyar" : "English"}
          onClick={() => {
            if (option === language) return;
            setLanguage(option);
            void queryClient.invalidateQueries();
          }}
        >
          {option.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

const GIB = 1024 ** 3;
/** Below this much free space a UHD encode and its work files may not fit. */
export const LOW_DISK_WARNING_BYTES = 100 * GIB;
export const LOW_DISK_CRITICAL_BYTES = 30 * GIB;

/** Problems of the host that otherwise look like a job that "does not start". */
export function HostWarnings({ health }: { health: HealthResponse | undefined }) {
  useLanguage();
  if (!health) return null;
  const waiting = health.queued_jobs + (health.ready_jobs ?? 0) + (health.active_job_id ? 1 : 0);
  const workerDown = health.worker_active === false && waiting > 0;
  const free = health.disk_free_bytes;
  const lowDisk = typeof free === "number" && free < LOW_DISK_WARNING_BYTES;
  if (!workerDown && !lowDisk) return null;
  return (
    <div className="host-warnings">
      {workerDown && (
        <Notice tone="danger" title={t("A worker szolgáltatás nem fut", "The worker service is not running")}>
          {t(
            `${waiting} munka vár, de senki nem veszi fel. A szerver pár percen belül magától újraindítja a workert; ha ez nem történik meg, a szerveren: sudo systemctl start bdencode-worker`,
            `${waiting} job(s) are waiting but nothing picks them up. The server restarts the worker by itself within a few minutes; if that does not happen, run on the server: sudo systemctl start bdencode-worker`,
          )}
        </Notice>
      )}
      {lowDisk && (
        <Notice
          tone={free < LOW_DISK_CRITICAL_BYTES ? "danger" : "warning"}
          title={free < LOW_DISK_CRITICAL_BYTES ? t("Majdnem megtelt a lemez", "The disk is almost full") : t("Kevés a szabad lemezhely", "Little free disk space")}
        >
          {t(
            `Szabad hely: ${(free / GIB).toFixed(0)} GiB. A kódolás a forrás méretének többszörösét igényli (munkafájlok, kész fájl); megtelt lemeznél a worker leáll. Törölj kész munkákat vagy bővítsd a tárhelyet.`,
            `Free space: ${(free / GIB).toFixed(0)} GiB. An encode needs several times the source size (work files, finished file); a full disk stops the worker. Delete finished jobs or add storage.`,
          )}
        </Notice>
      )}
    </div>
  );
}

export function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const cpuShare = cpuShareInForce(useCpuPolicy().data);
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 5000,
    retry: 2,
  });
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities, staleTime: 60_000 });
  const serverVersion = capabilities.data?.backend_version;
  // After an update an open tab keeps running the old interface until reloaded.
  const staleInterface = Boolean(serverVersion) && serverVersion !== __APP_VERSION__;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">{t("Ugrás a tartalomhoz", "Skip to content")}</a>
      <button
        type="button"
        className="mobile-menu-button"
        aria-label={t("Menü megnyitása", "Open menu")}
        aria-expanded={mobileOpen}
        aria-controls="primary-sidebar"
        onClick={() => setMobileOpen(true)}
      >
        <Menu size={22} aria-hidden="true" />
      </button>

      <aside id="primary-sidebar" className={clsx("sidebar", mobileOpen && "sidebar--open")}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <span />
          </span>
          <div>
            <strong>BDEncode</strong>
            <small>Studio Console</small>
            {serverVersion && <span className="brand-version" title={t("A szerveren futó verzió", "Version running on the server")}>v{serverVersion}</span>}
          </div>
          <button
            type="button"
            className="sidebar-close"
            aria-label={t("Menü bezárása", "Close menu")}
            onClick={() => setMobileOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        <nav className="primary-nav" aria-label={t("Fő navigáció", "Main navigation")}>
          {navigation().map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) => clsx("nav-link", isActive && "nav-link--active")}
            >
              <Icon size={19} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-status" role="status" aria-live="polite">
          <div className="sidebar-status__top">
            <span
              className={clsx(
                "status-dot",
                health.isSuccess ? "status-dot--online" : health.isError ? "status-dot--error" : "status-dot--pending",
              )}
              aria-hidden="true"
            />
            <span>{health.isSuccess ? t("Szerver elérhető", "Server online") : health.isError ? t("Kapcsolati hiba", "Connection error") : t("Kapcsolódás…", "Connecting…")}</span>
          </div>
          {health.data && (
            <small>
              {health.data.active_job_id ? t("1 aktív munka", "1 active job") : t("Nincs aktív munka", "No active job")} · {health.data.queued_jobs} {t("várakozik", "waiting")}
            </small>
          )}
          {staleInterface && (
            <div className="sidebar-update">
              <small>{t(`Ez a lap a v${__APP_VERSION__} felületét futtatja, a szerveren a v${serverVersion} van.`, `This tab runs the v${__APP_VERSION__} interface; the server has v${serverVersion}.`)}</small>
              <button type="button" className="sidebar-update__reload" onClick={() => window.location.reload()}>
                <RefreshCw size={14} aria-hidden="true" /> {t("Oldal frissítése", "Reload page")}
              </button>
            </div>
          )}
        </div>

        <div className="sidebar-footer">
          <Activity size={16} aria-hidden="true" />
          <span>{cpuShare ? `${cpuShare.percent}% ${t("CPU-keret", "CPU share")}${cpuShare.mode === "night" ? ` · ${t("éjszakai mód", "night mode")}` : ""}` : t("CPU-védelem aktív", "CPU limit active")}</span>
        </div>
        <LanguageSwitch />
      </aside>

      {mobileOpen && <button type="button" className="sidebar-scrim" aria-label={t("Menü bezárása", "Close menu")} onClick={() => setMobileOpen(false)} />}

      <main id="main-content" className="main-content" tabIndex={-1}>
        <HostWarnings health={health.data} />
        <Outlet />
      </main>
    </div>
  );
}
