"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import { BookOpen, ClipboardList, ExternalLink, FileText, ImageIcon, Info, Paperclip, Save, ThumbsDown, ThumbsUp, Trash2, Upload, X } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { useNotifications } from "@/components/notifications-provider";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate, recordTitle, shortDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { AppointmentPrep, EventDetail, KgNode } from "@/lib/types";

type EventAttachment = {
  id: string;
  name: string;
  type: string;
  size: number;
  data_url: string;
  created_at: string;
};

type CareReference = {
  id: string;
  label: string;
  definition: string;
  purpose: string;
  references: Array<{ title: string; source: string; url: string }>;
};

export default function EventDetailPage({ params }: { params: { id: string } }) {
  const { t, dateLocale } = useI18n();
  const { notify, refreshNotifications } = useNotifications();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [actionType, setActionType] = useState("");
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  const [recurrence, setRecurrence] = useState("");
  const [location, setLocation] = useState("");
  const [agency, setAgency] = useState("");
  const [activeReference, setActiveReference] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const detail = await api.event(params.id);
    setEvent(detail);
    setTitle(detail.payload.title || "");
    setDescription(detail.payload.description || "");
    setActionType(detail.payload.action_type || "");
    setStartAt(toDatetimeLocal(detail.payload.start_at));
    setEndAt(toDatetimeLocal(detail.payload.end_at));
    setRecurrence(detail.payload.recurrence || "");
    setLocation(detail.payload.location || "");
    setAgency(detail.payload.agency || "");
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [params.id]);

  async function setStatus(status: string) {
    setBusy(status);
    try {
      const updated = await api.status(params.id, status);
      await load();
      await refreshNotifications({ suppressToasts: true });
      notify({
        title: t("notifications.statusSaved"),
        body: updated.payload.title || event?.payload.title || t("event.careAction"),
        kind: status,
        href: `/event/${params.id}`
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function saveEdit() {
    setBusy("edit");
    try {
      const payload: Record<string, string> = {
        title,
        description,
        action_type: actionType,
        recurrence,
        location,
        agency
      };
      if (startAt) {
        payload.start_at = new Date(startAt).toISOString();
      }
      if (endAt) {
        payload.end_at = new Date(endAt).toISOString();
      }
      const updated = await api.editNode(params.id, payload);
      await load();
      await refreshNotifications({ suppressToasts: true });
      notify({
        title: t("notifications.editSaved"),
        body: updated.payload.title || title,
        kind: "edited",
        href: `/event/${params.id}`
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function attachFiles(changeEvent: ChangeEvent<HTMLInputElement>) {
    if (!event) {
      return;
    }
    const files = Array.from(changeEvent.target.files || []);
    if (files.length === 0) {
      return;
    }
    setBusy("attachment");
    setError(null);
    try {
      const newAttachments = await Promise.all(files.map(fileToAttachment));
      const attachments = [...((event.payload.attachments as EventAttachment[] | undefined) || []), ...newAttachments];
      const updated = await api.editNode(params.id, { attachments });
      await load();
      await refreshNotifications({ suppressToasts: true });
      notify({
        title: t("event.attachmentsUpdated"),
        body: updated.payload.title || title,
        kind: "edited",
        href: `/event/${params.id}`
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
      changeEvent.target.value = "";
    }
  }

  async function removeAttachment(attachmentId: string) {
    if (!event) {
      return;
    }
    setBusy("attachment");
    setError(null);
    try {
      const attachments = ((event.payload.attachments as EventAttachment[] | undefined) || []).filter((attachment) => attachment.id !== attachmentId);
      await api.editNode(params.id, { attachments });
      await load();
      await refreshNotifications({ suppressToasts: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  const resource = event?.related_nodes.find((node) => node.type === "recommended_resource");
  const grant = event?.related_nodes.find((node) => node.type === "grant_opportunity");
  const attachments = ((event?.payload.attachments as EventAttachment[] | undefined) || []) as EventAttachment[];
  const references = event ? careReferencesForEvent(event, resource) : [];
  const selectedReference = references.find((reference) => reference.id === activeReference) || references[0] || null;

  return (
    <>
      <AppHeader title={t("event.title")} subtitle={t("event.subtitle")} />
      <section className="flex-1 space-y-4 px-4 pb-28">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {!event ? <p className="rounded-lg bg-white p-4 text-sm text-[#66726a]">{t("event.loading")}</p> : null}
        {event ? (
          <>
            <article className="rounded-xl border border-[#dfe8e2] bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-bold uppercase text-moss">{event.payload.action_type || t("event.careAction")}</p>
                  <h1 className="mt-1 text-xl font-bold">
                    <LinkedClinicalText text={event.payload.title} onReferenceClick={setActiveReference} />
                  </h1>
                  <p className="mt-1 text-sm text-[#66726a]">{formatDate(event.payload.start_at, dateLocale)}</p>
                </div>
                <StatusBadge status={event.status} />
              </div>
              <p className="mt-3 text-sm text-[#34423a]">
                <LinkedClinicalText text={event.payload.description} onReferenceClick={setActiveReference} />
              </p>
              {event.payload.recurrence ? <p className="mt-2 text-sm font-semibold text-moss">{event.payload.recurrence}</p> : null}
              {appointmentRescheduleUrl(event) ? (
                <a
                  className="mt-4 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white"
                  href={appointmentRescheduleUrl(event)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("common.reschedule")} <ExternalLink className="h-4 w-4" />
                </a>
              ) : null}
              {references.length > 0 ? (
                <div className="relative mt-4">
                  <div className="flex flex-wrap gap-2">
                    {references.map((reference) => (
                      <button
                        className="inline-flex items-center gap-1.5 rounded-full border border-[#cbd8cf] bg-[#f5f8f6] px-3 py-1.5 text-xs font-bold text-moss"
                        key={reference.id}
                        onClick={() => setActiveReference((current) => (current === reference.id ? null : reference.id))}
                      >
                        <Info className="h-3.5 w-3.5" /> {reference.label}
                      </button>
                    ))}
                  </div>
                  {activeReference && selectedReference ? (
                    <ReferenceBubble reference={selectedReference} onClose={() => setActiveReference(null)} />
                  ) : null}
                </div>
              ) : null}
            </article>

            {event.appointment_prep ? <AppointmentPrepPanel prep={event.appointment_prep} /> : null}

            <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
              <h2 className="font-bold">{t("event.review")}</h2>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Button onClick={() => setStatus("approved")} disabled={Boolean(busy)}>
                  <ThumbsUp className="h-4 w-4" /> {t("event.approve")}
                </Button>
                <Button variant="danger" onClick={() => setStatus("dismissed")} disabled={Boolean(busy)}>
                  <ThumbsDown className="h-4 w-4" /> {t("event.dismiss")}
                </Button>
              </div>
              <div className="mt-4 space-y-3">
                <label className="block text-sm font-semibold text-[#34423a]">
                  {t("event.actionTitle")}
                  <input className="mt-1 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm" value={title} onChange={(event) => setTitle(event.target.value)} />
                </label>
                <label className="block text-sm font-semibold text-[#34423a]">
                  {t("event.actionDescription")}
                  <textarea
                    className="mt-1 min-h-24 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="block text-sm font-semibold text-[#34423a]">
                    {t("event.type")}
                    <select className="mt-1 w-full rounded-lg border border-[#ccd8d0] bg-white px-3 py-2 text-sm" value={actionType} onChange={(event) => setActionType(event.target.value)}>
                      {["medication", "therapy", "appointment", "grant", "task"].map((type) => (
                        <option key={type} value={type}>
                          {t(`eventType.${type}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-sm font-semibold text-[#34423a]">
                    {t("event.recurrence")}
                    <input className="mt-1 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm" value={recurrence} onChange={(event) => setRecurrence(event.target.value)} />
                  </label>
                </div>
                <div className="grid grid-cols-1 gap-2">
                  <label className="block text-sm font-semibold text-[#34423a]">
                    {t("event.start")}
                    <input className="mt-1 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm" type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} />
                  </label>
                  <label className="block text-sm font-semibold text-[#34423a]">
                    {t("event.end")}
                    <input className="mt-1 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm" type="datetime-local" value={endAt} onChange={(event) => setEndAt(event.target.value)} />
                  </label>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <label className="block text-sm font-semibold text-[#34423a]">
                    {t("event.location")}
                    <input className="mt-1 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm" value={location} onChange={(event) => setLocation(event.target.value)} />
                  </label>
                  <label className="block text-sm font-semibold text-[#34423a]">
                    {t("event.agency")}
                    <input className="mt-1 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm" value={agency} onChange={(event) => setAgency(event.target.value)} />
                  </label>
                </div>
                <Button variant="secondary" onClick={saveEdit} disabled={Boolean(busy)}>
                  <Save className="h-4 w-4" /> {t("event.saveEdit")}
                </Button>
              </div>
            </section>

            <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="inline-flex items-center gap-2 font-bold">
                  <Paperclip className="h-4 w-4 text-moss" /> {t("event.attachments")}
                </h2>
                <label className="inline-flex min-h-10 cursor-pointer items-center justify-center gap-2 rounded-lg border border-[#cbd8cf] bg-white px-3 py-2 text-sm font-semibold text-moss">
                  <Upload className="h-4 w-4" /> {t("event.addAttachment")}
                  <input className="sr-only" type="file" multiple accept="image/*,.pdf,.doc,.docx,.txt,.csv" onChange={attachFiles} disabled={Boolean(busy)} />
                </label>
              </div>
              <div className="mt-3 space-y-2">
                {attachments.length === 0 ? <p className="rounded-lg bg-[#f5f8f6] p-3 text-sm text-[#66726a]">{t("event.noAttachments")}</p> : null}
                {attachments.map((attachment) => (
                  <div className="flex items-center gap-3 rounded-lg border border-[#dfe8e2] p-2" key={attachment.id}>
                    <AttachmentIcon attachment={attachment} />
                    <a className="min-w-0 flex-1" href={attachment.data_url} target="_blank" rel="noreferrer" download={attachment.name}>
                      <span className="block truncate text-sm font-bold text-ink">{attachment.name}</span>
                      <span className="text-xs text-[#66726a]">{formatBytes(attachment.size)}</span>
                    </a>
                    <button className="rounded-lg p-2 text-[#8d3d29] hover:bg-[#f4e5df]" onClick={() => removeAttachment(attachment.id)} aria-label={t("event.removeAttachment")} disabled={Boolean(busy)}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
              <h2 className="font-bold">{t("event.derivedFrom")}</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {event.source_records.map((record) => (
                  <Link href="/records" className="rounded-full bg-mint px-3 py-1.5 text-xs font-semibold text-moss" key={record.id}>
                    {recordLabel(record, dateLocale)}
                  </Link>
                ))}
              </div>
            </section>

            {resource ? <ResourcePanel resource={resource} /> : null}
            {grant ? <GrantPanel grant={grant} /> : null}

            {event.reasoning_log ? (
              <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
                <h2 className="font-bold">{t("event.reasoning")}</h2>
                <div className="mt-3 space-y-2">
                  {(event.reasoning_narrative?.length ? event.reasoning_narrative : [event.reasoning_log.conclusion]).map((line, index) => (
                    <p className="rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm text-[#34423a]" key={index}>
                      {line}
                    </p>
                  ))}
                </div>
                <Link href="/audit" className="mt-3 inline-flex text-sm font-semibold text-moss">
                  {t("event.viewReasoning")}
                </Link>
              </section>
            ) : null}
          </>
        ) : null}
      </section>
      <BottomNav />
    </>
  );
}

function recordLabel(record: KgNode, locale: string) {
  const date = shortDate(record.payload.recorded_at, locale);
  return `${recordTitle(record.payload)} · ${date}`;
}

function careReferencesForEvent(event: EventDetail, resource?: KgNode): CareReference[] {
  const actionType = event.payload.action_type;
  const title = String(event.payload.title || "").toLowerCase();
  const description = String(event.payload.description || "").toLowerCase();
  const references: CareReference[] = [];

  if (title.includes("parkinson") || description.includes("parkinson")) {
    references.push({
      id: "condition-parkinsons",
      label: "Parkinson's reference",
      definition:
        "Parkinson's disease is a progressive movement condition that can affect tremor, stiffness, movement speed, walking, balance, and daily routines.",
      purpose:
        "For this care plan, Parkinson's is the clinical context that explains why medication timing, daily movement, falls monitoring, and neurology follow-up are being surfaced together.",
      references: [
        { title: "Parkinson's disease overview", source: "HealthHub", url: "https://www.healthhub.sg/" },
        { title: "Understanding Parkinson's", source: "Parkinson's Foundation", url: "https://www.parkinson.org/understanding-parkinsons" }
      ]
    });
  }

  if (actionType === "medication" || title.includes("levodopa")) {
    references.push({
      id: "medication-levodopa",
      label: "Medication reference",
      definition: "Levodopa/Carbidopa is a Parkinson's medicine used to replace or support dopamine signalling. Carbidopa helps more levodopa reach the brain and can reduce nausea.",
      purpose:
        "For this care action, the practical purpose is timing: give each dose after meals as prescribed, keep the timing consistent, and flag missed doses or side effects for the neurology team.",
      references: [
        { title: "Medication timing and Parkinson's symptoms", source: "HealthHub", url: "https://www.healthhub.sg/" },
        { title: "Levodopa and Parkinson's treatment information", source: "Parkinson's Foundation", url: "https://www.parkinson.org/living-with-parkinsons/treatment/prescription-medications/levodopa" }
      ]
    });
  }

  if (actionType === "therapy" || title.includes("exercise") || title.includes("physio")) {
    references.push({
      id: "therapy-physio",
      label: "Physio reference",
      definition: "Seated physiotherapy exercises are low-risk movement routines done while sitting, usually focused on posture, mobility, strength, and confidence.",
      purpose:
        "For this care action, the purpose is to maintain daily movement while Parkinson's symptoms are still mild, build routine, and make it easier to notice changes in mobility or balance.",
      references: [
        {
          title: resource?.payload.title || "Seated Parkinson's exercise routine",
          source: resource?.payload.source || "Parkinson's Foundation",
          url: resource?.payload.url || "https://www.parkinson.org/"
        },
        { title: "Exercise and Parkinson's care", source: "Parkinson's Foundation", url: "https://www.parkinson.org/living-with-parkinsons/treatment/exercise" }
      ]
    });
  }

  return references;
}

function LinkedClinicalText({ text, onReferenceClick }: { text: string | undefined; onReferenceClick: (referenceId: string) => void }) {
  const value = String(text || "");
  const parts = value.split(/(Parkinson's|Parkinsons|Parkinson)/gi);
  return (
    <>
      {parts.map((part, index) => {
        if (/^Parkinson'?s?$|^Parkinson$/i.test(part)) {
          return (
            <button
              className="inline rounded-sm text-moss underline decoration-moss/40 underline-offset-2 hover:bg-mint/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-moss"
              key={`${part}-${index}`}
              onClick={() => onReferenceClick("condition-parkinsons")}
              type="button"
            >
              {part}
            </button>
          );
        }
        return part;
      })}
    </>
  );
}

function appointmentRescheduleUrl(event: EventDetail) {
  if (event.payload.action_type !== "appointment") {
    return null;
  }
  return event.payload.scheduling_url || event.payload.reschedule_url || inferSchedulingUrl(event.payload.location || event.payload.title);
}

function inferSchedulingUrl(value?: string) {
  const text = String(value || "").toLowerCase();
  if (text.includes("tan tock seng") || text.includes("ttsh") || text.includes("neurology")) {
    return "https://www.ttsh.com.sg/Patients-and-Visitors/Your-Clinic-Visit/Pages/Appointments.aspx";
  }
  return "https://www.healthhub.sg/programmes/healthhub-health-appointment-system";
}

function ReferenceBubble({ reference, onClose }: { reference: CareReference; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className="absolute left-0 right-0 top-full z-30 mt-3 rounded-xl border border-[#cbd8cf] bg-white p-4 text-sm shadow-lg">
      <span className="absolute left-8 top-[-7px] h-3.5 w-3.5 rotate-45 border-l border-t border-[#cbd8cf] bg-white" />
      <div className="flex items-start justify-between gap-3">
        <h2 className="inline-flex items-center gap-2 font-bold text-ink">
          <BookOpen className="h-4 w-4 text-moss" /> {reference.label}
        </h2>
        <button className="rounded-full p-1 text-[#66726a] hover:bg-[#eef3ef]" onClick={onClose} aria-label={t("reference.close")}>
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-3 space-y-3">
        <div>
          <p className="text-xs font-bold uppercase text-moss">{t("reference.definition")}</p>
          <p className="mt-1 text-[#34423a]">{reference.definition}</p>
        </div>
        <div>
          <p className="text-xs font-bold uppercase text-moss">{t("reference.purpose")}</p>
          <p className="mt-1 text-[#34423a]">{reference.purpose}</p>
        </div>
        <div>
          <p className="text-xs font-bold uppercase text-moss">{t("reference.sources")}</p>
          <div className="mt-2 flex flex-col gap-2">
            {reference.references.map((item) => (
              <a className="inline-flex items-start justify-between gap-3 rounded-lg border border-[#dfe8e2] px-3 py-2 font-semibold text-moss" href={item.url} target="_blank" rel="noreferrer" key={`${reference.id}-${item.title}`}>
                <span>
                  <span className="block">{item.title}</span>
                  <span className="text-xs font-normal text-[#66726a]">{item.source}</span>
                </span>
                <ExternalLink className="mt-0.5 h-4 w-4 shrink-0" />
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AppointmentPrepPanel({ prep }: { prep: AppointmentPrep }) {
  const { t } = useI18n();
  return (
    <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
      <h2 className="inline-flex items-center gap-2 font-bold">
        <ClipboardList className="h-4 w-4 text-moss" /> {t("event.appointmentPrep")}
      </h2>
      <div className="mt-3 grid gap-3">
        <PrepList title={t("event.prepSymptoms")} items={prep.symptoms_to_mention} />
        <PrepList title={t("event.prepMedication")} items={prep.medication_notes} />
        <PrepList title={t("event.prepMobility")} items={prep.therapy_mobility_notes} />
        <PrepList title={t("event.prepQuestions")} items={prep.questions_for_clinician} />
        <PrepList title={t("event.prepLongTerm")} items={prep.long_term_concerns} />
        <PrepList title={t("event.prepRecurring")} items={prep.recurring_concerns || []} />
        <PrepList title={t("event.prepPreviousQuestions")} items={prep.previous_questions || []} />
        <PrepList title={t("event.prepUnresolved")} items={prep.unresolved_advice || []} />
        <PrepList title={t("event.prepRevisit")} items={prep.revisit_next_time || []} />
      </div>
      {prep.evidence.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {prep.evidence.map((item) => (
            <span className="rounded-full bg-mint px-3 py-1.5 text-xs font-semibold text-moss" key={item.id}>
              {item.title || item.type}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function PrepList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="rounded-lg bg-[#f5f8f6] p-3">
      <p className="text-xs font-bold uppercase text-moss">{title}</p>
      <ul className="mt-2 space-y-1.5 text-sm text-[#34423a]">
        {items.map((item) => (
          <li className="flex gap-2" key={item}>
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-moss" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function toDatetimeLocal(value?: string) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function fileToAttachment(file: File): Promise<EventAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve({
        id: crypto.randomUUID(),
        name: file.name,
        type: file.type || "application/octet-stream",
        size: file.size,
        data_url: String(reader.result),
        created_at: new Date().toISOString()
      });
    reader.onerror = () => reject(reader.error || new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

function formatBytes(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${Math.round(size / 1024)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function AttachmentIcon({ attachment }: { attachment: EventAttachment }) {
  if (attachment.type.startsWith("image/")) {
    return (
      <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-mint text-moss">
        <img alt="" className="h-full w-full object-cover" src={attachment.data_url} />
      </span>
    );
  }
  return (
    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-[#eef3ef] text-moss">
      {attachment.type === "application/pdf" ? <FileText className="h-5 w-5" /> : <ImageIcon className="h-5 w-5" />}
    </span>
  );
}

function ResourcePanel({ resource }: { resource: KgNode }) {
  const { t } = useI18n();
  const url = resourceUrl(resource);
  const isVideo = resource.payload.type === "video" && resource.payload.youtube_id && resource.payload.youtube_id !== "N7eQGdK6m5I";
  return (
    <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
      <h2 className="font-bold">{t("event.resource")}</h2>
      <p className="mt-1 text-sm text-[#34423a]">{resource.payload.title}</p>
      {isVideo ? (
        <div className="mt-3 aspect-video overflow-hidden rounded-lg border border-[#dfe8e2]">
          <iframe
            className="h-full w-full"
            src={`https://www.youtube.com/embed/${resource.payload.youtube_id}`}
            title={resource.payload.title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
      ) : (
        <a href={url} target="_blank" rel="noreferrer" className="mt-3 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white">
          {t("common.openResource")} <ExternalLink className="h-4 w-4" />
        </a>
      )}
    </section>
  );
}

function resourceUrl(resource: KgNode) {
  if (resource.payload.youtube_id === "N7eQGdK6m5I") {
    return "https://www.parkinson.org/library/videos/exercise";
  }
  if (resource.payload.url && !String(resource.payload.url).includes("youtube.com/embed/N7eQGdK6m5I")) {
    return resource.payload.url;
  }
  return "https://www.parkinson.org/library/videos/exercise";
}

function GrantPanel({ grant }: { grant: KgNode }) {
  const { t } = useI18n();
  return (
    <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
      <h2 className="font-bold">{t("event.grant")}</h2>
      <p className="mt-1 text-sm font-semibold text-moss">{grant.payload.name}</p>
      <p className="mt-2 text-sm text-[#34423a]">{grant.payload.summary}</p>
      <a
        className="mt-4 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-moss px-3 py-2 text-sm font-semibold text-white"
        href={grant.payload.url}
        target="_blank"
        rel="noreferrer"
      >
        {t("common.apply")} <ExternalLink className="h-4 w-4" />
      </a>
    </section>
  );
}
