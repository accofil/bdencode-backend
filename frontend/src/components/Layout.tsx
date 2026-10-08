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
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { cpuShareInForce, useCpuPolicy } from "./CpuPolicyPanel";

const navigation = [
  { to: "/", label: "Áttekintés", icon: Gauge, end: true },
  { to: "/new", label: "Új kódolás", icon: CirclePlus },
  { to: "/queue", label: "Várólista", icon: ListOrdered },
  { to: "/archive", label: "Elkészült munkák", icon: Archive },
  { to: "/comparisons", label: "Összehasonlítások", icon: AudioWaveform },
  { to: "/statistics", label: "Statisztika", icon: BarChart3 },
  { to: "/settings", label: "Rendszer", icon: Settings },
  { to: "/help", label: "Súgó", icon: BookOpen },
];

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
      <a className="skip-link" href="#main-content">Ugrás a tartalomhoz</a>
      <button
        type="button"
        className="mobile-menu-button"
        aria-label="Menü megnyitása"
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
            {serverVersion && <span className="brand-version" title="A szerveren futó verzió">v{serverVersion}</span>}
          </div>
          <button
            type="button"
            className="sidebar-close"
            aria-label="Menü bezárása"
            onClick={() => setMobileOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        <nav className="primary-nav" aria-label="Fő navigáció">
          {navigation.map(({ to, label, icon: Icon, end }) => (
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
            <span>{health.isSuccess ? "Szerver elérhető" : health.isError ? "Kapcsolati hiba" : "Kapcsolódás…"}</span>
          </div>
          {health.data && (
            <small>
              {health.data.active_job_id ? "1 aktív munka" : "Nincs aktív munka"} · {health.data.queued_jobs} várakozik
            </small>
          )}
          {staleInterface && (
            <div className="sidebar-update">
              <small>Ez a lap a v{__APP_VERSION__} felületét futtatja, a szerveren a v{serverVersion} van.</small>
              <button type="button" className="sidebar-update__reload" onClick={() => window.location.reload()}>
                <RefreshCw size={14} aria-hidden="true" /> Oldal frissítése
              </button>
            </div>
          )}
        </div>

        <div className="sidebar-footer">
          <Activity size={16} aria-hidden="true" />
          <span>{cpuShare ? `${cpuShare.percent}% CPU-keret${cpuShare.mode === "night" ? " · éjszakai mód" : ""}` : "CPU-védelem aktív"}</span>
        </div>
      </aside>

      {mobileOpen && <button type="button" className="sidebar-scrim" aria-label="Menü bezárása" onClick={() => setMobileOpen(false)} />}

      <main id="main-content" className="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
