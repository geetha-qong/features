import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./theme/ThemeContext";
import Layout from "./routes/Layout";
import Home from "./routes/Home";
import Login from "./routes/Login";
import Dashboard from "./routes/Dashboard";
import Projects from "./routes/Projects";
import ProjectDetail from "./routes/ProjectDetail";
import JobDetail from "./routes/JobDetail";
import ReviewCanvas from "./routes/ReviewCanvas";
import NotFound from "./routes/NotFound";

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
          <Route index element={<Home />} />
          {/* React sign-in screen lives at /signin so /login can be a
              pure backend proxy passthrough to FastAPI without a route
              conflict with this SPA. */}
          <Route path="signin" element={<Login />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:projectId" element={<ProjectDetail />} />
          <Route path="jobs/:jobId" element={<JobDetail />} />
          <Route path="jobs/:jobId/review" element={<ReviewCanvas />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

