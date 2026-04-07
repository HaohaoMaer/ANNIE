"use client";

import { useEffect, useState } from "react";
import { FogOverlay } from "@/components/layout/FogOverlay";
import { Header } from "@/components/layout/Header";
import { GameBoard } from "@/components/game/GameBoard";
import { useGameLive } from "@/hooks/useGameLive";
import { useGameState } from "@/hooks/useGameState";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

interface ResumeCandidate {
  gameId: string;
  turnCount: number;
}

export default function LivePage() {
  const { start, liveStatus, initializingMessage } = useGameLive();
  const liveError = useGameState((s) => s.liveError);
  const resumeLiveGame = useGameState((s) => s.resumeLiveGame);

  // Non-null while we're waiting for the user to choose resume vs new game.
  const [resumeCandidate, setResumeCandidate] = useState<ResumeCandidate | null>(null);
  const [checkingResume, setCheckingResume] = useState(true);

  // On mount: check whether there is an in-progress session the user can resume.
  useEffect(() => {
    let cancelled = false;

    async function checkActive() {
      try {
        // First try the saved game_id from the last session.
        const savedId = localStorage.getItem("annie_game_id");
        if (savedId) {
          const res = await fetch(`${BACKEND_URL}/api/games/${savedId}/status`);
          if (res.ok) {
            const data = await res.json();
            if (!cancelled && data.status !== "game_over" && data.status !== "error" && data.status !== "ended") {
              setResumeCandidate({ gameId: savedId, turnCount: data.turn_count });
              return;
            }
          }
        }

        // Fallback: ask backend for any active game (handles reload after hard refresh).
        const res = await fetch(`${BACKEND_URL}/api/games/active`);
        if (res.ok) {
          const data = await res.json();
          if (!cancelled && data.game_id) {
            setResumeCandidate({ gameId: data.game_id, turnCount: data.turn_count });
            return;
          }
        }
      } catch {
        // Backend unreachable — show normal start screen.
      } finally {
        if (!cancelled) setCheckingResume(false);
      }
    }

    checkActive();
    return () => { cancelled = true; };
  }, []);

  // Dismiss the loading spinner once we know there's nothing to resume.
  useEffect(() => {
    if (resumeCandidate !== null) setCheckingResume(false);
  }, [resumeCandidate]);

  // ── Resume dialog ──────────────────────────────────────────────────────────
  if (checkingResume) {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="flex items-center gap-3 text-slate-500">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-amber-500 border-t-transparent" />
            <span className="text-sm">检查游戏状态...</span>
          </div>
        </div>
      </>
    );
  }

  if (resumeCandidate && liveStatus === "idle") {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="rounded-xl border border-amber-500/30 bg-slate-900/80 p-8 text-center space-y-5 max-w-sm shadow-xl backdrop-blur">
            <div className="text-3xl">🚂</div>
            <h2 className="text-xl font-bold text-[var(--color-gold-500)]">
              发现未完成的游戏
            </h2>
            <p className="text-sm text-slate-400">
              游戏进行到第{" "}
              <span className="text-amber-400 font-semibold">
                {resumeCandidate.turnCount}
              </span>{" "}
              轮，是否继续？
            </p>
            <div className="flex gap-3 justify-center pt-1">
              <button
                onClick={() => resumeLiveGame(resumeCandidate.gameId)}
                className="flex-1 rounded-lg bg-amber-500 px-4 py-2.5 text-sm font-bold text-slate-950 hover:bg-amber-400 transition-colors"
              >
                继续游戏
              </button>
              <button
                onClick={() => {
                  localStorage.removeItem("annie_game_id");
                  setResumeCandidate(null);
                }}
                className="flex-1 rounded-lg border border-slate-600 px-4 py-2.5 text-sm text-slate-300 hover:border-slate-400 hover:text-slate-100 transition-colors"
              >
                重新开始
              </button>
            </div>
          </div>
        </div>
      </>
    );
  }

  // ── Normal start screen ────────────────────────────────────────────────────
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
