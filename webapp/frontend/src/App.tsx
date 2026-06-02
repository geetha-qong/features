import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./theme/ThemeContext";
import RequireAuth from "./auth/RequireAuth";
import Layout from "./routes/Layout";
import Home from "./routes/Home";
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
          {/* Public surfaces */}
          <Route index element={<Home />} />
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
            <Route path="feedback" element={<Feedback />} />
            <Route path="admin" element={<AdminLayout />}>
              <Route index element={<AdminDashboard />} />
              <Route path="dashboard" element={<AdminDashboard />} />
              <Route path="users" element={<AdminUsers />} />
              <Route path="feedback" element={<AdminFeedback />} />
              <Route path="credits" element={<AdminCredits />} />
              <Route path="plans" element={<AdminPlans />} />
              <Route path="label-studio" element={<AdminLabelStudio />} />
            </Route>
          </Route>

          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

