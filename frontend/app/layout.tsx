import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "RepoMind",
  description: "Developer documentation agent",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark h-full">
      <body className="flex h-full overflow-hidden bg-background text-foreground antialiased">
        <Sidebar />
        <main className="flex flex-col flex-1 min-w-0 overflow-hidden">
          {children}
        </main>
      </body>
    </html>
  );
}
