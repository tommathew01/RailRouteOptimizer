import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import { DataModeBanner } from "@/components/DataModeBanner";

import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "RailRoute Optimizer", template: "%s · RailRoute Optimizer" },
  description:
    "Find same-train segment combinations when a direct Indian Railways ticket is unavailable.",
  applicationName: "RailRoute Optimizer",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0f4c5c" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1f26" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <Providers>
          <header className="site-header">
            <div className="container-page flex items-center justify-between gap-4 py-3">
              <Link href="/" className="brand" aria-label="RailRoute Optimizer home">
                <span aria-hidden="true" className="brand-mark">
                  ⇢
                </span>
                RailRoute
              </Link>
              <p className="hidden text-sm text-muted sm:block">Same-train segment finder</p>
            </div>
          </header>
          <Suspense fallback={null}>
            <DataModeBanner />
          </Suspense>
          <main id="main" className="container-page flex-1 py-6 sm:py-10">
            {children}
          </main>
          <footer className="site-footer">
            <div className="container-page py-6 text-sm text-muted">
              RailRoute is independent and is not affiliated with Indian Railways or IRCTC. It
              does not book tickets. Each segment is a separate reservation.
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
