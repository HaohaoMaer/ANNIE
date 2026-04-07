"use client";

import { useEffect } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { FogOverlay } from "@/components/layout/FogOverlay";
import { Header } from "@/components/layout/Header";
import { useGameState } from "@/hooks/useGameState";
import { NPC_COLORS } from "@/lib/constants";
import type { CharacterProfile, ReplayData } from "@/lib/types";

function CharacterCard({ char, index }: { char: CharacterProfile; index: number }) {
  const color = NPC_COLORS[char.name] ?? char.color ?? "#94a3b8";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1, duration: 0.4 }}
      className="group relative overflow-hidden rounded-lg border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm transition-colors hover:border-amber-900/40"
    >
      {/* Top color bar */}
      <div className="absolute top-0 inset-x-0 h-1" style={{ backgroundColor: color }} />

      {/* Avatar circle */}
      <div
        className="mb-4 flex h-16 w-16 items-center justify-center rounded-full border-2 text-2xl font-bold"
        style={{ borderColor: color, color }}
      >
        {char.name.charAt(0)}
      </div>

      {/* Name and identity */}
      <h3 className="text-lg font-bold text-slate-100">{char.name}</h3>
      <p className="text-sm text-slate-500 mb-3">{char.identity}</p>

      {/* Traits */}
      <div className="flex flex-wrap gap-1 mb-3">
        {char.personality_traits.map((t) => (
          <span
            key={t}
            className="rounded-full px-2 py-0.5 text-[10px]"
            style={{
              backgroundColor: `${color}15`,
              color,
            }}
          >
            {t}
          </span>
        ))}
      </div>

      {/* Background */}
      <p className="text-xs leading-relaxed text-slate-400 line-clamp-3">
        {char.background}
      </p>

      {/* Goals */}
      {char.goals.length > 0 && (
        <div className="mt-3 border-t border-slate-800 pt-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600 mb-1">
            Goals
          </p>
          <ul className="space-y-0.5">
            {char.goals.slice(0, 2).map((g) => (
              <li key={g} className="text-xs text-slate-500">
                {g}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Secrets count */}
      <div className="absolute top-4 right-4">
        <span className="rounded-full bg-red-900/20 px-2 py-0.5 text-[10px] text-red-400">
          {char.secrets.length} secrets
        </span>
      </div>
    </motion.div>
  );
}

export default function CharactersPage() {
  const characters = useGameState((s) => s.characters);
  const loadReplay = useGameState((s) => s.loadReplay);

  useEffect(() => {
    if (characters.length > 0) return;
    fetch("/replay/midnight-train.json")
      .then((r) => r.json())
      .then((data: ReplayData) => loadReplay(data))
      .catch(() => {});
  }, [characters.length, loadReplay]);

  return (
    <>
      <FogOverlay intensity="low" />
      <Header />
      <main className="mx-auto max-w-6xl px-6 pt-20 pb-12">
        <div className="mb-8 flex items-center gap-4">
          <Link
            href="/"
            className="rounded-full border border-slate-800 p-2 text-slate-500 hover:bg-slate-900 hover:text-slate-300 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div>
            <h1 className="text-3xl font-bold text-[var(--color-gold-500)]">
              Characters
            </h1>
            <p className="text-sm text-slate-500">
              Six passengers, each with their own secrets
            </p>
          </div>
        </div>

        {characters.length > 0 ? (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {characters.map((c, i) => (
              <CharacterCard key={c.name} char={c} index={i} />
            ))}
          </div>
        ) : (
          <p className="text-center text-slate-600 py-12">Loading characters...</p>
        )}
      </main>
    </>
  );
}
