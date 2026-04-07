"use client";

import { useEffect, useState } from "react";
import { FogOverlay } from "@/components/layout/FogOverlay";
import { Header } from "@/components/layout/Header";
import { GameBoard } from "@/components/game/GameBoard";
import { useGameState } from "@/hooks/useGameState";
import type { ReplayData } from "@/lib/types";

interface ReplayMeta {
  id: string;
  filename: string;
  game_name: string;
  game_name_en: string;
  created_at: string;
  total_turns: number;
  npc_count: number;
}

const BACKEND_URL =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_BACKEND_URL
    ? process.env.NEXT_PUBLIC_BACKEND_URL
    : "http://localhost:8000";

export default function ReplayPage() {
  const loadReplay = useGameState((s) => s.loadReplay);
  const mode = useGameState((s) => s.mode);
  const [error, setError] = useState<string | null>(null);
  const [replays, setReplays] = useState<ReplayMeta[] | null>(null);
  const [loading, setLoading] = useState(false);

  // Fetch the list of available replays on mount
  useEffect(() => {
    fetch(`${BACKEND_URL}/api/replays`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => setReplays(data.replays ?? []))
      .catch((e) => setError(`无法加载回放列表: ${e.message}`));
  }, []);

  const handleSelectReplay = (id: string) => {
    setLoading(true);
    setError(null);
    fetch(`${BACKEND_URL}/api/replays/${id}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: ReplayData) => {
        loadReplay(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(`加载失败: ${e.message}`);
        setLoading(false);
      });
  };

  // Show replay board if a replay is loaded
  if (mode === "replay") {
    return (
      <>
        <FogOverlay intensity="low" />
        <Header />
        <main className="pt-14">
          <GameBoard />
        </main>
      </>
    );
  }

  if (error) {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="text-center">
            <p className="text-lg text-red-400 mb-2">加载失败</p>
            <p className="text-sm text-slate-500">{error}</p>
            <p className="text-xs text-slate-600 mt-4">
              请确认后端服务已启动：
              <code className="bg-slate-800 px-1.5 py-0.5 rounded text-amber-400 ml-1">
                uvicorn web.backend.main:app --port 8000
              </code>
            </p>
          </div>
        </div>
      </>
    );
  }

  if (loading) {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="flex items-center gap-3 text-slate-500">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-amber-500 border-t-transparent" />
            <span className="text-sm">正在加载回放数据...</span>
          </div>
        </div>
      </>
    );
  }

  if (replays === null) {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="flex items-center gap-3 text-slate-500">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-amber-500 border-t-transparent" />
            <span className="text-sm">正在获取回放列表...</span>
          </div>
        </div>
      </>
    );
  }

  if (replays.length === 0) {
    return (
      <>
        <Header />
        <div className="flex flex-1 items-center justify-center pt-14">
          <div className="text-center">
            <p className="text-lg text-slate-400 mb-2">暂无回放记录</p>
            <p className="text-sm text-slate-500">
              完成一局游戏后，回放记录将自动保存在此处。
            </p>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <FogOverlay intensity="low" />
      <Header />
      <main className="pt-14 flex flex-col items-center py-12 px-4">
        <h1 className="text-2xl font-bold text-amber-400 mb-2">选择回放</h1>
        <p className="text-sm text-slate-500 mb-8">选择一局历史游戏进行回放</p>
        <div className="w-full max-w-2xl space-y-3">
          {replays.map((r) => (
            <button
              key={r.id}
              onClick={() => handleSelectReplay(r.id)}
              className="w-full flex items-center justify-between rounded-lg border border-slate-700 bg-slate-900 px-5 py-4 text-left hover:border-amber-500/60 hover:bg-slate-800 transition-colors"
            >
              <div>
                <p className="font-semibold text-slate-200">{r.game_name}</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  {r.npc_count} 名角色 · {r.total_turns} 轮对话
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-slate-500">
                  {r.created_at ? new Date(r.created_at).toLocaleString("zh-CN") : "未知时间"}
                </p>
                <p className="text-xs text-amber-500/80 mt-1">点击回放 →</p>
              </div>
            </button>
          ))}
        </div>
      </main>
    </>
  );
}
