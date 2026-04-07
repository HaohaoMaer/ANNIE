"use client";

import { useEffect, useRef } from "react";
import { useGameState } from "./useGameState";
import { DEFAULT_TURN_DURATION_MS } from "@/lib/constants";

export function useReplayEngine() {
  const isPlaying = useGameState((s) => s.isPlaying);
  const playbackSpeed = useGameState((s) => s.playbackSpeed);
  const currentTurnIndex = useGameState((s) => s.currentTurnIndex);
  const totalTurns = useGameState((s) => s.totalTurns);
  const advanceTurn = useGameState((s) => s.advanceTurn);
  const setPlaying = useGameState((s) => s.setPlaying);
  const setCurrentTurn = useGameState((s) => s.setCurrentTurn);
  const setPlaybackSpeed = useGameState((s) => s.setPlaybackSpeed);

  const intervalRef = useRef<ReturnType<typeof setInterval>>(null);

  useEffect(() => {
    if (isPlaying && currentTurnIndex < totalTurns - 1) {
      const ms = DEFAULT_TURN_DURATION_MS / playbackSpeed;
      intervalRef.current = setInterval(() => {
        advanceTurn();
      }, ms);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPlaying, playbackSpeed, currentTurnIndex, totalTurns, advanceTurn]);

  return {
    play: () => {
      if (currentTurnIndex >= totalTurns - 1) {
        setCurrentTurn(0);
      }
      setPlaying(true);
    },
    pause: () => setPlaying(false),
    seek: (index: number) => setCurrentTurn(Math.max(-1, Math.min(index, totalTurns - 1))),
    setSpeed: setPlaybackSpeed,
    isPlaying,
    currentTurnIndex,
    totalTurns,
    playbackSpeed,
  };
}
