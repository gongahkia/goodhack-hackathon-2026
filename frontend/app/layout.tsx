import type { Metadata } from "next";
import { NotificationsProvider } from "@/components/notifications-provider";
import { LanguageProvider } from "@/lib/i18n";
import "./globals.css";

export const metadata: Metadata = {
  title: "Caregiver Companion",
  description: "Traceable caregiving calendar for Singapore families"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <LanguageProvider>
          <NotificationsProvider>
            <main className="mx-auto flex min-h-screen w-full max-w-[430px] flex-col bg-[#fbfdfb] shadow-app md:my-6 md:min-h-[860px] md:rounded-[28px] md:border md:border-white/70">
              {children}
            </main>
          </NotificationsProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
