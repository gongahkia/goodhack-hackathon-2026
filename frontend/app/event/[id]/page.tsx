"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import { BookOpen, ExternalLink, FileText, ImageIcon, Info, Paperclip, Save, ThumbsDown, ThumbsUp, Trash2, Upload, X } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { useNotifications } from "@/components/notifications-provider";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDate, recordTitle, shortDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { EventDetail, KgNode } from "@/lib/types";

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
                  <h1 className="mt-1 text-xl font-bold">{event.payload.title}</h1>
                  <p className="mt-1 text-sm text-[#66726a]">{formatDate(event.payload.start_at, dateLocale)}</p>
                </div>
                <StatusBadge status={event.status} />
              </div>
              <p className="mt-3 text-sm text-[#34423a]">{event.payload.description}</p>
              {event.payload.recurrence ? <p className="mt-2 text-sm font-semibold text-moss">{event.payload.recurrence}</p> : null}
            </article>

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
              <div className="mt-4 space-y-2">
                <input
                  className="w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  aria-label={t("event.actionTitle")}
                />
                <textarea
                  className="min-h-24 w-full rounded-lg border border-[#ccd8d0] px-3 py-2 text-sm"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  aria-label={t("event.actionDescription")}
                />
                <Button variant="secondary" onClick={saveEdit} disabled={Boolean(busy)}>
                  <Save className="h-4 w-4" /> {t("event.saveEdit")}
                </Button>
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
                <p className="mt-2 text-sm text-[#34423a]">{event.reasoning_log.conclusion}</p>
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

function ResourcePanel({ resource }: { resource: KgNode }) {
  const { t } = useI18n();
  const isVideo = resource.payload.type === "video" && resource.payload.youtube_id;
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
        <a href={resource.payload.url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-moss">
          {t("common.openResource")} <ExternalLink className="h-4 w-4" />
        </a>
      )}
    </section>
  );
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
