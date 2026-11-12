import type { Metadata } from "next";
import Link from "next/link";
import { DEMO, REPO_URL } from "@/lib/api";
import "./globals.css";

export const metadata: Metadata = {
  title: "DocuFlow AI",
  description: "AI invoice and receipt processing with human review",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {DEMO && (
          <div className="px-4 py-2 text-center text-sm" style={{ background: "var(--info-bg)", color: "var(--info)" }}>
            <b>Live demo</b> · 20 invoices processed by a real AI run (gpt-6.1-sol). You can review and approve;
            changes aren&apos;t saved.{" "}
            <a className="underline font-semibold" href={REPO_URL} target="_blank" rel="noreferrer">
              View the code on GitHub →
            </a>
          </div>
        )}
        <header className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <nav className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
            <Link href="/" className="text-lg font-bold">
              DocuFlow <span style={{ color: "var(--accent)" }}>AI</span>
            </Link>
            <Link href="/" className="text-sm font-medium muted hover:underline">
              Inbox
            </Link>
            <Link href="/dashboard" className="text-sm font-medium muted hover:underline">
              Dashboard
            </Link>
          </nav>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
