"use client";

import { motion } from "framer-motion";
import { useTypewriter } from "@/hooks/useTypewriter";
import { NPC_COLORS } from "@/lib/constants";
import type { TruthRevealData } from "@/lib/types";

interface TruthRevealProps {
  truth: TruthRevealData;
}

export function TruthReveal({ truth }: TruthRevealProps) {
  const narration = useTypewriter(truth.narration, 40, true);
  const color = NPC_COLORS[truth.real_murderer] ?? "#ef4444";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 1 }}
      className="relative flex flex-col items-center gap-6 py-8 text-center"
    >
      {/* Spotlight */}
      <div
        className="absolute inset-0 opacity-20"
        style={{
          background: `radial-gradient(ellipse at center, ${color}40 0%, transparent 60%)`,
        }}
      />

      {/* Murderer reveal */}
      <motion.div
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.5, type: "spring", stiffness: 200 }}
        className="relative z-10"
      >
        <p className="text-sm text-slate-500 mb-2">The murderer is...</p>
        <p className="text-4xl font-bold" style={{ color }}>
          {truth.real_murderer}
        </p>
      </motion.div>

      {/* Method */}
      {truth.murder_method && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.5 }}
          className="relative z-10 max-w-lg text-sm text-slate-400 italic"
        >
          {truth.murder_method}
        </motion.p>
      )}

      {/* Narration */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 2 }}
        className="relative z-10 max-w-xl"
      >
        <p className="text-sm leading-relaxed text-slate-300 whitespace-pre-wrap">
          {narration}
        </p>
      </motion.div>

      {/* Verdict */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 3 }}
        className={`relative z-10 rounded-full px-6 py-2 text-sm font-bold ${
          truth.is_correct
            ? "bg-gradient-to-r from-amber-600 to-amber-400 text-slate-950"
            : "bg-gradient-to-r from-red-800 to-red-600 text-slate-100"
        }`}
      >
        {truth.is_correct ? "Justice Prevails!" : "The Murderer Escaped..."}
      </motion.div>
    </motion.div>
  );
}
