"use client";

import { useEffect, useRef, useCallback } from "react";
import { DialogueBubble } from "./DialogueBubble";
import { ThinkingIndicator } from "./ThinkingIndicator";
import type { DialogueEntry, ThinkingIndicatorData } from "@/lib/types";

interface DialogueStreamProps {
  dialogue: DialogueEntry[];
  currentTurnIndex: number;
  onRevealThoughts: (npc: string) => void;
  thinkingNpc?: ThinkingIndicatorData | null;
}

export function DialogueStream({
  dialogue,
  currentTurnIndex,
  onRevealThoughts,
  thinkingNpc,
}: DialogueStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Track whether user is near the bottom (within 120px)
  const isNearBottomRef = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isNearBottomRef.current = distFromBottom < 120;
  }, []);

  useEffect(() => {
    // Only auto-scroll if user hasn't scrolled up manually
    if (isNearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [dialogue.length, thinkingNpc?.npc]);

  if (dialogue.length === 0 && !thinkingNpc) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-600">
        <p className="text-sm">Press play to start the replay...</p>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto"
      onScroll={handleScroll}
    >
      <div className="space-y-3 p-4">
        {dialogue.map((entry) => (
          <DialogueBubble
            key={entry.turn_index}
            entry={entry}
            isLatest={entry.turn_index === currentTurnIndex}
            onRevealThoughts={onRevealThoughts}
          />
        ))}
        <ThinkingIndicator data={thinkingNpc ?? null} />
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
