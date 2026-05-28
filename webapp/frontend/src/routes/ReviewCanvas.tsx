// /jobs/:jobId/review is an alias for /jobs/:jobId (the studio) — kept so
// any deep-linked URLs from earlier placeholders continue to work.
// The actual studio component lives at routes/JobDetail.tsx.
import JobDetail from "./JobDetail";

export default function ReviewCanvas() {
  return <JobDetail />;
}
