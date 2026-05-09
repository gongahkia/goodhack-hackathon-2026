"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowRight, CheckCircle2, ClipboardList, Loader2, Mic, NotebookPen, Save, Square } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { api } from "@/lib/api";
import type { CaregiverNoteResult, KgNode } from "@/lib/types";

const examples = [
  "for 28 Jan appointment, remind me to ask doc about the new lump",
  "doctor said consider wheelchair, decide by 15 June"
];

type BrowserSpeechRecognition = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onresult: ((event: SpeechRecognitionResultEvent) => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionResultEvent = {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string; confidence: number };
  }>;
};

type SpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

export default function CapturePage() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaregiverNoteResult | null>(null);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcriptMeta, setTranscriptMeta] = useState<string | null>(null);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const baseTextRef = useRef("");

  useEffect(() => {
    const speechWindow = window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    };
    setSpeechSupported(Boolean(speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition));
    return () => recognitionRef.current?.stop();
  }, []);

  function startListening() {
    const speechWindow = window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    };
    const Recognition = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      setError("Speech recognition is not available in this browser. Use Chrome, Edge, or Safari, or paste the note.");
      return;
    }
    recognitionRef.current?.stop();
    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.lang = "en-SG";
    baseTextRef.current = text.trim();
    recognition.onstart = () => {
      setListening(true);
      setTranscriptMeta("Listening in English (Singapore).");
    };
    recognition.onerror = (event) => {
      setError(`Microphone transcription failed${event.error ? `: ${event.error}` : "."}`);
      setListening(false);
    };
    recognition.onend = () => setListening(false);
    recognition.onresult = (event) => {
      let transcript = "";
      let bestConfidence = 0;
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const resultItem = event.results[index];
        transcript += resultItem[0].transcript;
        bestConfidence = Math.max(bestConfidence, resultItem[0].confidence || 0);
      }
      setText([baseTextRef.current, transcript.trim()].filter(Boolean).join(" "));
      if (bestConfidence > 0) {
        setTranscriptMeta(`Transcribing with browser speech model · confidence ${Math.round(bestConfidence * 100)}%`);
      }
    };
    recognitionRef.current = recognition;
    recognition.start();
  }

  function stopListening() {
    recognitionRef.current?.stop();
    setListening(false);
  }

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
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss disabled:opacity-60"
              disabled={!speechSupported || listening}
              onClick={startListening}
              type="button"
            >
              <Mic className="h-4 w-4" /> Start mic
            </button>
            <button
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss disabled:opacity-60"
              disabled={!listening}
              onClick={stopListening}
              type="button"
            >
              <Square className="h-4 w-4" /> Stop
            </button>
          </div>
          <p className="mt-2 text-xs text-[#66726a]">
            {speechSupported ? transcriptMeta || "Uses the browser's built-in speech recognition model. No app API key is required." : "Mic transcription is not supported in this browser; typed capture still works."}
          </p>
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
  const [noteText, setNoteText] = useState(String(result.note.payload.text || ""));
  const [savedTranscript, setSavedTranscript] = useState(false);

  async function saveTranscript() {
    await api.editNode(result.note.id, { text: noteText });
    setSavedTranscript(true);
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-bold text-moss">
        <CheckCircle2 className="h-4 w-4" /> Saved to graph
      </div>
      <article className="rounded-xl border border-[#dfe8e2] bg-white p-4">
        <p className="text-xs font-bold uppercase text-moss">Transcript correction</p>
        <textarea
          className="mt-2 min-h-20 w-full resize-none rounded-lg border border-[#cbd8cf] bg-[#fbfdfb] p-3 text-sm outline-none focus:border-moss"
          onChange={(event) => {
            setNoteText(event.target.value);
            setSavedTranscript(false);
          }}
          value={noteText}
        />
        <button
          className="mt-3 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss"
          onClick={saveTranscript}
          type="button"
        >
          <Save className="h-4 w-4" /> {savedTranscript ? "Saved" : "Save transcript"}
        </button>
      </article>
      {items.map((node) => (
        <ResultNode key={node.id} node={node} />
      ))}
    </section>
  );
}

function ResultNode({ node }: { node: KgNode }) {
  const editable = node.type === "care_intent" || node.type === "decision_forecast";
  const [correction, setCorrection] = useState(correctionDefaults(node));
  const [saved, setSaved] = useState(false);
  const title = node.payload.title || node.payload.question || node.payload.topic || node.type.replace("_", " ");
  const needsClarification = node.status === "clarification_required" || node.payload.requires_clarification;

  async function saveCorrection() {
    await api.editNode(node.id, cleanCorrection(correction));
    setSaved(true);
  }

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
      {editable ? (
        <div className="mt-4 grid gap-2 rounded-lg border border-[#dfe8e2] bg-[#fbfdfb] p-3">
          <p className="text-xs font-bold uppercase text-moss">Correct interpretation</p>
          <input
            className="min-h-10 rounded-lg border border-[#cbd8cf] bg-white px-3 text-sm outline-none focus:border-moss"
            onChange={(event) => {
              setCorrection((current) => ({ ...current, topic: event.target.value }));
              setSaved(false);
            }}
            placeholder={node.type === "care_intent" ? "Question or topic" : "Decision topic"}
            value={correction.topic}
          />
          <input
            className="min-h-10 rounded-lg border border-[#cbd8cf] bg-white px-3 text-sm outline-none focus:border-moss"
            onChange={(event) => {
              setCorrection((current) => ({ ...current, date: event.target.value }));
              setSaved(false);
            }}
            placeholder="Date or deadline"
            value={correction.date}
          />
          <button
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss"
            onClick={saveCorrection}
            type="button"
          >
            <Save className="h-4 w-4" /> {saved ? "Saved" : "Save correction"}
          </button>
        </div>
      ) : null}
      {node.type === "scheduled_action" ? (
        <Link className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-moss" href={`/event/${node.id}`}>
          Open action <ArrowRight className="h-4 w-4" />
        </Link>
      ) : null}
    </article>
  );
}

function correctionDefaults(node: KgNode) {
  return {
    topic: String(node.payload.question || node.payload.topic || node.payload.normalized?.topic || ""),
    date: String(node.payload.target_date || node.payload.decision_due_at || node.payload.normalized?.target_date || "")
  };
}

function cleanCorrection(correction: { topic: string; date: string }) {
  const payload: Record<string, string> = {};
  if (correction.topic.trim()) {
    payload.topic = correction.topic.trim();
    payload.question = correction.topic.trim();
  }
  if (correction.date.trim()) {
    payload.target_date = correction.date.trim();
    payload.decision_due_at = correction.date.trim();
  }
  return payload;
}
