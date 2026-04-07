// TypeScript interfaces mirroring ANNIE backend data models

export interface CharacterProfile {
  name: string;
  identity: string;
  background: string;
  personality_traits: string[];
  values: string[];
  goals: string[];
  secrets: string[];
  relationships: Record<string, string>;
  is_murderer: boolean;
  color: string;
}

export interface DialogueEntry {
  turn_index: number;
  npc: string;
  inner_thoughts: string;
  spoken_words: string;
  vote: string | null;
  phase: string;
  emotional_state?: { primary: string; intensity: number };
  timestamp: number;
}

export interface GraphNode {
  id: string;
  label: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  trust: number;
  familiarity: number;
  emotional_valence: number;
  type: string;
  status: string;
}

export interface SocialGraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SocialGraphSnapshot {
  turn_index: number;
  phase: string;
  graph: SocialGraphData;
}

export interface ClueData {
  id: string;
  category: string;
  file_name: string;
  content: string;
  discovered: boolean;
  discovered_by: string | null;
  discovered_at_turn: number | null;
  importance: number;
}

export interface PhaseData {
  id: string;
  name: string;
  description: string;
  allowed_actions: string[];
  npc_order: string[];
  objectives: string[];
  status: "upcoming" | "active" | "completed";
  announcement?: string;
}

export interface VoteResults {
  votes: Record<string, string>;
  counts: Record<string, number>;
  top_suspect: string;
  real_murderer: string;
  is_correct: boolean;
}

export interface TruthRevealData {
  real_murderer: string;
  murder_method: string;
  narration: string;
  is_correct: boolean;
}

export interface GameMetadata {
  game_name: string;
  game_name_en: string;
  total_turns: number;
  total_phases: number;
  npc_count: number;
  created_at: string;
}

export interface ReplayData {
  metadata: GameMetadata;
  characters: CharacterProfile[];
  phases: PhaseData[];
  dialogue: DialogueEntry[];
  social_graph_snapshots: SocialGraphSnapshot[];
  clues: ClueData[];
  vote_results: VoteResults;
  truth_reveal: TruthRevealData;
}

// ── Live game types ──────────────────────────────────────────────────────────

export type LiveGameStatus =
  | "idle"
  | "initializing"
  | "running"
  | "npc_thinking"
  | "game_over"
  | "error";

export interface ThinkingIndicatorData {
  npc: string;
  phase: string;
  round: number;
  startedAt: number; // Date.now()
}

// SSE event payloads

export interface SSEInitializing {
  type: "initializing";
  message: string;
}

export interface SSEGameReady {
  type: "game_ready";
  game_id: string;
  characters: CharacterProfile[];
  phases: PhaseData[];
  clues: ClueData[];
  social_graph: SocialGraphData;
}

export interface SSEPhaseChange {
  type: "phase_change";
  phase_name: string;
  phase_description: string;
  announcement: string;
}

export interface SSENpcThinking {
  type: "npc_thinking";
  npc: string;
  phase: string;
  round: number;
}

export interface SSEDialogue {
  type: "dialogue";
  turn_index: number;
  npc: string;
  inner_thoughts: string;
  spoken_words: string;
  vote: string | null;
  phase: string;
}

export interface SSEGameOver {
  type: "game_over";
  vote_results: VoteResults;
  truth_reveal: TruthRevealData;
}

export interface SSEClueDiscovered {
  type: "clue_discovered";
  clue: ClueData;
}

export interface SSESocialGraphSnapshot {
  type: "social_graph_snapshot";
  turn_index: number;
  phase: string;
  graph: SocialGraphData;
}

export type SSEEvent =
  | SSEInitializing
  | SSEGameReady
  | SSEPhaseChange
  | SSENpcThinking
  | SSEDialogue
  | SSEGameOver
  | SSEClueDiscovered
  | SSESocialGraphSnapshot;
