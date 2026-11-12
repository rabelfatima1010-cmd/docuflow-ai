import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "DocuFlow AI",
  description: "AI invoice and receipt processing with human review",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
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
