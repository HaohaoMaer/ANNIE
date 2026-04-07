"use client";

import { AnimatePresence, motion } from "framer-motion";
import { NPC_COLORS, NPC_TEXT_COLORS } from "@/lib/constants";
import type { ThinkingIndicatorData } from "@/lib/types";

interface ThinkingIndicatorProps {
  data: ThinkingIndicatorData | null;
}

export function ThinkingIndicator({ data }: ThinkingIndicatorProps) {
  return (
    <AnimatePresence>
      {data && (
        <motion.div
          key={data.npc}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25 }}
          className="rounded-lg border-l-4 bg-slate-900/60 p-4 backdrop-blur-sm"
          style={{ borderLeftColor: NPC_COLORS[data.npc] ?? "#94a3b8" }}
        >
          <div className="flex items-center gap-3">
            {/* Three-dot typing animation */}
            <div className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: NPC_COLORS[data.npc] ?? "#94a3b8" }}
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{
                    duration: 1.2,
                    repeat: Infinity,
                    delay: i * 0.2,
                  }}
                />
              ))}
            </div>
            <span
              className={`text-sm font-bold ${NPC_TEXT_COLORS[data.npc] ?? "text-slate-400"}`}
            >
              {data.npc}
            </span>
            <span className="text-xs text-slate-500">正在思考...</span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
