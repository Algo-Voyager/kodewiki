"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { triggerQuery, pollResult, fetchSessionLogs, type AgentResult, type LogEntry, type ContextMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ReasoningExpander } from "@/components/ReasoningExpander";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";

interface Message {
  role: "user" | "assistant";
  content: string;
  steps?: number;
  logs?: LogEntry[];
  error?: boolean;
}

type ChatHistories = Record<string, Message[]>;

function BotAvatar() {
  return (
    <div className="flex-shrink-0 w-7 h-7 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center text-xs font-bold text-primary">
      RM
    </div>
  );
}

export default function ChatPage() {
  const [collection, setCollection] = useState<string>("");
  const [histories, setHistories] = useState<ChatHistories>({});
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Per-collection in-flight and queue tracking — refs so async closures always
  // see current values without needing to be inside a useCallback dep array.
  const inFlightRef = useRef<Record<string, boolean>>({});
  const queuesRef = useRef<Record<string, string[]>>({});
  // Per-collection compressed context sent to the backend.
  // Separate from UI messages so compression doesn't affect the chat display.
  const contextRef = useRef<Record<string, ContextMessage[]>>({});
  // UI-only state for re-renders
  const [loadingCols, setLoadingCols] = useState<Record<string, boolean>>({});
  const [queueCounts, setQueueCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    function onCollectionChanged(e: Event) {
      const name = (e as CustomEvent<string>).detail;
      setCollection(name);
    }
    window.addEventListener("collection-changed", onCollectionChanged);
    const stored = sessionStorage.getItem("selected-collection");
    if (stored) setCollection(stored);
    return () => window.removeEventListener("collection-changed", onCollectionChanged);
  }, []);

  useEffect(() => {
    function onCollectionChanged(e: Event) {
      const name = (e as CustomEvent<string>).detail;
      sessionStorage.setItem("selected-collection", name);
    }
    window.addEventListener("collection-changed", onCollectionChanged);
    return () => window.removeEventListener("collection-changed", onCollectionChanged);
  }, []);

  const messages: Message[] = collection ? (histories[collection] ?? []) : [];
  const isCurrentLoading = !!loadingCols[collection];
  const currentQueueCount = queueCounts[collection] ?? 0;

  function appendMessage(col: string, msg: Message) {
    setHistories((prev) => ({
      ...prev,
      [col]: [...(prev[col] ?? []), msg],
    }));
  }

  function updateLastAssistant(col: string, updater: (m: Message) => Message) {
    setHistories((prev) => {
      const msgs = [...(prev[col] ?? [])];
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === "assistant") {
          msgs[i] = updater(msgs[i]);
          break;
        }
      }
      return { ...prev, [col]: msgs };
    });
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Core query executor — independent of React render cycle after being called.
  // Uses functional state updaters and refs so there are no stale closure issues.
  async function executeQuery(col: string, prompt: string) {
    // Snapshot the current compressed context and build the history to send.
    // contextRef holds only prior exchanges; the new user message is NOT included
    // here because the backend appends it internally during the ReAct prompt.
    const historyToSend: ContextMessage[] = contextRef.current[col] ?? [];

    appendMessage(col, { role: "assistant", content: "…" });

    try {
      const sessionId = await triggerQuery(prompt, col, historyToSend);

      let result: AgentResult | null = null;
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        result = await pollResult(sessionId);
        if (result) break;
      }

      if (!result) {
        updateLastAssistant(col, (m) => ({
          ...m,
          content: "The agent did not respond in time. The Modal service may be cold-starting — try again.",
          error: true,
        }));
        return;
      }

      const logs = await fetchSessionLogs(result.session_id);
      updateLastAssistant(col, (m) => ({
        ...m,
        content: result!.answer,
        steps: result!.steps,
        logs,
      }));

      // Update the context for the next message.
      // Use compressed_history returned by backend (may be same as sent if no
      // compression was needed), then append the current exchange.
      const updatedContext: ContextMessage[] = [
        ...(result.compressed_history ?? historyToSend),
        { role: "user", content: prompt },
        { role: "assistant", content: result.answer },
      ];
      contextRef.current[col] = updatedContext;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Something went wrong. Please try again.";
      updateLastAssistant(col, (m) => ({ ...m, content: msg, error: true }));
    } finally {
      // Dequeue next item for this collection, if any
      const q = queuesRef.current[col] ?? [];
      const next = q.shift();
      queuesRef.current[col] = q;
      setQueueCounts((prev) => ({ ...prev, [col]: q.length }));

      if (next !== undefined) {
        // Stay in-flight and process the next queued prompt immediately
        executeQuery(col, next);
      } else {
        inFlightRef.current[col] = false;
        setLoadingCols((prev) => ({ ...prev, [col]: false }));
      }
    }
  }

  const send = useCallback(() => {
    const prompt = input.trim();
    if (!prompt || !collection) return;
    setInput("");

    // Always show the user message immediately
    appendMessage(collection, { role: "user", content: prompt });

    if (inFlightRef.current[collection]) {
      // Same collection is busy — queue the prompt, assistant bubble added later
      const q = queuesRef.current[collection] ?? [];
      q.push(prompt);
      queuesRef.current[collection] = q;
      setQueueCounts((prev) => ({ ...prev, [collection]: q.length }));
    } else {
      // Collection is free — execute right away
      inFlightRef.current[collection] = true;
      setLoadingCols((prev) => ({ ...prev, [collection]: true }));
      executeQuery(collection, prompt);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, collection]);

  if (!collection) {
    return (
      <div className="flex flex-col flex-1 items-center justify-center gap-4 text-center px-6">
        <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-2xl font-bold text-primary">
          RM
        </div>
        <div>
          <p className="text-base font-medium text-foreground">No repository selected</p>
          <p className="text-sm text-muted-foreground mt-1">
            Choose an indexed repo from the sidebar to start chatting.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Header */}
      <div className="shrink-0 px-5 py-3 border-b border-border bg-card/50 backdrop-blur-sm flex items-center gap-3">
        <div className={`w-2 h-2 rounded-full shrink-0 ${isCurrentLoading ? "bg-yellow-400 animate-pulse" : "bg-green-400"}`} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate text-foreground">{collection}</p>
          <p className="text-xs text-muted-foreground">
            {isCurrentLoading
              ? currentQueueCount > 0
                ? `Processing · ${currentQueueCount} queued`
                : "Processing…"
              : "RepoMind agent"}
          </p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <p className="text-sm text-muted-foreground">Ask anything about the codebase.</p>
            <div className="flex flex-wrap gap-2 justify-center max-w-sm">
              {[
                "How is authentication handled?",
                "Explain the data ingestion pipeline",
                "Where are API routes defined?",
              ].map((hint) => (
                <button
                  key={hint}
                  onClick={() => setInput(hint)}
                  className="text-xs px-3 py-1.5 rounded-full border border-border text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors"
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5 max-w-3xl mx-auto w-full">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "assistant" && <BotAvatar />}

                <div
                  className={`flex flex-col gap-1 ${
                    msg.role === "user" ? "items-end max-w-[70%]" : "items-start flex-1 min-w-0"
                  }`}
                >
                  <div
                    className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                      msg.role === "user"
                        ? "bg-primary text-primary-foreground rounded-br-sm"
                        : msg.error
                        ? "bg-destructive/10 text-destructive border border-destructive/30 rounded-bl-sm w-full"
                        : "bg-card border border-border text-foreground rounded-bl-sm w-full"
                    }`}
                  >
                    {msg.role === "assistant" && msg.content === "…" ? (
                      <div className="flex items-center gap-2">
                        <span className="text-muted-foreground text-xs">Agent working</span>
                        <span className="flex gap-1">
                          {[0, 1, 2].map((d) => (
                            <span
                              key={d}
                              className="w-1 h-1 rounded-full bg-muted-foreground animate-bounce"
                              style={{ animationDelay: `${d * 0.15}s` }}
                            />
                          ))}
                        </span>
                      </div>
                    ) : msg.role === "assistant" ? (
                      <MarkdownRenderer content={msg.content} />
                    ) : (
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    )}
                  </div>

                  {msg.steps !== undefined && msg.logs !== undefined && (
                    <div className="w-full">
                      <ReasoningExpander steps={msg.steps} logs={msg.logs} />
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-border bg-card/50 px-4 py-3">
        <div className="max-w-3xl mx-auto flex gap-2 items-end">
          <div className="flex-1 relative">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder={
                isCurrentLoading
                  ? "Type to queue next question…"
                  : "Ask about the codebase… (Enter to send)"
              }
              className="resize-none min-h-[44px] max-h-36 text-sm pr-3 rounded-xl border-border focus-visible:ring-1 focus-visible:ring-primary/50"
              rows={1}
            />
          </div>
          <Button
            onClick={send}
            disabled={!input.trim()}
            size="sm"
            className="shrink-0 h-11 px-4 rounded-xl"
          >
            {isCurrentLoading ? "Queue" : "Send"}
          </Button>
        </div>
        <p className="text-center text-xs text-muted-foreground/50 mt-1.5 max-w-3xl mx-auto">
          {isCurrentLoading && currentQueueCount > 0
            ? `${currentQueueCount} question${currentQueueCount > 1 ? "s" : ""} queued — will run automatically`
            : "Shift+Enter for new line"}
        </p>
      </div>
    </div>
  );
}
