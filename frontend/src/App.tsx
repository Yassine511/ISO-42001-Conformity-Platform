import { Navigate, Route, Routes, useParams } from "react-router-dom";
import HomePage from "./pages/HomePage";
import OrganizationPage from "./pages/OrganizationPage";
import ReviewWorkspacePage from "./pages/ReviewWorkspacePage";
import ChatPage from "./pages/ChatPage";
import RemediationListPage from "./pages/RemediationListPage";
import RemediationCasePage from "./pages/RemediationCasePage";
import DashboardPage from "./pages/DashboardPage";
import RiskRegisterPage from "./pages/RiskRegisterPage";
import SoaPage from "./pages/SoaPage";
import { AppShell } from "@/components/app-shell";

function LegacyDashboardRedirect() {
  const { orgId } = useParams<{ orgId: string }>();
  return <Navigate replace to={`/organizations/${orgId}`} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/organizations/:orgId" element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="dashboard" element={<LegacyDashboardRedirect />} />
        <Route path="evaluations" element={<OrganizationPage />} />
        <Route path="assessments/:assessmentId" element={<ReviewWorkspacePage />} />
        <Route path="chat/:conversationId?" element={<ChatPage />} />
        <Route path="risk-register" element={<RiskRegisterPage />} />
        <Route path="soa" element={<SoaPage />} />
        <Route path="remediation" element={<RemediationListPage />} />
        <Route path="remediation/:caseId" element={<RemediationCasePage />} />
      </Route>
    </Routes>
  );
}
