import { create } from "zustand";
import type {
  CharacterProfile,
  ClueData,
  DialogueEntry,
  LiveGameStatus,
  PhaseData,
  ReplayData,
  SocialGraphData,
  SSEEvent,
  ThinkingIndicatorData,
  TruthRevealData,
  VoteResults,
} from "@/lib/types";

interface GameStore {
  // data
  mode: "idle" | "replay" | "live";
  characters: CharacterProfile[];
  phases: PhaseData[];
  allDialogue: DialogueEntry[];
  allClues: ClueData[];
  socialGraphSnapshots: { turn_index: number; graph: SocialGraphData }[];
  voteResults: VoteResults | null;
  truthReveal: TruthRevealData | null;

  // playback state
  currentTurnIndex: number;
  totalTurns: number;
  isPlaying: boolean;
  playbackSpeed: number;
  selectedNpc: string | null;

  // derived (computed from currentTurnIndex)
  dialogue: DialogueEntry[];
  currentPhase: PhaseData | null;
  socialGraph: SocialGraphData;
  clues: ClueData[];

  // live game state
  liveStatus: LiveGameStatus;
  thinkingNpc: ThinkingIndicatorData | null;
  gameId: string | null;
  liveError: string | null;
  initializingMessage: string;

  // actions
  loadReplay: (data: ReplayData) => void;
  setCurrentTurn: (index: number) => void;
  advanceTurn: () => void;
  selectNpc: (name: string | null) => void;
  setPlaying: (playing: boolean) => void;
  setPlaybackSpeed: (speed: number) => void;
  reset: () => void;
  // live game actions
  startLiveGame: () => Promise<void>;
  resumeLiveGame: (gameId: string) => void;
  handleSSEEvent: (event: SSEEvent) => void;
  setLiveStatus: (status: LiveGameStatus) => void;
}

function deriveState(
  allDialogue: DialogueEntry[],
  allClues: ClueData[],
  phases: PhaseData[],
  snapshots: { turn_index: number; graph: SocialGraphData }[],
  turnIndex: number,
) {
  const dialogue = allDialogue.filter((d) => d.turn_index <= turnIndex);
  const currentEntry = allDialogue.find((d) => d.turn_index === turnIndex);
  const currentPhaseName = currentEntry?.phase ?? phases[0]?.name;
  const currentPhase = phases.find((p) => p.name === currentPhaseName) ?? phases[0] ?? null;
  const clues = allClues.map((c) => ({
    ...c,
    discovered: c.discovered_at_turn !== null && c.discovered_at_turn <= turnIndex,
  }));

  // Find the latest snapshot at or before this turn
  let socialGraph: SocialGraphData = { nodes: [], edges: [] };
  for (let i = snapshots.length - 1; i >= 0; i--) {
    if (snapshots[i].turn_index <= turnIndex) {
      socialGraph = snapshots[i].graph;
      break;
    }
  }

  return { dialogue, currentPhase, socialGraph, clues };
}

const emptyGraph: SocialGraphData = { nodes: [], edges: [] };

