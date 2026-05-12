"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  MessageSquare,
  ScrollText,
  BarChart3,
  GitBranch,
  Zap,
  Cpu,
  ExternalLink,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Database,
  ChevronRight,
} from "lucide-react";
import { fetchCollections, ingestRepo, type Collection } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// ─── Nav config ───────────────────────────────────────────────────────────────

const NAV = [
  {
    href: "/chat",
    label: "Chat",
    icon: MessageSquare,
    color: "text-violet-400",
    bg: "bg-violet-500/15",
    activeBg: "bg-violet-500/20",
    activeBorder: "border-violet-500/30",
  },
  {
    href: "/logs",
    label: "Logs",
    icon: ScrollText,
    color: "text-sky-400",
    bg: "bg-sky-500/15",
    activeBg: "bg-sky-500/20",
    activeBorder: "border-sky-500/30",
  },
  {
    href: "/benchmarks",
    label: "Benchmarks",
    icon: BarChart3,
    color: "text-emerald-400",
    bg: "bg-emerald-500/15",
    activeBg: "bg-emerald-500/20",
    activeBorder: "border-emerald-500/30",
  },
] as const;

// ─── Sidebar ──────────────────────────────────────────────────────────────────

export function Sidebar() {
  const pathname = usePathname();
  const [repo, setRepo] = useState("");
  const [mode, setMode] = useState<"ast" | "naive">("ast");
  const [collections, setCollections] = useState<Collection[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [status, setStatus] = useState<{ msg: string; type: "ok" | "err" } | null>(null);
  const [loading, setLoading] = useState(false);

  // Resizable sidebar
  const [sidebarWidth, setSidebarWidth] = useState(220);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(0);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragStartX.current = e.clientX;
    dragStartWidth.current = sidebarWidth;
    setIsDragging(true);
  }, [sidebarWidth]);

  useEffect(() => {
    if (!isDragging) return;

    function onMouseMove(e: MouseEvent) {
      const delta = e.clientX - dragStartX.current;
      const next = Math.min(400, Math.max(160, dragStartWidth.current + delta));
      setSidebarWidth(next);
    }
    function onMouseUp() {
      setIsDragging(false);
    }

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, [isDragging]);

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
    <aside
      style={{ width: sidebarWidth }}
      className="relative flex flex-col shrink-0 h-full border-r border-white/[0.06] bg-[#0d0d10] overflow-hidden select-none"
    >
      {/* Drag handle */}
      <div
        onMouseDown={onDragStart}
        className={cn(
          "absolute top-0 right-0 h-full w-1 z-50 cursor-col-resize group transition-colors",
          isDragging ? "bg-violet-500/60" : "hover:bg-violet-500/40"
        )}
      >
        {/* Centre dots */}
        <div className="absolute top-1/2 -translate-y-1/2 left-1/2 -translate-x-1/2 flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {[0, 1, 2].map((i) => (
            <div key={i} className="w-1 h-1 rounded-full bg-violet-400/80" />
          ))}
        </div>
      </div>

      {/* ── Branding ─────────────────────────────────────────────────────── */}
      <div className="px-4 pt-5 pb-4">
        <div className="flex items-center gap-3">
          {/* Logo mark */}
          <div className="relative shrink-0">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-violet-500/30">
              <Zap className="w-4 h-4 text-white" />
            </div>
            <div className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-green-400 border-2 border-[#0d0d10]" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-white leading-tight">
              RepoMind
            </h1>
            <p className="text-[11px] text-white/40 leading-tight mt-0.5">Dev-Doc Agent</p>
          </div>
        </div>
      </div>

      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <div className="px-2 pb-2">
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ href, label, icon: Icon, color, bg, activeBg, activeBorder }) => {
            const isActive = pathname.startsWith(href);
            return (
              <Link key={href} href={href}>
                <motion.div
                  whileHover={{ x: 2 }}
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-colors",
                    isActive
                      ? `${activeBg} border ${activeBorder} text-white`
                      : "text-white/50 hover:text-white/80 hover:bg-white/[0.04] border border-transparent"
                  )}
                >
                  {/* Icon badge */}
                  <div className={cn(
                    "w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-colors",
                    isActive ? bg : "bg-white/[0.06]"
                  )}>
                    <Icon className={cn("w-3.5 h-3.5", isActive ? color : "text-white/40")} />
                  </div>

                  <span className="text-[13px] font-medium leading-none">{label}</span>

                  {isActive && (
                    <ChevronRight className={cn("w-3 h-3 ml-auto", color)} />
                  )}
                </motion.div>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* divider */}
      <div className="mx-3 h-px bg-white/[0.06] mb-1" />

      {/* ── Add Repository ────────────────────────────────────────────────── */}
      <div className="px-3 py-3 flex flex-col gap-2.5">
        <div className="flex items-center gap-2 px-1">
          <GitBranch className="w-3 h-3 text-white/30" />
          <p className="text-[10px] font-semibold text-white/30 uppercase tracking-widest">
            Add Repository
          </p>
        </div>

        <Input
          placeholder="owner/repo"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleIngest()}
          className="h-8 text-xs rounded-lg bg-white/[0.04] border-white/[0.08] text-white/80 placeholder:text-white/20 focus-visible:ring-violet-500/40 focus-visible:border-violet-500/40"
        />

        {/* AST / Naive toggle */}
        <div className="flex gap-1.5 p-1 bg-white/[0.04] rounded-lg border border-white/[0.06]">
          {(["ast", "naive"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={cn(
                "flex-1 py-1 rounded-md text-[11px] font-semibold tracking-wide transition-all",
                mode === m
                  ? "bg-violet-500 text-white shadow-sm shadow-violet-500/30"
                  : "text-white/30 hover:text-white/60"
              )}
            >
              {m.toUpperCase()}
            </button>
          ))}
        </div>

        <motion.div whileTap={{ scale: 0.98 }}>
          <Button
            onClick={handleIngest}
            disabled={loading}
            size="sm"
            className={cn(
              "w-full h-8 text-xs rounded-lg font-semibold tracking-wide transition-all",
              "bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500",
              "text-white border-0 shadow-md shadow-violet-500/20"
            )}
          >
            {loading ? (
              <span className="flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin" /> Triggering…
              </span>
            ) : (
              "Ingest Repo"
            )}
          </Button>
        </motion.div>

        <AnimatePresence>
          {status && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              className={cn(
                "flex items-center gap-1.5 text-[11px] px-1",
                status.type === "ok" ? "text-emerald-400" : "text-red-400"
              )}
            >
              {status.type === "ok"
                ? <CheckCircle2 className="w-3 h-3 shrink-0" />
                : <AlertCircle className="w-3 h-3 shrink-0" />
              }
              <span>{status.msg}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* divider */}
      <div className="mx-3 h-px bg-white/[0.06] mb-1" />

      {/* ── Indexed Repos ─────────────────────────────────────────────────── */}
      <div className="px-3 py-3 flex flex-col gap-2 flex-1 min-h-0 overflow-y-auto">
        <div className="flex items-center gap-2 px-1">
          <Database className="w-3 h-3 text-white/30" />
          <p className="text-[10px] font-semibold text-white/30 uppercase tracking-widest">
            Indexed Repos
          </p>
        </div>

        {collections.length === 0 ? (
          <p className="text-[11px] text-white/20 px-1 py-1">No repos ingested yet</p>
        ) : (
          <div className="flex flex-col gap-1">
            {collections.map((col) => {
              const isActive = selected === col.name;
              return (
                <motion.button
                  key={col.name}
                  onClick={() => {
                    setSelected(col.name);
                    window.dispatchEvent(
                      new CustomEvent("collection-changed", { detail: col.name })
                    );
                  }}
                  whileHover={{ x: 2 }}
                  whileTap={{ scale: 0.98 }}
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  className={cn(
                    "flex items-center justify-between w-full px-2.5 py-2 rounded-xl text-left transition-all border",
                    isActive
                      ? "bg-violet-500/10 border-violet-500/25 text-white"
                      : "border-transparent text-white/40 hover:bg-white/[0.04] hover:text-white/70"
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <div className={cn(
                      "w-1.5 h-1.5 rounded-full shrink-0",
                      isActive ? "bg-violet-400" : "bg-white/20"
                    )} />
                    <span className="text-[11px] font-medium truncate">{col.name}</span>
                  </div>
                  <span className={cn(
                    "shrink-0 ml-1.5 text-[10px] font-mono px-1.5 py-0.5 rounded-md",
                    isActive
                      ? "bg-violet-500/20 text-violet-300"
                      : "bg-white/[0.06] text-white/30"
                  )}>
                    {col.chunk_count}
                  </span>
                </motion.button>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <div className="px-3 pb-4">
        <div className="mx-0 h-px bg-white/[0.06] mb-3" />

        {/* Model info pill */}
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.05] mb-2">
          <Cpu className="w-3 h-3 text-white/30 shrink-0" />
          <span className="text-[10px] text-white/30 truncate">Qwen2.5-7B · Modal GPU</span>
        </div>

        <a
          href="http://localhost:8288"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-[10px] text-white/30 hover:text-violet-400 hover:bg-violet-500/5 transition-all"
        >
          <ExternalLink className="w-3 h-3 shrink-0" />
          <span>Inngest Dev UI</span>
        </a>
      </div>
    </aside>
  );
}
