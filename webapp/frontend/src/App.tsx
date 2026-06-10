import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./theme/ThemeContext";
import RequireAuth from "./auth/RequireAuth";
import Layout from "./routes/Layout";
import RootRedirect from "./routes/RootRedirect";
import Login from "./routes/Login";
import Dashboard from "./routes/Dashboard";
import Projects from "./routes/Projects";
import ProjectDetail from "./routes/ProjectDetail";
import JobDetail from "./routes/JobDetail";
import ReviewCanvas from "./routes/ReviewCanvas";
import Account from "./routes/Account";
import AccountApiKeys from "./routes/AccountApiKeys";
import Feedback from "./routes/Feedback";
import NotFound from "./routes/NotFound";
import AdminLayout from "./admin/AdminLayout";
import AdminUsers from "./admin/AdminUsers";
import AdminDashboard from "./admin/AdminDashboard";
import AdminFeedback from "./admin/AdminFeedback";
import AdminCredits from "./admin/AdminCredits";
import AdminPlans from "./admin/AdminPlans";
import AdminLabelStudio from "./admin/AdminLabelStudio";
import AdminCustomColumns from "./admin/AdminCustomColumns";
import AdminEntities from "./admin/AdminEntities";
// FEATURES #38 Phase 5 + 6 — marking shortcuts + annotation metrics
import AccountShortcuts from "./account/Shortcuts";
import AdminAnnotationMetrics from "./admin/AdminAnnotationMetrics";

export default function App() {
  return (
    <ThemeProvider>
      <AppRoutes />
    </ThemeProvider>
  );
}

function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          {/* No public marketing on this instance — qongsystems.com is hosted
              elsewhere. Root `/` redirects: active session → /dashboard,
              anon → /signin. RootRedirect waits for AuthContext to settle. */}
          <Route index element={<RootRedirect />} />
          {/* React sign-in screen lives at /signin so /login can be a
              pure backend proxy passthrough to FastAPI without a route
              conflict with this SPA. */}
          <Route path="signin" element={<Login />} />

          {/* Protected surfaces — RequireAuth bounces logged-out users to
              /signin?next=... before the inner routes render. */}
          <Route element={<RequireAuth />}>
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="projects" element={<Projects />} />
            <Route path="projects/:projectId" element={<ProjectDetail />} />
            <Route path="jobs/:jobId" element={<JobDetail />} />
            <Route path="jobs/:jobId/review" element={<ReviewCanvas />} />
            <Route path="account" element={<Account />} />
            <Route path="account/api-keys" element={<AccountApiKeys />} />
            <Route path="account/shortcuts" element={<AccountShortcuts />} />
            <Route path="feedback" element={<Feedback />} />
            <Route path="admin" element={<AdminLayout />}>
              <Route index element={<AdminDashboard />} />
              <Route path="dashboard" element={<AdminDashboard />} />
              <Route path="users" element={<AdminUsers />} />
              <Route path="feedback" element={<AdminFeedback />} />
              <Route path="credits" element={<AdminCredits />} />
              <Route path="plans" element={<AdminPlans />} />
              <Route path="label-studio" element={<AdminLabelStudio />} />
              <Route path="entities" element={<AdminEntities />} />
              <Route path="annotation-metrics" element={<AdminAnnotationMetrics />} />
              <Route path="custom-columns" element={<AdminCustomColumns />} />
            </Route>
          </Route>

          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

