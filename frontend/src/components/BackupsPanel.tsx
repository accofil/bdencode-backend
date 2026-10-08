import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup } from "lucide-react";
import { api, ApiError } from "../api/client";
import { t } from "../i18n";
import { formatBytes, formatDate } from "../utils";
import { Badge, Button, Card, LoadingPanel, Notice } from "./ui";

function labels(): Record<string, string> {
  return {
    scheduled: t("Ütemezett", "Scheduled"),
    manual: t("Kézi", "Manual"),
    "pre-migration": t("Migráció előtti", "Before migration"),
    "pre-restore": t("Visszaállítás előtti", "Before restore"),
  };
}

function labelText(label: string): string {
  return labels()[label.replace(/-v\d+$/, "")] ?? label;
}

/** Database health, schema history and verified backups (System page). */
export function BackupsPanel() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["database-status"], queryFn: api.databaseStatus, retry: false });
  const backups = useQuery({ queryKey: ["database-backups"], queryFn: api.backups, retry: false });
  const create = useMutation({
    mutationFn: api.createBackup,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["database-backups"] });
      void queryClient.invalidateQueries({ queryKey: ["database-status"] });
    },
  });

  const healthy = status.data?.integrity.length === 1 && status.data.integrity[0] === "ok";
  return (
    <Card className="backups-panel">
      <div className="section-heading">
        <div>
          <span className="section-heading__icon"><DatabaseBackup size={19} /></span>
          <div><h3>{t("Adatbázis és mentések", "Database and backups")}</h3><p>{t("A várólista SQLite adatbázisának állapota és ellenőrzött online mentései", "The state of the queue's SQLite database and its verified online backups")}</p></div>
        </div>
        <Button icon={<DatabaseBackup size={17} />} loading={create.isPending} onClick={() => create.mutate()}>{t("Mentés most", "Back up now")}</Button>
      </div>

      {status.isLoading ? <LoadingPanel label={t("Adatbázis állapotának lekérdezése…", "Checking the database state…")} /> : status.data ? (
        <dl className="summary-list">
          <div><dt>{t("Séma", "Schema")}</dt><dd>v{status.data.schema_version}</dd></div>
          <div><dt>{t("Méret", "Size")}</dt><dd>{formatBytes(status.data.size_bytes)}</dd></div>
          <div><dt>{t("Integritás", "Integrity")}</dt><dd><Badge tone={healthy ? "success" : "danger"}>{healthy ? t("rendben", "ok") : status.data.integrity.join("; ")}</Badge></dd></div>
          <div><dt>{t("Mentések", "Backups")}</dt><dd>{status.data.backup_count}</dd></div>
        </dl>
      ) : <Notice tone="warning">{t("Az adatbázis állapota nem olvasható.", "The database state cannot be read.")}</Notice>}

      {create.isError && <Notice tone="danger" title={t("A mentés nem sikerült", "The backup failed")}>{create.error instanceof ApiError ? create.error.detail : t("Ismeretlen hiba", "Unknown error")}</Notice>}
      {create.isSuccess && <Notice tone="success">{t("A mentés elkészült és ellenőrzött:", "The backup is done and verified:")} {create.data.name}</Notice>}

      {backups.data && backups.data.items.length > 0 && (
        <div className="table-scroll">
          <table className="stats-table">
            <thead><tr><th scope="col">{t("Időpont", "Time")}</th><th scope="col">{t("Fajta", "Kind")}</th><th scope="col">{t("Méret", "Size")}</th><th scope="col">{t("Séma", "Schema")}</th><th scope="col">{t("Munkák", "Jobs")}</th></tr></thead>
            <tbody>
              {backups.data.items.map((item) => (
                <tr key={item.name}>
                  <th scope="row">{formatDate(item.created_at)}<small>{item.name}</small></th>
                  <td>{labelText(item.label)}</td>
                  <td>{formatBytes(item.size_bytes)}</td>
                  <td>{item.schema_version == null ? "—" : `v${item.schema_version}`}</td>
                  <td>{item.jobs ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {backups.data && backups.data.items.length === 0 && <p className="muted">{t("Még nincs mentés. Az ütemezett mentés a worker üresjáratában készül; a „Mentés most” azonnal ír egyet.", "No backup yet. The scheduled backup runs while the worker is idle; “Back up now” writes one immediately.")}</p>}

      {status.data && status.data.migrations.length > 0 && (
        <details className="metric-details">
          <summary>{t("Séma-előzmények", "Schema history")}</summary>
          <ul className="migration-list">
            {status.data.migrations.map((item) => (
              <li key={item.id}>
                {formatDate(item.applied_at)} · {item.kind === "create" ? t(`létrehozva v${item.to_version}`, `created v${item.to_version}`) : t(`migráció v${item.from_version} → v${item.to_version}`, `migration v${item.from_version} → v${item.to_version}`)}
                {item.backup_name ? t(` · mentés: ${item.backup_name}`, ` · backup: ${item.backup_name}`) : ""}
                {item.app_version ? ` · BDEncode ${item.app_version}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="field-help">{t("A visszaállítás szándékosan csak parancssorból lehetséges", "Restoring is deliberately possible only from the command line")} (<code>bdencode db-restore</code>), {t("leállított szolgáltatásokkal.", "with the services stopped.")}</p>
    </Card>
  );
}
