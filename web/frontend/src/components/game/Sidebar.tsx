"use client";

import { NPC_COLORS } from "@/lib/constants";
import type { CharacterProfile, PhaseData } from "@/lib/types";

interface SidebarProps {
  characters: CharacterProfile[];
  phases: PhaseData[];
  currentPhase: PhaseData | null;
  selectedNpc: string | null;
  onSelectNpc: (name: string | null) => void;
}

export function Sidebar({
  characters,
  phases,
  currentPhase,
  selectedNpc,
  onSelectNpc,
}: SidebarProps) {
  return (
    <aside className="flex w-56 flex-col gap-6 border-r border-slate-800 bg-slate-950/80 p-4">
      {/* Phase navigation */}
      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-600">
          Phases
        </h3>
        <div className="space-y-1">
          {phases.map((p) => {
            const isCurrent = p.name === currentPhase?.name;
            return (
              <div
                key={p.id}
                className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs transition-colors ${
                  isCurrent
                    ? "bg-[var(--color-gold-500)]/10 text-[var(--color-gold-500)]"
                    : "text-slate-500"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    isCurrent ? "bg-[var(--color-gold-500)]" : "bg-slate-700"
                  }`}
                />
                <span className="truncate">{p.name}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* NPC list */}
      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-600">
          Characters
        </h3>
        <div className="space-y-1">
          {characters.map((c) => {
            const color = NPC_COLORS[c.name] ?? "#94a3b8";
            const isSelected = selectedNpc === c.name;
            return (
              <button
                key={c.name}
                onClick={() => onSelectNpc(isSelected ? null : c.name)}
                className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors ${
                  isSelected
                    ? "bg-slate-800 text-slate-200"
                    : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
                }`}
              >
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                <span className="truncate">{c.name}</span>
                <span className="ml-auto text-[10px] text-slate-600 truncate">
                  {c.identity}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
