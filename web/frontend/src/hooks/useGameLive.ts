"use client";

import { useEffect, useRef } from "react";
import { useGameState } from "./useGameState";
import type { SSEEvent } from "@/lib/types";

// The POST can use the Next.js proxy (/api/games → localhost:8000).
// The SSE stream MUST connect directly to the backend — Next.js's dev-server
// proxy buffers text/event-stream responses, so events would never arrive
// in real-time if we used the proxy for EventSource.
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

/**
 * Manages the SSE connection for a live game session.
 *
 * Usage:
 *   const { start, liveStatus, thinkingNpc } = useGameLive();
 *   // Call start() to create a game and begin streaming.
 */
export function useGameLive() {
  const startLiveGame = useGameState((s) => s.startLiveGame);
  const handleSSEEvent = useGameState((s) => s.handleSSEEvent);
  const setLiveStatus = useGameState((s) => s.setLiveStatus);
  const gameId = useGameState((s) => s.gameId);
  const liveStatus = useGameState((s) => s.liveStatus);
  const thinkingNpc = useGameState((s) => s.thinkingNpc);
  const initializingMessage = useGameState((s) => s.initializingMessage);

  const esRef = useRef<EventSource | null>(null);

  // Open the SSE stream once we have a gameId.
  useEffect(() => {
    if (!gameId) return;

    // Close any previous connection.
    esRef.current?.close();

    // Connect DIRECTLY to the backend — bypasses Next.js proxy buffering.
    const es = new EventSource(`${BACKEND_URL}/api/games/${gameId}/stream`);
    esRef.current = es;

    const handleEvent = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data) as SSEEvent;
        handleSSEEvent(event);
      } catch {
        // Ignore malformed events.
      }
    };

    const eventTypes = [
      "initializing",
      "game_ready",
      "phase_change",
      "npc_thinking",
      "dialogue",
      "game_over",
      "clue_discovered",
      "social_graph_snapshot",
      "heartbeat",
      "error",
    ];
    eventTypes.forEach((t) => es.addEventListener(t, handleEvent));

    es.onerror = () => {
      // onerror fires when the backend is unreachable or the stream ends
      // with an error. Close and show error to avoid silent reconnect loops.
      es.close();
      setLiveStatus("error");
    };

    return () => {
      eventTypes.forEach((t) => es.removeEventListener(t, handleEvent));
      es.close();
    };
  }, [gameId, handleSSEEvent, setLiveStatus]);

  const start = async () => {
    try {
      await startLiveGame();
    } catch {
      setLiveStatus("error");
    }
  };

  const disconnect = () => {
    esRef.current?.close();
    esRef.current = null;
  };

  return { start, disconnect, liveStatus, thinkingNpc, initializingMessage };
}
