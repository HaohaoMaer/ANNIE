"use client";

import { useState, useMemo } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useGameState } from "@/hooks/useGameState";
import { PhaseHeader } from "./PhaseHeader";
import { PlaybackControls } from "./PlaybackControls";
import { LiveStatusBar } from "./LiveStatusBar";
import { DialogueStream } from "./DialogueStream";
import { Sidebar } from "./Sidebar";
import { InnerThoughts } from "./InnerThoughts";
import { SocialGraphViz } from "@/components/social-graph/SocialGraphViz";
import { ClueBoard } from "@/components/clues/ClueBoard";
import { VoteReveal } from "@/components/voting/VoteReveal";
import { TruthReveal } from "@/components/truth/TruthReveal";

interface GameBoardProps {
  isLive?: boolean;
}

export function GameBoard({ isLive = false }: GameBoardProps) {
  const characters = useGameState((s) => s.characters);
  const phases = useGameState((s) => s.phases);
  const currentPhase = useGameState((s) => s.currentPhase);
  const dialogue = useGameState((s) => s.dialogue);
  const currentTurnIndex = useGameState((s) => s.currentTurnIndex);
  const socialGraph = useGameState((s) => s.socialGraph);
  const clues = useGameState((s) => s.clues);
  const voteResults = useGameState((s) => s.voteResults);
  const truthReveal = useGameState((s) => s.truthReveal);
  const selectedNpc = useGameState((s) => s.selectedNpc);
  const selectNpc = useGameState((s) => s.selectNpc);
  const totalTurns = useGameState((s) => s.totalTurns);
  const liveStatus = useGameState((s) => s.liveStatus);
  const thinkingNpc = useGameState((s) => s.thinkingNpc);

  const [thoughtsNpc, setThoughtsNpc] = useState<string | null>(null);

  // Find the latest dialogue entry for the selected thought NPC
  const thoughtEntry = useMemo(() => {
    if (!thoughtsNpc) return null;
    const entries = dialogue.filter((d) => d.npc === thoughtsNpc);
    return entries.length > 0 ? entries[entries.length - 1] : null;
  }, [dialogue, thoughtsNpc]);

  // Show final screens:
  // - replay mode: after all turns played
  // - live mode: when game_over event received
  const isGameOver = isLive ? liveStatus === "game_over" : currentTurnIndex >= totalTurns - 1;
  const showVotes = voteResults && isGameOver;
  const showTruth = truthReveal && isGameOver;

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
      {/* Top bar */}
      <div className="flex items-center gap-3 border-b border-slate-800 bg-slate-950/80 px-4 py-2">
        <div className="flex-1">
          <PhaseHeader phases={phases} currentPhase={currentPhase} />
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar */}
        <Sidebar
          characters={characters}
          phases={phases}
          currentPhase={currentPhase}
          selectedNpc={selectedNpc}
          onSelectNpc={selectNpc}
        />

        {/* Center: Dialogue */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {showVotes || showTruth ? (
            <div className="flex-1 overflow-y-auto p-6">
              {showVotes && voteResults && (
                <div className="mb-8">
                  <h3 className="mb-4 text-center text-lg font-bold text-[var(--color-gold-500)]">
                    Voting Results
                  </h3>
                  <VoteReveal results={voteResults} />
                </div>
              )}
              {showTruth && truthReveal && <TruthReveal truth={truthReveal} />}
            </div>
          ) : (
            <DialogueStream
              dialogue={dialogue}
              currentTurnIndex={currentTurnIndex}
              onRevealThoughts={(npc) =>
                setThoughtsNpc((prev) => (prev === npc ? null : npc))
              }
              thinkingNpc={isLive ? thinkingNpc : null}
            />
          )}

          {/* Bottom controls: playback controls for replay, live status bar for live */}
          <div className="border-t border-slate-800 bg-slate-950/80 px-4 py-2">
            {isLive ? <LiveStatusBar /> : <PlaybackControls />}
          </div>
        </div>

        {/* Right panel */}
        <aside className="hidden w-[360px] flex-col border-l border-slate-800 bg-slate-950/80 lg:flex">
          <Tabs defaultValue="thoughts" className="flex flex-1 flex-col">
            <TabsList className="mx-4 mt-3 bg-slate-900/60">
              <TabsTrigger value="thoughts" className="text-xs">
                Inner Thoughts
              </TabsTrigger>
              <TabsTrigger value="graph" className="text-xs">
                Social Graph
              </TabsTrigger>
              <TabsTrigger value="clues" className="text-xs">
                Clues
              </TabsTrigger>
            </TabsList>

            <TabsContent value="thoughts" className="flex-1 overflow-y-auto p-4">
              <InnerThoughts
                entry={thoughtEntry}
                onClose={() => setThoughtsNpc(null)}
              />
              {!thoughtEntry && (
                <p className="text-center text-xs text-slate-600 mt-8">
                  Click the eye icon on any dialogue bubble to peek at their inner thoughts.
                </p>
              )}
            </TabsContent>

            <TabsContent value="graph" className="flex-1 p-2">
              <SocialGraphViz
                graphData={socialGraph}
                highlightNpc={selectedNpc}
              />
            </TabsContent>

            <TabsContent value="clues" className="flex-1 overflow-y-auto p-2">
              <ClueBoard clues={clues} />
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  );
}
