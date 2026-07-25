import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { AppShell } from "@/components/app-shell";
import { RequireAuth } from "./auth";

// Route-level code splitting: each page (and its heavy deps — the remediation
// workflow, the motion layer) loads on demand instead of in one bundle.
const LandingPage = lazy(() => import("./pages/LandingPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const SignupPage = lazy(() => import("./pages/SignupPage"));
const InviteAcceptPage = lazy(() => import("./pages/InviteAcceptPage"));
const OrganizationPage = lazy(() => import("./pages/OrganizationPage"));
const ReviewWorkspacePage = lazy(() => import("./pages/ReviewWorkspacePage"));
const ChatPage = lazy(() => import("./pages/ChatPage"));
const RemediationListPage = lazy(() => import("./pages/RemediationListPage"));
const RemediationCasePage = lazy(() => import("./pages/RemediationCasePage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const RiskRegisterPage = lazy(() => import("./pages/RiskRegisterPage"));
const SoaPage = lazy(() => import("./pages/SoaPage"));

function LegacyDashboardRedirect() {
  const { orgId } = useParams<{ orgId: string }>();
  return <Navigate replace to={`/organizations/${orgId}`} />;
}

function RouteFallback() {
  return (
    <p className="p-6 text-sm text-muted-foreground" aria-live="polite">
      Chargement…
    </p>
  );
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        {/* public */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/invitation/:token" element={<InviteAcceptPage />} />

        {/* authenticated app */}
        <Route
          path="/organizations/:orgId"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
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
    </Suspense>
  );
}
