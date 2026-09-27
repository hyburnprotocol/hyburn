import type { Metadata } from "next";
import "./globals.css";
import { MenuBar } from "@/components/MenuBar";
import { CONFIG } from "@/lib/config";

export const metadata: Metadata = {
  title: "Hyburn",
  description: "Burn HYPE every 999 seconds, share the HYBURN issued for the round.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-white focus:px-2 focus:py-1">
          Skip to content
        </a>
        <MenuBar />
        <main id="main" className="flex-1 w-full max-w-4xl mx-auto px-4 py-4">
          {children}
        </main>
        <footer className="w-full max-w-4xl mx-auto px-4 py-4 text-sm flex flex-wrap gap-3 border-t">
          <span>Hyburn · Open source</span>
          <a href={CONFIG.repo} target="_blank" rel="noopener noreferrer">Source code</a>
          <a href={`${CONFIG.repo}/blob/HEAD/LICENSE`} target="_blank" rel="noopener noreferrer">MIT License</a>
        </footer>
      </body>
    </html>
  );
}
