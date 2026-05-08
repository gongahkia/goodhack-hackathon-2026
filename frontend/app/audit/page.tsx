"use client";

import { useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { ReasoningLog } from "@/lib/types";

export default function AuditPage() {
  const { t, dateLocale } = useI18n();
  const [logs, setLogs] = useState<ReasoningLog[]>([]);
  const [selected, setSelected] = useState<ReasoningLog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.audit()
      .then((items) => {
        setLogs(items);
        setSelected(items[0] || null);
      })
      .catch((err) => setError(err.message));
  }, []);

  return (
    <>
      <AppHeader title={t("audit.title")} subtitle={t("audit.subtitle")} />
      <section className="flex-1 space-y-3 px-4 pb-4">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        <div className="flex gap-2 overflow-x-auto pb-1">
          {logs.map((log) => (
            <button
              className={`shrink-0 rounded-lg border px-3 py-2 text-left text-xs ${selected?.id === log.id ? "border-moss bg-mint text-moss" : "border-[#dfe8e2] bg-white text-[#536159]"}`}
              key={log.id}
              onClick={() => setSelected(log)}
            >
              <span className="block font-bold">{log.trigger.split(":")[0]}</span>
              <span>{formatDate(log.created_at, dateLocale)}</span>
            </button>
          ))}
        </div>
        {!selected ? <p className="rounded-lg bg-white p-4 text-sm text-[#66726a]">{t("audit.empty")}</p> : null}
        {selected ? (
          <article className="rounded-xl border border-[#dfe8e2] bg-white p-4">
            <p className="text-xs font-bold uppercase text-moss">{t("audit.conclusion")}</p>
            <p className="mt-2 text-sm text-[#34423a]">{selected.conclusion || "No conclusion recorded."}</p>
            <div className="mt-5 space-y-3 border-l-2 border-mint pl-4">
              {selected.steps.map((step, index) => (
                <div className="relative rounded-lg border border-[#e4ebe6] bg-[#fbfdfb] p-3" key={`${selected.id}-${index}`}>
                  <span className="absolute -left-[23px] top-4 h-3 w-3 rounded-full border-2 border-moss bg-white" />
                  <p className="text-xs font-bold uppercase text-[#66726a]">{step.kind || "step"}</p>
                  {step.text ? <p className="mt-1 text-sm">{step.text}</p> : null}
                  {step.tool ? <p className="mt-1 text-sm font-semibold">{step.tool}</p> : null}
                  {step.input ? <pre className="mt-2 overflow-auto rounded bg-[#eef3ef] p-2 text-xs">{JSON.stringify(step.input, null, 2)}</pre> : null}
                  {step.result ? <pre className="mt-2 max-h-48 overflow-auto rounded bg-[#eef3ef] p-2 text-xs">{JSON.stringify(step.result, null, 2)}</pre> : null}
                  {step.message ? <p className="mt-1 text-sm text-[#8d3d29]">{step.message}</p> : null}
                </div>
              ))}
            </div>
          </article>
        ) : null}
      </section>
      <BottomNav />
    </>
  );
}
