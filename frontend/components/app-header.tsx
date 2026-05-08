import Link from "next/link";
import { NotificationBell } from "@/components/notifications-provider";

export function AppHeader({ title, subtitle }: { title: string; subtitle?: string }) {
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
        <NotificationBell />
      </div>
    </header>
  );
}
