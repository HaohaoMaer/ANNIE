"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Play, Users } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";

export function HeroSection() {
  return (
    <section className="relative flex min-h-[100dvh] flex-col items-center justify-center overflow-hidden px-6">
      {/* Background gradient layers */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_rgba(251,191,36,0.06)_0%,_transparent_60%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom,_rgba(239,68,68,0.04)_0%,_transparent_50%)]" />

      {/* Animated train window dividers */}
      <div className="absolute inset-y-0 left-1/4 w-px bg-gradient-to-b from-transparent via-amber-900/20 to-transparent" />
      <div className="absolute inset-y-0 right-1/4 w-px bg-gradient-to-b from-transparent via-amber-900/20 to-transparent" />

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
        className="relative z-10 text-center max-w-3xl"
      >
        {/* Title */}
        <h1 className="text-6xl sm:text-7xl font-bold tracking-tight text-[var(--color-gold-500)] mb-2">
          午夜列车
        </h1>
        <p className="font-[family-name:var(--font-geist-mono)] text-sm text-[var(--color-gold-600)]/60 tracking-[0.3em] uppercase mb-8">
          Midnight Train
        </p>

        {/* Tagline */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4, duration: 0.8 }}
          className="text-xl sm:text-2xl text-slate-300 mb-4 leading-relaxed"
        >
          六位旅客，一具尸体
        </motion.p>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, duration: 0.8 }}
          className="text-lg text-slate-400 mb-12"
        >
          每个人都有秘密，每个人都在说谎
        </motion.p>

        {/* CTAs */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8, duration: 0.6 }}
          className="flex flex-col sm:flex-row gap-4 justify-center"
        >
          <Link
            href="/game/replay"
            className={buttonVariants({ size: "lg", className: "bg-[var(--color-gold-500)] text-slate-950 hover:bg-[var(--color-gold-400)] font-bold text-base px-8" })}
          >
            <Play className="mr-2 h-4 w-4" />
            Watch Demo
          </Link>
          <Link
            href="/characters"
            className={buttonVariants({ variant: "outline", size: "lg", className: "border-slate-700 text-slate-300 hover:bg-slate-800/50 text-base px-8" })}
          >
            <Users className="mr-2 h-4 w-4" />
            Meet Characters
          </Link>
        </motion.div>
      </motion.div>

      {/* Bottom attribution */}
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.2, duration: 0.8 }}
        className="absolute bottom-8 text-xs text-slate-600 font-[family-name:var(--font-geist-mono)]"
      >
        Powered by ANNIE — Multi-Agent Narrative Intelligence Engine
      </motion.p>
    </section>
  );
}
