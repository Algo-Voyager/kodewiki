"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Cpu, Eye, EyeOff, KeyRound, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getStoredGithubToken,
  setStoredGithubToken,
  getStoredVllmApiKey,
  setStoredVllmApiKey,
} from "@/lib/api";

/**
 * Settings page — currently just the GitHub PAT override.
 *
 * The token is stored in localStorage and sent as `X-Github-Token` on every
 * /api/ingest and /api/query call. When set, it overrides the server-side
 * GITHUB_TOKEN env var (handled by backend/auth.py:set_github_token_override).
 *
 * Use case: the deploy's pre-configured PAT expired or got rate-limited —
 * paste your own here to keep ingesting + querying without redeploying.
 */
export default function SettingsPage() {
  const [token, setToken] = useState("");
  const [reveal, setReveal] = useState(false);
  const [saved, setSaved] = useState<"idle" | "saved" | "cleared">("idle");

  const [vllmKey, setVllmKey] = useState("");
  const [revealVllm, setRevealVllm] = useState(false);
  const [savedVllm, setSavedVllm] = useState<"idle" | "saved" | "cleared">("idle");

  // Hydrate inputs from localStorage on mount.
  useEffect(() => {
    setToken(getStoredGithubToken());
    setVllmKey(getStoredVllmApiKey());
  }, []);

  const handleSave = () => {
    setStoredGithubToken(token);
    setSaved(token.trim() ? "saved" : "cleared");
    setTimeout(() => setSaved("idle"), 2500);
  };

  const handleClear = () => {
    setToken("");
    setStoredGithubToken("");
    setSaved("cleared");
    setTimeout(() => setSaved("idle"), 2500);
  };

  const handleSaveVllm = () => {
    setStoredVllmApiKey(vllmKey);
    setSavedVllm(vllmKey.trim() ? "saved" : "cleared");
    setTimeout(() => setSavedVllm("idle"), 2500);
  };

  const handleClearVllm = () => {
    setVllmKey("");
    setStoredVllmApiKey("");
    setSavedVllm("cleared");
    setTimeout(() => setSavedVllm("idle"), 2500);
  };

  const masked = token && !reveal ? "•".repeat(Math.min(token.length, 36)) : token;
  const maskedVllm = vllmKey && !revealVllm ? "•".repeat(Math.min(vllmKey.length, 36)) : vllmKey;

  return (
    <div className="mx-auto max-w-2xl py-10 px-6 space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Override the deploy&apos;s API keys with your own. Stored locally in
          this browser only (localStorage) — never sent anywhere except as a
          header on requests to the backend.
        </p>
      </div>

      {/* ─── GitHub PAT ─────────────────────────────────────────────────── */}
      <section className="rounded-xl border border-border bg-card p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-amber-500/15 border border-amber-500/30 p-2">
            <KeyRound className="h-5 w-5 text-amber-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-foreground">
              GitHub Personal Access Token
            </h2>
            <p className="text-xs text-muted-foreground">
              Used for repo ingestion. If the server&apos;s default token is
              expired or rate-limited, paste a fresh one here.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            PAT
          </label>
          <div className="flex gap-2">
            <Input
              type={reveal ? "text" : "password"}
              value={reveal ? token : masked}
              onChange={(e) => setToken(e.target.value)}
              placeholder="ghp_… or github_pat_…"
              className="font-mono text-sm flex-1"
              autoComplete="off"
              spellCheck={false}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => setReveal((v) => !v)}
              title={reveal ? "Hide token" : "Reveal token"}
            >
              {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Generate one at{" "}
            <a
              href="https://github.com/settings/tokens/new?scopes=repo&description=repomind"
              target="_blank"
              rel="noreferrer"
              className="text-sky-400 hover:underline"
            >
              github.com/settings/tokens/new
            </a>{" "}
            — needs <code className="px-1 rounded bg-muted">repo</code> (or just{" "}
            <code className="px-1 rounded bg-muted">public_repo</code>) read access.
          </p>
        </div>

        <div className="flex items-center gap-2 pt-2">
          <Button onClick={handleSave} className="bg-sky-500 hover:bg-sky-600 text-white">
            <Save className="h-4 w-4 mr-2" />
            Save
          </Button>
          <Button onClick={handleClear} variant="outline" disabled={!token}>
            <Trash2 className="h-4 w-4 mr-2" />
            Clear
          </Button>
          {saved === "saved" && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs text-emerald-400">
              <CheckCircle2 className="h-4 w-4" />
              Saved — next request uses this token.
            </span>
          )}
          {saved === "cleared" && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
              <CheckCircle2 className="h-4 w-4" />
              Cleared — falling back to the server&apos;s default.
            </span>
          )}
        </div>
      </section>

      {/* ─── LLM / VLLM API Key ─────────────────────────────────────────── */}
      <section className="rounded-xl border border-border bg-card p-6 space-y-4">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-sky-500/15 border border-sky-500/30 p-2">
            <Cpu className="h-5 w-5 text-sky-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-foreground">
              LLM API Key <span className="text-xs font-normal text-muted-foreground">(Modal / vLLM Bearer)</span>
            </h2>
            <p className="text-xs text-muted-foreground">
              Auth key for the Qwen + embedding endpoints. Use your own Modal key
              if the deploy&apos;s default has rotated, or to point at your own
              Modal deployment.
            </p>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            API Key
          </label>
          <div className="flex gap-2">
            <Input
              type={revealVllm ? "text" : "password"}
              value={revealVllm ? vllmKey : maskedVllm}
              onChange={(e) => setVllmKey(e.target.value)}
              placeholder="Bearer key from your Modal app's secret"
              className="font-mono text-sm flex-1"
              autoComplete="off"
              spellCheck={false}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => setRevealVllm((v) => !v)}
              title={revealVllm ? "Hide key" : "Reveal key"}
            >
              {revealVllm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Sent as <code className="px-1 rounded bg-muted">X-VLLM-Key</code>.
            Backend uses it as the <code className="px-1 rounded bg-muted">Authorization: Bearer</code>{" "}
            for both Qwen generation and embedding calls.
          </p>
        </div>

        <div className="flex items-center gap-2 pt-2">
          <Button onClick={handleSaveVllm} className="bg-sky-500 hover:bg-sky-600 text-white">
            <Save className="h-4 w-4 mr-2" />
            Save
          </Button>
          <Button onClick={handleClearVllm} variant="outline" disabled={!vllmKey}>
            <Trash2 className="h-4 w-4 mr-2" />
            Clear
          </Button>
          {savedVllm === "saved" && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs text-emerald-400">
              <CheckCircle2 className="h-4 w-4" />
              Saved — next LLM/embedding call uses this key.
            </span>
          )}
          {savedVllm === "cleared" && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
              <CheckCircle2 className="h-4 w-4" />
              Cleared — falling back to the server&apos;s default.
            </span>
          )}
        </div>
      </section>

      {/* ─── Notes ───────────────────────────────────────────────────────── */}
      <section className="rounded-xl border border-border bg-muted/30 p-5 text-xs text-muted-foreground space-y-2">
        <p>
          <strong className="text-foreground">Scope of override:</strong> the
          token is used for <em>your</em> requests only (this browser). Other
          users of the deployed app see the server&apos;s default token.
        </p>
        <p>
          <strong className="text-foreground">Security:</strong> stored in
          localStorage of this browser, sent only to the configured backend
          over HTTPS. Clear when you&apos;re done if this is a shared device.
        </p>
        <p>
          <strong className="text-foreground">When to use:</strong> server-side
          PAT expired, got rate-limited, or you want to access a private repo
          your team owns but the deploy&apos;s token doesn&apos;t.
        </p>
      </section>
    </div>
  );
}
