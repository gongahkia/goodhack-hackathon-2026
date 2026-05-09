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

export default function CapturePage() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaregiverNoteResult | null>(null);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [transcriptMeta, setTranscriptMeta] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const baseTextRef = useRef("");

  useEffect(() => {
    setSpeechSupported(Boolean(typeof navigator.mediaDevices?.getUserMedia === "function"));
    return () => {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function startListening() {
    try {
      setError(null);
      chunksRef.current = [];
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      baseTextRef.current = text.trim();
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstart = () => {
        setListening(true);
        setTranscriptMeta("Recording. Transcription starts when you stop.");
      };
      recorder.onerror = () => {
        setError("Microphone recording failed. Check browser microphone permission.");
        setListening(false);
      };
      recorder.onstop = async () => {
        setListening(false);
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        const audio = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        if (audio.size > 0) {
          await transcribeAudio(audio);
        }
      };
      recorder.start();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to access microphone.");
      setListening(false);
    }
  }

  function stopListening() {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
      return;
    }
    setListening(false);
  }

  async function transcribeAudio(audio: Blob) {
    setTranscribing(true);
    setTranscriptMeta("Transcribing audio...");
    setError(null);
    try {
      const result = await api.transcribe(audio);
      if (!result.text.trim()) {
        setError("No speech was detected. Try recording closer to the microphone.");
        return;
      }
      setText([baseTextRef.current, result.text.trim()].filter(Boolean).join(" "));
      setTranscriptMeta(`Transcribed with ${result.provider} (${result.model}).`);
    } catch (err) {
      setError(err instanceof Error ? `Microphone transcription failed: ${err.message}` : "Microphone transcription failed.");
    } finally {
      setTranscribing(false);
    }
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
              disabled={!speechSupported || listening || transcribing}
              onClick={startListening}
              type="button"
            >
              <Mic className="h-4 w-4" /> Record mic
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
            {speechSupported ? transcriptMeta || "Record in the browser, transcribe through the backend, or use phone keyboard dictation in the text box." : "Mic recording is not supported in this browser; typed capture still works."}
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
