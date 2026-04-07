"use client";

import { Play, Pause, SkipBack, SkipForward } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { PLAYBACK_SPEEDS } from "@/lib/constants";
import { useReplayEngine } from "@/hooks/useReplayEngine";

export function PlaybackControls() {
  const { play, pause, seek, setSpeed, isPlaying, currentTurnIndex, totalTurns, playbackSpeed } =
    useReplayEngine();

  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-2 backdrop-blur-sm">
      {/* Transport */}
      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 text-slate-400 hover:text-foreground"
        onClick={() => seek(0)}
      >
        <SkipBack className="h-4 w-4" />
      </Button>

      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 text-[var(--color-gold-500)] hover:text-[var(--color-gold-400)]"
        onClick={isPlaying ? pause : play}
      >
        {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
      </Button>

      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 text-slate-400 hover:text-foreground"
        onClick={() => seek(totalTurns - 1)}
      >
        <SkipForward className="h-4 w-4" />
      </Button>

      {/* Timeline */}
      <div className="flex-1 px-2">
        <Slider
          value={[Math.max(0, currentTurnIndex)]}
          max={Math.max(0, totalTurns - 1)}
          step={1}
          onValueChange={(val) => seek(Array.isArray(val) ? val[0] : val)}
          className="cursor-pointer"
        />
      </div>

      {/* Turn counter */}
      <span className="min-w-[60px] text-right font-[family-name:var(--font-geist-mono)] text-xs text-slate-500">
        {Math.max(0, currentTurnIndex + 1)} / {totalTurns}
      </span>

      {/* Speed */}
      <div className="flex items-center gap-1 border-l border-slate-800 pl-3">
        {PLAYBACK_SPEEDS.map((s) => (
          <button
            key={s}
            onClick={() => setSpeed(s)}
            className={`rounded px-1.5 py-0.5 font-[family-name:var(--font-geist-mono)] text-xs transition-colors ${
              playbackSpeed === s
                ? "bg-[var(--color-gold-500)]/20 text-[var(--color-gold-500)]"
                : "text-slate-600 hover:text-slate-300"
            }`}
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
}
