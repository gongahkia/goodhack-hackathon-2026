"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ClipboardCheck, Save } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { HumanEvalWorkflow, KgNode } from "@/lib/types";

type Scores = {
  provenance_score: number;
  reasoning_score: number;
  appropriateness_score: number;
  burden_score: number;
  notes: string;
};

const defaultScores: Scores = {
  provenance_score: 4,
  reasoning_score: 4,
  appropriateness_score: 4,
  burden_score: 3,
  notes: ""
};

export default function HumanEvalPage() {
  const { dateLocale } = useI18n();
  const [workflow, setWorkflow] = useState<HumanEvalWorkflow | null>(null);
  const [scores, setScores] = useState<Record<string, Scores>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    setWorkflow(await api.humanEval());
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  function scoreFor(actionId: string) {
    return scores[actionId] || defaultScores;
  }

  function updateScore(actionId: string, patch: Partial<Scores>) {
    setScores((current) => ({ ...current, [actionId]: { ...scoreFor(actionId), ...patch } }));
  }

  async function submit(action: KgNode) {
    setBusy(action.id);
    try {
      const current = scoreFor(action.id);
      await api.submitHumanEval({
        action_id: action.id,
        reviewer_role: "clinician",
        ...current,
        notes: current.notes || undefined
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <AppHeader title="Human eval" subtitle="Clinician-style grading for care-plan decisions" />
      <section className="flex-1 space-y-4 px-4 pb-28">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="h-5 w-5 text-moss" />
            <h2 className="font-bold">Evaluation coverage</h2>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center">
            <Metric label="Actions" value={workflow?.automated?.action_count ?? 0} />
            <Metric label="Reviewed" value={workflow?.automated?.human_reviewed_action_count ?? 0} />
            <Metric label="Ungrounded" value={workflow?.automated?.ungrounded_action_count ?? 0} />
          </div>
        </section>

        {(workflow?.queue || []).length === 0 ? (
          <p className="rounded-lg bg-white p-4 text-sm text-[#66726a]">All active care actions have a human evaluation.</p>
        ) : null}

        {(workflow?.queue || []).map((action) => (
          <article className="rounded-xl border border-[#dfe8e2] bg-white p-4" key={action.id}>
            <p className="text-xs font-bold uppercase text-moss">{action.payload.action_type || "care action"}</p>
            <h2 className="mt-1 text-lg font-bold text-ink">{action.payload.title}</h2>
            <p className="mt-1 text-sm text-[#66726a]">{formatDate(action.payload.start_at, dateLocale)}</p>
            {action.payload.description ? <p className="mt-3 text-sm text-[#34423a]">{action.payload.description}</p> : null}
            <div className="mt-4 grid gap-3">
              <ScoreInput label="Provenance" value={scoreFor(action.id).provenance_score} onChange={(value) => updateScore(action.id, { provenance_score: value })} />
              <ScoreInput label="Reasoning" value={scoreFor(action.id).reasoning_score} onChange={(value) => updateScore(action.id, { reasoning_score: value })} />
              <ScoreInput label="Appropriate" value={scoreFor(action.id).appropriateness_score} onChange={(value) => updateScore(action.id, { appropriateness_score: value })} />
              <ScoreInput label="Burden" value={scoreFor(action.id).burden_score} onChange={(value) => updateScore(action.id, { burden_score: value })} />
              <textarea
                className="min-h-20 resize-none rounded-lg border border-[#cbd8cf] bg-[#fbfdfb] px-3 py-2 text-sm outline-none focus:border-moss"
                onChange={(event) => updateScore(action.id, { notes: event.target.value })}
                placeholder="Clinician notes..."
                value={scoreFor(action.id).notes}
              />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button onClick={() => submit(action)} disabled={busy === action.id}>
                <Save className="h-4 w-4" /> Save grade
              </Button>
              <Link className="inline-flex min-h-10 items-center justify-center rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss" href={`/event/${action.id}`}>
                Open action
              </Link>
            </div>
          </article>
        ))}
      </section>
      <BottomNav />
    </>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-[#f5f8f6] px-3 py-2">
      <span className="block text-lg font-black text-ink">{value}</span>
      <span className="mt-0.5 block text-[11px] font-bold text-[#66726a]">{label}</span>
    </div>
  );
}

function ScoreInput({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="grid grid-cols-[7rem_1fr_2rem] items-center gap-2 text-sm font-semibold text-[#34423a]">
      <span>{label}</span>
      <input min={1} max={5} step={1} type="range" value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <span className="text-right font-black text-moss">{value}</span>
    </label>
  );
}
