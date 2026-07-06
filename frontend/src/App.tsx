import { Link, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import OrganizationPage from "./pages/OrganizationPage";
import ReviewWorkspacePage from "./pages/ReviewWorkspacePage";
import ChatPage from "./pages/ChatPage";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            Copilote ISO/IEC 42001
          </Link>
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
            INT102 · Teamwill
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/organizations/:orgId" element={<OrganizationPage />} />
          <Route
            path="/organizations/:orgId/assessments/:assessmentId"
            element={<ReviewWorkspacePage />}
          />
          <Route path="/organizations/:orgId/chat/:conversationId?" element={<ChatPage />} />
        </Routes>
      </main>
    </div>
  );
}
