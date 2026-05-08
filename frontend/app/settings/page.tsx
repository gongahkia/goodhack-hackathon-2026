"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Activity, Database, FileClock, RefreshCw, RotateCcw, ShieldCheck, UserRound } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { BottomNav } from "@/components/bottom-nav";
import { useNotifications } from "@/components/notifications-provider";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { languages, useI18n, type Language } from "@/lib/i18n";
import type { PatientSummary } from "@/lib/types";

export default function SettingsPage() {
  const { language, setLanguage, t } = useI18n();
  const { notify, refreshNotifications } = useNotifications();
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; store: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    const [summary, status] = await Promise.all([api.summary(), api.health()]);
    setPatient(summary);
    setHealth(status);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function rebuildRecords() {
    setBusy("reset");
    setMessage(null);
    await api.reset();
    await load();
    setMessage(t("settings.rebuilt"));
    setBusy(null);
  }

  return (
    <>
      <AppHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <section className="flex-1 space-y-4 px-4 pb-4">
        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {message ? <div className="rounded-lg bg-mint p-3 text-sm font-semibold text-moss">{message}</div> : null}

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <h2 className="font-bold">{t("settings.language")}</h2>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.languageDescription")}</p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {languages.map((item) => (
              <button
                className={`rounded-lg border px-3 py-2 text-left text-sm font-semibold ${
                  language === item.code ? "border-moss bg-mint text-moss" : "border-[#dfe8e2] bg-white text-[#536159]"
                }`}
                key={item.code}
                onClick={() => setLanguage(item.code as Language)}
              >
                <span className="block">{item.nativeLabel}</span>
                <span className="text-xs font-normal">{item.label}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <UserRound className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.careProfile")}</h2>
          </div>
          <div className="mt-3 space-y-2 text-sm text-[#34423a]">
            <p>
              <span className="font-semibold">{t("common.patient")}:</span> {patient?.name || "Mdm Tan Siew Lan"}
            </p>
            <p>
              <span className="font-semibold">{t("settings.caregiver")}:</span> {patient?.caregiver || "Daughter, Elaine"}
            </p>
            <p>
              <span className="font-semibold">{t("settings.livingArrangement")}:</span> {patient?.living_arrangement || "Lives with daughter in Toa Payoh"}
            </p>
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <Database className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.recordProcessing")}</h2>
          </div>
          <p className="mt-2 text-sm text-[#536159]">{t("settings.recordProcessingDescription")}</p>
          <div className="mt-4 grid grid-cols-1 gap-2">
            <Button variant="secondary" onClick={rebuildRecords} disabled={Boolean(busy)}>
              <RotateCcw className="h-4 w-4" /> {t("settings.rebuild")}
            </Button>
          </div>
          {busy ? <p className="mt-3 text-sm font-semibold text-[#705a16]">{t("settings.rebuilding")}</p> : null}
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.traceability")}</h2>
          </div>
          <div className="mt-3 grid gap-2">
            <Link href="/audit" className="flex items-center justify-between rounded-lg border border-[#dfe8e2] px-3 py-3 text-sm font-semibold text-moss">
              <span className="inline-flex items-center gap-2">
                <FileClock className="h-4 w-4" /> {t("settings.reasoningTrail")}
              </span>
              <span aria-hidden="true">›</span>
            </Link>
            <Link href="/records" className="flex items-center justify-between rounded-lg border border-[#dfe8e2] px-3 py-3 text-sm font-semibold text-moss">
              <span className="inline-flex items-center gap-2">
                <RefreshCw className="h-4 w-4" /> {t("settings.recordProvenance")}
              </span>
              <span aria-hidden="true">›</span>
            </Link>
          </div>
        </section>

        <section className="rounded-xl border border-[#dfe8e2] bg-white p-4">
          <div className="flex items-center gap-2">
            <Activity className="h-5 w-5 text-moss" />
            <h2 className="font-bold">{t("settings.systemStatus")}</h2>
          </div>
          <div className="mt-3 flex items-center justify-between rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm">
            <span>{t("common.api")}</span>
            <span className="font-semibold text-moss">{health?.ok ? t("common.connected") : t("common.checking")}</span>
          </div>
          <div className="mt-2 flex items-center justify-between rounded-lg bg-[#f5f8f6] px-3 py-2 text-sm">
            <span>{t("common.storage")}</span>
            <span className="font-semibold text-moss">{health?.store || t("common.checking")}</span>
          </div>
        </section>
      </section>
      <BottomNav />
    </>
  );
}
