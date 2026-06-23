import { useCallback, useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import * as api from "./api";
import type { BillingPlan } from "./types";

export default function AdminPlans() {
  const [plans, setPlans] = useState<BillingPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listPlans();
      setPlans(data.plans);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function toggle(plan: BillingPlan) {
    setBusyId(plan.id);
    try {
      await api.togglePlan(plan.id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="projects-header">
        <div className="titlewrap">
          <span className="overline">Admin · Billing</span>
          <h1>Plans</h1>
          <p className="sub">Define the billing plans customers can purchase.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)} data-testid="plans-new">
          <Plus size={14} strokeWidth={1.6} /> New Plan
        </button>
      </div>

      {error && (
        <div
          style={{ background: "var(--error-soft)", color: "var(--error)", padding: 12, borderRadius: 8, marginBottom: 16 }}
          role="alert"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="empty-state">
          <h3>Loading…</h3>
        </div>
      ) : plans.length === 0 ? (
        <div className="empty-state">
          <h3>No plans yet</h3>
          <p>Create the first plan to start offering paid tiers.</p>
        </div>
      ) : (
        <div className="projects-list" data-testid="plans-table">
          <div className="list-head" style={{ gridTemplateColumns: "1.5fr 1fr 1fr 1fr 0.8fr" }}>
            <div>Name</div>
            <div>Credits</div>
            <div>Price</div>
            <div>Stripe</div>
            <div></div>
          </div>
          {plans.map((p) => (
            <div
              key={p.id}
              className="list-row"
              style={{ gridTemplateColumns: "1.5fr 1fr 1fr 1fr 0.8fr", cursor: "default" }}
              data-testid={`plan-row-${p.id}`}
            >
              <div className="name">{p.name}</div>
              <div className="mono">{p.credits.toLocaleString()}</div>
              <div className="mono">${(p.price_usd_cents / 100).toFixed(2)}</div>
              <div className="mono caption">{p.stripe_price_id || "—"}</div>
              <div>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={busyId === p.id}
                  onClick={() => toggle(p)}
                  data-testid={`plan-toggle-${p.id}`}
                >
                  {p.is_active ? "Active · Disable" : "Inactive · Enable"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <CreatePlanModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false);
          void refresh();
        }}
      />
    </>
  );
}

interface CreatePlanModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

function CreatePlanModal({ open, onClose, onCreated }: CreatePlanModalProps) {
  const [name, setName] = useState("");
  const [credits, setCredits] = useState("");
  const [priceUsd, setPriceUsd] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName("");
      setCredits("");
      setPriceUsd("");
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createPlan({
        name: name.trim(),
        credits: Number(credits),
        price_usd_cents: Math.round(Number(priceUsd) * 100),
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form className="modal" onSubmit={submit}>
        <div className="modal-head">
          <span className="overline">Admin · New Plan</span>
          <h2>Create Plan</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={1.6} />
          </button>
        </div>
        <div className="modal-body">
          <div className="field">
            <label className="field-label">Plan name</label>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Starter"
              required
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
            <div className="field">
              <label className="field-label">Credits</label>
              <input
                className="input"
                type="number"
                min={1}
                value={credits}
                onChange={(e) => setCredits(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label className="field-label">Price (USD)</label>
              <input
                className="input"
                type="number"
                step="0.01"
                min={0}
                value={priceUsd}
                onChange={(e) => setPriceUsd(e.target.value)}
                required
              />
            </div>
          </div>
          {error && (
            <div className="err" style={{ color: "var(--error)", fontSize: 13 }} role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!name || !credits || priceUsd === "" || submitting}
          >
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}
