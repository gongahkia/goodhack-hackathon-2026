"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowRight, CheckCircle2, ClipboardList, Loader2, Mic, NotebookPen } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { api } from "@/lib/api";
import type { CaregiverNoteResult, KgNode } from "@/lib/types";

const examples = [
  "for 28 Jan appointment, remind me to ask doc about the new lump",
  "doctor said consider wheelchair, decide by 15 June"
];

export default function CapturePage() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaregiverNoteResult | null>(null);

  async function submit() {
    const note = text.trim();
    if (!note) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await api.caregiverNote(note));
      setText("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <AppHeader title="Capture" subtitle="Save spoken care notes into the plan" />
      <main className="flex-1 space-y-4 px-4 pb-4">
        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-bold text-moss">
            <Mic className="h-4 w-4" /> Care note
          </div>
          <textarea
            className="mt-3 min-h-32 w-full resize-none rounded-lg border border-[#cbd8cf] bg-[#fbfdfb] p-3 text-sm outline-none focus:border-moss"
            onChange={(event) => setText(event.target.value)}
            placeholder="Dictate or paste a note..."
            value={text}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {examples.map((example) => (
              <button
                className="rounded-lg border border-[#dfe8e2] bg-[#f5f8f6] px-3 py-2 text-left text-xs font-semibold text-[#536159]"
                key={example}
                onClick={() => setText(example)}
                type="button"
              >
                {example}
              </button>
            ))}
          </div>
          {error ? <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
          <button
            className="mt-4 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
            disabled={busy || !text.trim()}
            onClick={submit}
            type="button"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <NotebookPen className="h-4 w-4" />}
            Save note
          </button>
        </section>

        {result ? <CaptureResult result={result} /> : null}
      </main>
      <BottomNav />
    </>
  );
}

function CaptureResult({ result }: { result: CaregiverNoteResult }) {
  const items = [...result.intents, ...(result.research_notes || []), ...(result.scheduled_actions || [])];
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-bold text-moss">
        <CheckCircle2 className="h-4 w-4" /> Saved to graph
      </div>
      {items.map((node) => (
        <ResultNode key={node.id} node={node} />
      ))}
    </section>
  );
}

function ResultNode({ node }: { node: KgNode }) {
  const title = node.payload.title || node.payload.question || node.payload.topic || node.type.replace("_", " ");
  const needsClarification = node.status === "clarification_required" || node.payload.requires_clarification;
  return (
    <article className="rounded-xl border border-[#dfe8e2] bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="inline-flex items-center gap-2 text-xs font-bold uppercase text-moss">
            {needsClarification ? <AlertCircle className="h-4 w-4 text-[#8d3d29]" /> : <ClipboardList className="h-4 w-4" />}
            {node.type.replace("_", " ")}
          </p>
          <h2 className="mt-1 font-bold text-ink">{title}</h2>
          {node.payload.clarification_reason ? <p className="mt-2 text-sm text-[#8d3d29]">{node.payload.clarification_reason}</p> : null}
          {node.payload.summary ? <p className="mt-2 text-sm text-[#536159]">{node.payload.summary}</p> : null}
        </div>
      </div>
      {node.type === "scheduled_action" ? (
        <Link className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-moss" href={`/event/${node.id}`}>
          Open action <ArrowRight className="h-4 w-4" />
        </Link>
      ) : null}
    </article>
  );
}
