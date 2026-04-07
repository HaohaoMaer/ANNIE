"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Lock, X } from "lucide-react";
import { NPC_TEXT_COLORS, EMOTION_LABELS_CN, EMOTION_COLORS } from "@/lib/constants";
import type { DialogueEntry } from "@/lib/types";

interface InnerThoughtsProps {
  entry: DialogueEntry | null;
  onClose: () => void;
}

export function InnerThoughts({ entry, onClose }: InnerThoughtsProps) {
  return (
    <AnimatePresence>
      {entry && (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 20 }}
          transition={{ duration: 0.25 }}
          className="relative overflow-hidden rounded-lg border border-red-900/30 bg-slate-950"
        >
          {/* Top gradient accent */}
          <div className="h-0.5 bg-gradient-to-r from-red-900/0 via-red-500/60 to-red-900/0" />

          {/* Danger stripes background */}
          <div
            className="absolute inset-0 opacity-[0.02]"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, transparent, transparent 10px, rgb(239 68 68) 10px, rgb(239 68 68) 11px)",
            }}
          />

          <div className="relative p-4">
            {/* Header */}
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Lock className="h-3.5 w-3.5 text-red-400" />
                <span className="text-sm font-bold text-red-400">
                  内心独白
                </span>
                <span className={`text-sm font-bold ${NPC_TEXT_COLORS[entry.npc] ?? "text-slate-400"}`}>
                  {entry.npc}
                </span>
              </div>
              <button
                onClick={onClose}
                className="rounded p-1 text-slate-600 hover:bg-slate-800 hover:text-slate-300"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Emotional state */}
            {entry.emotional_state && (
              <div className="mb-3 flex items-center gap-2">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{
                    backgroundColor:
                      EMOTION_COLORS[entry.emotional_state.primary] ?? "#94a3b8",
                  }}
                />
                <span className="text-xs text-slate-500">
                  {EMOTION_LABELS_CN[entry.emotional_state.primary] ??
                    entry.emotional_state.primary}{" "}
                  (intensity: {(entry.emotional_state.intensity * 100).toFixed(0)}%)
                </span>
              </div>
            )}

            {/* Inner thoughts content */}
            <p className="text-sm italic leading-relaxed text-slate-400 whitespace-pre-wrap">
              {entry.inner_thoughts || "No inner thoughts recorded."}
            </p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
