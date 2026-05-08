"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, ClipboardCheck, FileText, Settings } from "lucide-react";
import { clsx } from "clsx";
import { useI18n } from "@/lib/i18n";

const items = [
  { href: "/", labelKey: "nav.calendar", icon: CalendarDays },
  { href: "/review", labelKey: "nav.review", icon: ClipboardCheck },
  { href: "/records", labelKey: "nav.records", icon: FileText },
  { href: "/settings", labelKey: "nav.settings", icon: Settings }
];

export function BottomNav() {
  const pathname = usePathname();
  const { t } = useI18n();
  return (
    <nav className="sticky bottom-0 grid grid-cols-3 border-t border-[#dde5df] bg-white/95 px-2 py-2 backdrop-blur">
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href) && item.href !== "#";
        const Icon = item.icon;
        return (
          <Link
            href={item.href}
            key={item.labelKey}
            className={clsx("flex flex-col items-center gap-1 rounded-lg px-2 py-1.5 text-xs", active ? "bg-mint text-moss" : "text-[#6c756f]")}
          >
            <Icon className="h-5 w-5" aria-hidden="true" />
            <span>{t(item.labelKey)}</span>
          </Link>
        );
      })}
    </nav>
  );
}
