"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { fetchCollections, ingestRepo, type Collection } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

const NAV = [
  { href: "/chat", label: "Chat", icon: "💬" },
  { href: "/logs", label: "Logs", icon: "📜" },
  { href: "/benchmarks", label: "Benchmarks", icon: "📊" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [repo, setRepo] = useState("");
  const [mode, setMode] = useState<"ast" | "naive">("ast");
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [status, setStatus] = useState<{ msg: string; type: "ok" | "err" } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadCollections();
  }, []);

  async function loadCollections() {
    const cols = await fetchCollections();
    setCollections(cols);
    if (cols.length > 0 && !selected) {
      setSelected(cols[0].name);
      window.dispatchEvent(new CustomEvent("collection-changed", { detail: cols[0].name }));
    }
  }

  async function handleIngest() {
    if (!repo.includes("/")) {
      setStatus({ msg: "Format: owner/repo", type: "err" });
      return;
    }
    setLoading(true);
    setStatus(null);
    try {
      await ingestRepo(repo, mode);
      setStatus({ msg: `Triggered for ${repo}`, type: "ok" });
      setTimeout(loadCollections, 3000);
    } catch (e: unknown) {
      setStatus({ msg: e instanceof Error ? e.message : "Ingest failed", type: "err" });
    } finally {
      setLoading(false);
    }
  }

  return (
    <aside className="flex flex-col w-60 shrink-0 border-r border-border bg-card overflow-y-auto">
      {/* Branding */}
      <div className="px-4 pt-5 pb-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary/20 border border-primary/30 flex items-center justify-center text-xs font-bold text-primary shrink-0">
            RM
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight leading-tight">RepoMind</h1>
            <p className="text-xs text-muted-foreground leading-tight">Dev-Doc Agent</p>
          </div>
        </div>
      </div>

      <Separator />

      {/* Navigation */}
      <nav className="px-2 py-2 flex flex-col gap-0.5">
        {NAV.map(({ href, label, icon }) => (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
              pathname.startsWith(href)
                ? "bg-accent text-accent-foreground font-medium"
                : "text-muted-foreground hover:bg-accent/40 hover:text-foreground"
            }`}
          >
            <span className="text-base leading-none">{icon}</span>
            <span>{label}</span>
          </Link>
        ))}
      </nav>

      <Separator />

      {/* Repo ingestion */}
      <div className="px-3 py-4 flex flex-col gap-2.5">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest px-1">
          Add Repository
        </p>
        <Input
          placeholder="owner/repo"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleIngest()}
          className="h-8 text-sm rounded-lg"
        />

        <div className="flex gap-1.5">
          {(["ast", "naive"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 py-1 rounded-lg text-xs font-medium transition-colors border ${
                mode === m
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-border text-muted-foreground hover:bg-accent/40"
              }`}
            >
              {m.toUpperCase()}
            </button>
          ))}
        </div>

        <Button
          onClick={handleIngest}
          disabled={loading}
          size="sm"
          className="w-full h-8 text-xs rounded-lg"
        >
          {loading ? "Triggering…" : "Ingest repo"}
        </Button>

        {status && (
          <p className={`text-xs px-1 ${status.type === "ok" ? "text-green-400" : "text-destructive"}`}>
            {status.msg}
          </p>
        )}
      </div>

      <Separator />

      {/* Collection selector */}
      <div className="px-3 py-4 flex flex-col gap-2">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest px-1">
          Indexed Repos
        </p>
        {collections.length === 0 ? (
          <p className="text-xs text-muted-foreground px-1">No repos ingested yet</p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {collections.map((col) => (
              <button
                key={col.name}
                onClick={() => {
                  setSelected(col.name);
                  window.dispatchEvent(new CustomEvent("collection-changed", { detail: col.name }));
                }}
                className={`flex items-center justify-between px-2.5 py-2 rounded-lg text-xs text-left transition-colors group ${
                  selected === col.name
                    ? "bg-primary/15 text-foreground border border-primary/25"
                    : "text-muted-foreground hover:bg-accent/40 hover:text-foreground border border-transparent"
                }`}
              >
                <span className="truncate font-medium">{col.name}</span>
                <Badge
                  variant="secondary"
                  className={`ml-2 shrink-0 text-[10px] px-1.5 ${
                    selected === col.name ? "bg-primary/20 text-primary" : ""
                  }`}
                >
                  {col.chunk_count}
                </Badge>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="mt-auto px-3 py-4">
        <Separator className="mb-3" />
        <p className="text-[11px] text-muted-foreground px-1">Qwen2.5-7B · Modal GPU</p>
        <a
          href="http://localhost:8288"
          target="_blank"
          rel="noreferrer"
          className="block text-[11px] text-muted-foreground hover:text-foreground transition-colors mt-1 px-1 underline underline-offset-2"
        >
          Inngest Dev UI →
        </a>
      </div>
    </aside>
  );
}
