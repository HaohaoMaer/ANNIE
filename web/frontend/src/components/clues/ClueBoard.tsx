"use client";

import { motion } from "framer-motion";
import { Search, HelpCircle } from "lucide-react";
import type { ClueData } from "@/lib/types";

interface ClueBoardProps {
  clues: ClueData[];
}

export function ClueBoard({ clues }: ClueBoardProps) {
  if (clues.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8 text-slate-600">
        <Search className="h-6 w-6" />
        <p className="text-xs">No clues available yet</p>
      </div>
    );
  }

  const categories = [...new Set(clues.map((c) => c.category))];

  return (
    <div className="space-y-4 p-2">
      {categories.map((cat) => (
        <div key={cat}>
          <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-600">
            {cat}
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {clues
              .filter((c) => c.category === cat)
              .map((clue) => (
                <ClueCard key={clue.id} clue={clue} />
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function ClueCard({ clue }: { clue: ClueData }) {
  if (!clue.discovered) {
    return (
      <div className="flex aspect-[4/3] items-center justify-center rounded-md border border-slate-800 bg-slate-900/60">
        <HelpCircle className="h-5 w-5 text-slate-700" />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ rotateY: 180 }}
      animate={{ rotateY: 0 }}
      transition={{ duration: 0.5 }}
      className="rounded-md border border-amber-900/30 bg-slate-900/80 p-2"
      style={{ perspective: 800 }}
    >
      <p className="text-[10px] leading-snug text-slate-300 line-clamp-4">
        {clue.content || clue.file_name}
      </p>
      {clue.discovered_by && (
        <p className="mt-1 text-[9px] text-amber-600">
          {clue.discovered_by}
        </p>
      )}
    </motion.div>
  );
}
