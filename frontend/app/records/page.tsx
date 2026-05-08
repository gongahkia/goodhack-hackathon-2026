"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import { recordTitle, shortDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { KgNode } from "@/lib/types";

export default function RecordsPage() {
  const { t, dateLocale } = useI18n();
  const [records, setRecords] = useState<Array<KgNode & { forward_actions: KgNode[] }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.records().then(setRecords).catch((err) => setError(err.message));
  }, []);

  return (
    <>
      <AppHeader title={t("records.title")} subtitle={t("records.subtitle")} />
      <section className="flex-1 space-y-3 px-4 pb-4">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {records.length === 0 ? <p className="rounded-lg bg-white p-4 text-sm text-[#66726a]">{t("records.empty")}</p> : null}
        {records.map((record) => (
          <article className="rounded-xl border border-[#dfe8e2] bg-white p-4" key={record.id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase text-moss">{record.payload.record_type?.replace("_", " ")}</p>
                <h2 className="mt-1 font-bold">{recordTitle(record.payload)}</h2>
                <p className="mt-1 text-xs text-[#66726a]">{shortDate(record.payload.recorded_at, dateLocale)}</p>
              </div>
              <StatusBadge status={record.status} />
            </div>
            <p className="mt-3 text-sm text-[#536159]">{record.payload.content?.notes || record.payload.content?.dose || t("records.fallback")}</p>
            <div className="mt-4 border-t border-[#e7ede9] pt-3">
              <p className="text-xs font-bold uppercase text-[#66726a]">{t("records.spawnedActions")}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {record.forward_actions.length === 0 ? <span className="text-sm text-[#7b837e]">{t("common.noneYet")}</span> : null}
                {record.forward_actions.map((action) => (
                  <Link className="rounded-full bg-mint px-3 py-1.5 text-xs font-semibold text-moss" href={`/event/${action.id}`} key={action.id}>
                    {action.payload.title}
                  </Link>
                ))}
              </div>
            </div>
          </article>
        ))}
      </section>
      <BottomNav />
    </>
  );
}
