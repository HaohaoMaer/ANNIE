"use client";

import { FogOverlay } from "@/components/layout/FogOverlay";
import { Header } from "@/components/layout/Header";
import { GameBoard } from "@/components/game/GameBoard";
import { useGameLive } from "@/hooks/useGameLive";
import { useGameState } from "@/hooks/useGameState";

export default function LivePage() {
  const { start, liveStatus, initializingMessage } = useGameLive();
  const liveError = useGameState((s) => s.liveError);

  if (liveStatus === "idle") {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="text-center space-y-6">
            <h2 className="text-2xl font-bold text-[var(--color-gold-500)]">
              午夜列车 — 实时游戏
            </h2>
            <p className="text-sm text-slate-400 max-w-sm">
              AI角色将实时对话推理，游戏需要约15-20分钟。
              <br />
              请确保后端服务已启动。
            </p>
            <button
              onClick={start}
              className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-6 py-3 text-sm font-bold text-slate-950 hover:bg-amber-400 transition-colors"
            >
              <span className="inline-block h-2 w-2 rounded-full bg-red-600 animate-pulse" />
              开始新游戏
            </button>
          </div>
        </div>
      </>
    );
  }

  if (liveStatus === "initializing") {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="flex items-center gap-3 text-slate-500">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-amber-500 border-t-transparent" />
            <span className="text-sm">
              {initializingMessage || "正在准备游戏..."}
            </span>
          </div>
        </div>
      </>
    );
  }

  if (liveStatus === "error") {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="text-center space-y-3 max-w-sm">
            <p className="text-red-400 font-bold">连接失败</p>
            {liveError && (
              <p className="text-xs text-slate-400">{liveError}</p>
            )}
            <p className="text-xs text-slate-500">
              请先启动后端服务（使用 annie 环境）：
            </p>
            <code className="block text-xs bg-slate-800 px-3 py-2 rounded text-amber-400 text-left">
              conda activate annie<br />
              uvicorn web.backend.main:app --port 8000
            </code>
            <div className="pt-2">
              <button
                onClick={start}
                className="text-sm text-amber-400 hover:text-amber-300 underline"
              >
                重试
              </button>
            </div>
          </div>
        </div>
      </>
    );
  }

  // running / npc_thinking / game_over → show the game board
  return (
    <>
      <FogOverlay intensity="low" />
      <Header />
      <main className="pt-14">
        <GameBoard isLive />
      </main>
    </>
  );
}
