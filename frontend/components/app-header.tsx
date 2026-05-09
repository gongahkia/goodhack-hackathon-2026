"use client";

import Link from "next/link";
import { useState } from "react";
import { ChevronDown, Languages, Settings } from "lucide-react";
import { NotificationBell } from "@/components/notifications-provider";
import { SettingsModal } from "@/components/settings-modal";
import { languages, useI18n, type Language } from "@/lib/i18n";

export function AppHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <header className="px-5 pb-3 pt-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href="/" className="text-xs font-semibold uppercase text-moss">
            Caregiver Companion
          </Link>
          <h1 className="mt-2 text-2xl font-bold text-ink">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-[#66726a]">{subtitle}</p> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <LanguageSelector />
          <NotificationBell />
          <button
            aria-label="Settings"
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#dfe8e2] bg-white text-moss shadow-sm"
            onClick={() => setSettingsOpen(true)}
            type="button"
          >
            <Settings className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </header>
  );
}

function LanguageSelector() {
  const { language, setLanguage, t } = useI18n();
  return (
    <label className="relative inline-flex h-10 items-center rounded-full border border-[#dfe8e2] bg-white pl-3 pr-8 text-moss shadow-sm">
      <Languages className="h-4 w-4" aria-hidden="true" />
      <select
        aria-label={t("settings.language")}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        value={language}
        onChange={(event) => setLanguage(event.target.value as Language)}
      >
        {languages.map((item) => (
          <option key={item.code} value={item.code}>
            {item.nativeLabel}
          </option>
        ))}
      </select>
      <span className="ml-1 text-xs font-bold uppercase" aria-hidden="true">
        {language}
      </span>
      <ChevronDown className="absolute right-2 h-3.5 w-3.5" aria-hidden="true" />
    </label>
  );
}
