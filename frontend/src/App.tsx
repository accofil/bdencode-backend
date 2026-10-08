import { Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { JobsPage } from "./pages/JobsPage";
import { NewEncodePage } from "./pages/NewEncodePage";
import { JobDetailPage } from "./pages/JobDetailPage";
import { ComparisonsPage } from "./pages/ComparisonsPage";
import { HelpPage } from "./pages/HelpPage";
import { StatisticsPage } from "./pages/StatisticsPage";
import { SystemPage } from "./pages/SystemPage";
import { useLanguage } from "./i18n";

export function App() {
  // Subscribing here re-renders the whole tree when the language changes.
  useLanguage();
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="new" element={<NewEncodePage />} />
        <Route path="queue" element={<JobsPage mode="queue" />} />
        <Route path="archive" element={<JobsPage mode="archive" />} />
        <Route path="jobs/:jobId" element={<JobDetailPage />} />
        <Route path="comparisons" element={<ComparisonsPage />} />
        <Route path="statistics" element={<StatisticsPage />} />
        <Route path="settings" element={<SystemPage />} />
        <Route path="help" element={<HelpPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
