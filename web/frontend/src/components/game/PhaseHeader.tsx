"use client";

import type { PhaseData } from "@/lib/types";

interface PhaseHeaderProps {
  phases: PhaseData[];
  currentPhase: PhaseData | null;
}

export function PhaseHeader({ phases, currentPhase }: PhaseHeaderProps) {
  const currentIdx = phases.findIndex((p) => p.name === currentPhase?.name);

  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3 backdrop-blur-sm">
      {/* Phase dots */}
      <div className="flex items-center gap-1.5">
        {phases.map((p, i) => (
          <div
            key={p.id}
            className={`h-2 rounded-full transition-all ${
              i <= currentIdx
                ? "w-6 bg-[var(--color-gold-500)]"
                : "w-2 bg-slate-700"
            }`}
          />
        ))}
      </div>

      {/* Phase name */}
      {currentPhase && (
        <div className="flex-1 min-w-0">
          <p className="truncate text-sm font-bold text-[var(--color-gold-500)]">
            {currentPhase.name}
          </p>
          <p className="truncate text-xs text-slate-500">
            {currentPhase.description}
          </p>
        </div>
      )}
    </div>
  );
}
