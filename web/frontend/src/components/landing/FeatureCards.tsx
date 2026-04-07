"use client";

import { motion } from "framer-motion";
import { Brain, Network, Eye } from "lucide-react";

const features = [
  {
    icon: Brain,
    title: "Inner Thoughts vs. Speech",
    titleCn: "内心独白 vs 公开发言",
    description:
      "Each NPC has private reasoning driven by secrets and motivations. What they say may differ completely from what they think.",
  },
  {
    icon: Network,
    title: "Dynamic Social Graph",
    titleCn: "动态社交图谱",
    description:
      "Trust, familiarity, and emotions evolve in real-time. Information propagates through the social network with distortion.",
  },
  {
    icon: Eye,
    title: "Belief & Perception",
    titleCn: "信念与认知系统",
    description:
      "NPCs evaluate information credibility based on source trust. The same event is perceived differently by each character.",
  },
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.15 } },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5 } },
};

export function FeatureCards() {
  return (
    <motion.section
      variants={container}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-80px" }}
      className="relative z-10 mx-auto grid max-w-5xl grid-cols-1 gap-6 px-6 pb-24 sm:grid-cols-3"
    >
      {features.map((f) => (
        <motion.div
          key={f.title}
          variants={item}
          className="group rounded-lg border border-amber-900/20 bg-slate-900/60 p-6 backdrop-blur-sm transition-colors hover:border-amber-500/40"
        >
          <f.icon className="mb-4 h-8 w-8 text-[var(--color-gold-500)] opacity-80 group-hover:opacity-100 transition-opacity" />
          <h3 className="text-lg font-bold text-slate-100 mb-1">{f.titleCn}</h3>
          <p className="text-xs text-[var(--color-gold-600)]/60 font-[family-name:var(--font-geist-mono)] mb-3">
            {f.title}
          </p>
          <p className="text-sm text-slate-400 leading-relaxed">{f.description}</p>
        </motion.div>
      ))}
    </motion.section>
  );
}
