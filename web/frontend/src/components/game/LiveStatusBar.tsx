"use client";

import { useGameState } from "@/hooks/useGameState";
import { NPC_TEXT_COLORS } from "@/lib/constants";

export function LiveStatusBar() {
  const liveStatus = useGameState((s) => s.liveStatus);
  const thinkingNpc = useGameState((s) => s.thinkingNpc);
  const totalTurns = useGameState((s) => s.totalTurns);

  const statusMessage = () => {
    if (liveStatus === "npc_thinking" && thinkingNpc) {
      return (
        <span className={NPC_TEXT_COLORS[thinkingNpc.npc] ?? "text-slate-400"}>
          {thinkingNpc.npc} 正在思考...
        </span>
      );
    }
    if (liveStatus === "running") return <span className="text-slate-400">等待下一位角色...</span>;
    if (liveStatus === "game_over") return <span className="text-amber-400">游戏结束</span>;
    return null;
  };

  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-2 backdrop-blur-sm">
      {/* Pulsing LIVE badge */}
      <span className="flex items-center gap-1.5 text-xs font-bold text-red-400">
        <span className="inline-block h-2 w-2 rounded-full bg-red-500 animate-pulse" />
        LIVE
      </span>

      {/* Status message */}
      <span className="flex-1 text-xs">{statusMessage()}</span>

      {/* Turn counter */}
      <span className="font-[family-name:var(--font-geist-mono)] text-xs text-slate-500">
        {totalTurns} 轮对话
      </span>
    </div>
  );
}
