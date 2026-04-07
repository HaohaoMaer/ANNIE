"use client";

import { motion } from "framer-motion";
import { NPC_COLORS } from "@/lib/constants";
import type { VoteResults } from "@/lib/types";

interface VoteRevealProps {
  results: VoteResults;
}

export function VoteReveal({ results }: VoteRevealProps) {
  const entries = Object.entries(results.votes);
  const maxCount = Math.max(...Object.values(results.counts), 1);

  return (
    <div className="space-y-6">
      {/* Vote cards */}
      <div className="flex flex-wrap justify-center gap-3">
        {entries.map(([voter, target], i) => (
          <motion.div
            key={voter}
            initial={{ rotateY: 180, opacity: 0 }}
            animate={{ rotateY: 0, opacity: 1 }}
            transition={{ delay: i * 0.3, duration: 0.6, type: "spring" }}
            style={{ perspective: 800 }}
            className="w-28 rounded-lg border border-slate-700 bg-slate-900/90 p-3 text-center"
          >
            <p
              className="text-xs font-bold mb-1"
              style={{ color: NPC_COLORS[voter] ?? "#94a3b8" }}
            >
              {voter}
            </p>
            <p className="text-[10px] text-slate-600 mb-1">voted for</p>
            <p className="text-sm font-bold text-red-400">{target}</p>
          </motion.div>
        ))}
      </div>

      {/* Bar chart */}
      <div className="space-y-2">
        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-600">
          Vote Tally
        </h4>
        {Object.entries(results.counts)
          .sort(([, a], [, b]) => b - a)
          .map(([name, count], i) => (
            <div key={name} className="flex items-center gap-2">
              <span
                className="w-16 text-right text-xs font-bold truncate"
                style={{ color: NPC_COLORS[name] ?? "#94a3b8" }}
              >
                {name}
              </span>
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${(count / maxCount) * 100}%` }}
                transition={{
                  delay: entries.length * 0.3 + 0.3 + i * 0.15,
                  duration: 0.5,
                  type: "spring",
                }}
                className={`h-5 rounded-sm ${
                  name === results.top_suspect
                    ? "bg-red-500/80"
                    : "bg-slate-700"
                }`}
              />
              <span className="text-xs text-slate-500 font-[family-name:var(--font-geist-mono)]">
                {count}
              </span>
            </div>
          ))}
      </div>

      {/* Suspect callout */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: entries.length * 0.3 + 1 }}
        className="text-center"
      >
        <p className="text-xs text-slate-500 mb-1">Primary Suspect</p>
        <p className="text-2xl font-bold text-red-400 animate-pulse">
          {results.top_suspect}
        </p>
      </motion.div>
    </div>
  );
}
