"use client";

import { motion } from "framer-motion";
import { Eye } from "lucide-react";
import { NPC_COLORS, NPC_TEXT_COLORS, EMOTION_LABELS_CN, EMOTION_COLORS } from "@/lib/constants";
import { useTypewriter } from "@/hooks/useTypewriter";
import type { DialogueEntry } from "@/lib/types";

interface DialogueBubbleProps {
  entry: DialogueEntry;
  isLatest: boolean;
  onRevealThoughts: (npc: string) => void;
}

export function DialogueBubble({ entry, isLatest, onRevealThoughts }: DialogueBubbleProps) {
  const color = NPC_COLORS[entry.npc] ?? "#94a3b8";
  const textColorClass = NPC_TEXT_COLORS[entry.npc] ?? "text-slate-400";
  const displayText = useTypewriter(entry.spoken_words, 25, isLatest);
  const emotion = entry.emotional_state;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="group relative rounded-lg border-l-4 bg-slate-900/80 p-4 backdrop-blur-sm"
      style={{ borderLeftColor: color }}
    >
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`font-bold ${textColorClass}`}>{entry.npc}</span>
          {emotion && (
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
              style={{
                backgroundColor: `${EMOTION_COLORS[emotion.primary] ?? "#94a3b8"}20`,
                color: EMOTION_COLORS[emotion.primary] ?? "#94a3b8",
              }}
            >
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: EMOTION_COLORS[emotion.primary] ?? "#94a3b8" }}
              />
              {EMOTION_LABELS_CN[emotion.primary] ?? emotion.primary}
            </span>
          )}
          {entry.vote && (
            <span className="rounded-full bg-red-900/30 px-2 py-0.5 text-xs text-red-400">
              vote: {entry.vote}
            </span>
          )}
        </div>
        <button
          onClick={() => onRevealThoughts(entry.npc)}
          className="rounded p-1 text-slate-600 opacity-0 transition-opacity hover:bg-slate-800 hover:text-amber-400 group-hover:opacity-100"
          title="View inner thoughts"
        >
          <Eye className="h-4 w-4" />
        </button>
      </div>

      {/* Speech content */}
      <p className="text-sm leading-relaxed text-slate-200 whitespace-pre-wrap">
        {displayText}
        {isLatest && displayText.length < entry.spoken_words.length && (
          <span className="inline-block w-0.5 h-4 bg-amber-400 animate-pulse ml-0.5 align-text-bottom" />
        )}
      </p>
    </motion.div>
  );
}
