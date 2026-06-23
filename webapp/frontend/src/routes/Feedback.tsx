import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Send } from "lucide-react";
import { submitFeedback } from "../account/api";
import type { FeedbackCategory } from "../account/types";

export default function Feedback() {
  const [category, setCategory] = useState<FeedbackCategory>("bug");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!subject.trim() || !message.trim()) {
      setError("Subject and message are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await submitFeedback({
        category,
        subject: subject.trim(),
        message: message.trim(),
        page_url: document.referrer || null,
      });
      setSuccess(true);
      setSubject("");
      setMessage("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ padding: 32, maxWidth: 700, margin: "0 auto" }}>
      <Link to="/dashboard" style={{ display: "inline-flex", alignItems: "center", gap: 4, marginBottom: 12 }}>
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>
      <h1 style={{ marginTop: 0 }}>Send Feedback</h1>
      <p style={{ color: "#666" }}>
        Found a bug, want a feature, or have a billing question? Let us know.
      </p>

      {success && (
        <div style={{ background: "#e6ffe6", border: "1px solid #99cc99", color: "#040", padding: 12, borderRadius: 6, marginBottom: 16 }}>
          Thanks for your feedback! We'll review it soon.{" "}
          <button
            onClick={() => setSuccess(false)}
            style={{ marginLeft: 8, background: "transparent", border: "none", textDecoration: "underline", cursor: "pointer", color: "#040" }}
          >
            Send another
          </button>
        </div>
      )}

      {error && (
        <div style={{ background: "#fee", border: "1px solid #fbb", color: "#900", padding: 12, borderRadius: 6, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {!success && (
        <form onSubmit={onSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label htmlFor="fb-category" style={{ display: "block", marginBottom: 4, fontWeight: 600 }}>
              Category
            </label>
            <select
              id="fb-category"
              value={category}
              onChange={(e) => setCategory(e.target.value as FeedbackCategory)}
              style={{ width: "100%", padding: 8, border: "1px solid #ccc", borderRadius: 4 }}
            >
              <option value="bug">Bug</option>
              <option value="feature">Feature request</option>
              <option value="pricing">Pricing / billing</option>
              <option value="other">Other</option>
            </select>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="fb-subject" style={{ display: "block", marginBottom: 4, fontWeight: 600 }}>
              Subject
            </label>
            <input
              id="fb-subject"
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              maxLength={255}
              required
              style={{ width: "100%", padding: 8, border: "1px solid #ccc", borderRadius: 4 }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="fb-message" style={{ display: "block", marginBottom: 4, fontWeight: 600 }}>
              Message
            </label>
            <textarea
              id="fb-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={8}
              required
              style={{ width: "100%", padding: 8, border: "1px solid #ccc", borderRadius: 4, fontFamily: "inherit" }}
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !subject.trim() || !message.trim()}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "10px 20px", background: "#0070f3", color: "#fff", border: "none", borderRadius: 4 }}
          >
            <Send size={14} /> {submitting ? "Sending…" : "Send feedback"}
          </button>
        </form>
      )}
    </div>
  );
}