export const useGameState = create<GameStore>((set, get) => ({
  mode: "idle",
  characters: [],
  phases: [],
  allDialogue: [],
  allClues: [],
  socialGraphSnapshots: [],
  voteResults: null,
  truthReveal: null,
  currentTurnIndex: -1,
  totalTurns: 0,
  isPlaying: false,
  playbackSpeed: 1,
  selectedNpc: null,
  dialogue: [],
  currentPhase: null,
  socialGraph: emptyGraph,
  clues: [],
  // live game state
  liveStatus: "idle",
  thinkingNpc: null,
  gameId: null,
  liveError: null,
  initializingMessage: "",

  loadReplay: (data) => {
    const snapshots = data.social_graph_snapshots.map((s) => ({
      turn_index: s.turn_index,
      graph: s.graph,
    }));
    set({
      mode: "replay",
      characters: data.characters,
      phases: data.phases,
      allDialogue: data.dialogue,
      allClues: data.clues,
      socialGraphSnapshots: snapshots,
      voteResults: data.vote_results,
      truthReveal: data.truth_reveal,
      totalTurns: data.dialogue.length,
      currentTurnIndex: -1,
      isPlaying: false,
      ...deriveState(data.dialogue, data.clues, data.phases, snapshots, -1),
    });
  },

  setCurrentTurn: (index) => {
    const { allDialogue, allClues, phases, socialGraphSnapshots } = get();
    set({
      currentTurnIndex: index,
      ...deriveState(allDialogue, allClues, phases, socialGraphSnapshots, index),
    });
  },

  advanceTurn: () => {
    const { currentTurnIndex, totalTurns } = get();
    if (currentTurnIndex < totalTurns - 1) {
      get().setCurrentTurn(currentTurnIndex + 1);
    } else {
      set({ isPlaying: false });
    }
  },

  selectNpc: (name) => set({ selectedNpc: name }),
  setPlaying: (playing) => set({ isPlaying: playing }),
  setPlaybackSpeed: (speed) => set({ playbackSpeed: speed }),

  reset: () =>
    set({
      mode: "idle",
      characters: [],
      phases: [],
      allDialogue: [],
      allClues: [],
      socialGraphSnapshots: [],
      voteResults: null,
      truthReveal: null,
      currentTurnIndex: -1,
      totalTurns: 0,
      isPlaying: false,
      playbackSpeed: 1,
      selectedNpc: null,
      dialogue: [],
      currentPhase: null,
      socialGraph: emptyGraph,
      clues: [],
      liveStatus: "idle",
      thinkingNpc: null,
      gameId: null,
      liveError: null,
      initializingMessage: "",
    }),

  // ── Live game actions ──────────────────────────────────────────────────────

  startLiveGame: async () => {
    const backendUrl =
      typeof process !== "undefined" && process.env.NEXT_PUBLIC_BACKEND_URL
        ? process.env.NEXT_PUBLIC_BACKEND_URL
        : "http://localhost:8000";

    set({ mode: "live", liveStatus: "initializing", liveError: null, initializingMessage: "连接中..." });
    let resp: Response;
    try {
      resp = await fetch(`${backendUrl}/api/games`, { method: "POST" });
    } catch (err) {
      set({ liveStatus: "error", liveError: "无法连接到后端服务，请确认已启动" });
      throw err;
    }
    if (!resp.ok) {
      set({ liveStatus: "error", liveError: `后端返回错误: ${resp.status}` });
      throw new Error(`Backend error: ${resp.status}`);
    }
    const { game_id } = await resp.json();
    // Persist so the resume-check on next page load can find it.
    try { localStorage.setItem("annie_game_id", game_id); } catch { /* ignore */ }
    set({ gameId: game_id });
  },

  resumeLiveGame: (gameId: string) => {
    // Skip POST /api/games — just reconnect SSE to the existing session.
    set({
      mode: "live",
      liveStatus: "initializing",
      liveError: null,
      initializingMessage: "正在恢复游戏...",
      gameId,
    });
  },

  setLiveStatus: (status) => set({ liveStatus: status }),

  handleSSEEvent: (event) => {
    switch (event.type) {
      case "initializing":
        set({ liveStatus: "initializing", initializingMessage: event.message });
        break;

      case "game_ready": {
        const { characters, phases, clues, social_graph } = event;
        const initialSnapshots = social_graph
          ? [{ turn_index: -1, graph: social_graph }]
          : [];
        set({
          liveStatus: "running",
          characters,
          phases,
          allClues: clues,
          allDialogue: [],
          socialGraphSnapshots: initialSnapshots,
          voteResults: null,
          truthReveal: null,
          totalTurns: 0,
          currentTurnIndex: -1,
          thinkingNpc: null,
          ...deriveState([], clues, phases, initialSnapshots, -1),
        });
        break;
      }

      case "phase_change":
        set((s) => ({
          phases: s.phases.map((p) =>
            p.name === event.phase_name
              ? { ...p, status: "active" as const, announcement: event.announcement }
              : p.status === "active"
              ? { ...p, status: "completed" as const }
              : p
          ),
        }));
        break;

      case "npc_thinking":
        set({
          liveStatus: "npc_thinking",
          thinkingNpc: {
            npc: event.npc,
            phase: event.phase,
            round: event.round,
            startedAt: Date.now(),
          },
        });
        break;

      case "dialogue": {
        const entry: DialogueEntry = {
          turn_index: event.turn_index,
          npc: event.npc,
          inner_thoughts: event.inner_thoughts,
          spoken_words: event.spoken_words,
          vote: event.vote,
          phase: event.phase,
          timestamp: Date.now(),
        };
        set((s) => {
          const allDialogue = [...s.allDialogue, entry];
          const totalTurns = allDialogue.length;
          const currentTurnIndex = totalTurns - 1;
          return {
            liveStatus: "running",
            thinkingNpc: null,
            allDialogue,
            totalTurns,
            currentTurnIndex,
            ...deriveState(allDialogue, s.allClues, s.phases, s.socialGraphSnapshots, currentTurnIndex),
          };
        });
        break;
      }

      case "clue_discovered": {
        const updatedClue = event.clue;
        set((s) => {
          const allClues = s.allClues.map((c) =>
            c.id === updatedClue.id ? { ...c, ...updatedClue } : c
          );
          return {
            allClues,
            clues: allClues.map((c) => ({
              ...c,
              discovered:
                c.discovered_at_turn !== null &&
                c.discovered_at_turn <= s.currentTurnIndex,
            })),
          };
        });
        break;
      }

      case "social_graph_snapshot": {
        set((s) => {
          const snapshots = [
            ...s.socialGraphSnapshots,
            { turn_index: event.turn_index, graph: event.graph },
          ];
          return {
            socialGraphSnapshots: snapshots,
            socialGraph: event.graph,
          };
        });
        break;
      }

      case "game_over":
        set({
          liveStatus: "game_over",
          thinkingNpc: null,
          voteResults: event.vote_results,
          truthReveal: event.truth_reveal,
        });
        break;
    }
  },
}));
