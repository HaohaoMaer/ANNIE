# 双重暗影 — Handoff Package

**Schema versions**: truth v1, npc v1, evidence v1
**Package generated**: 2026-04-20T11:44:46.329207Z
**Case language**: zh

## Quick orientation

- Reading the case as a human? → `script.md`
- Full spoiler walkthrough? → `dm_handbook.md`
- Showing a player the opening? → `player_briefing.md`
- Building an NPC roleplay agent? → feed `npcs/<id>.json` as agent context.
  **Never** show `truth.json` to NPC agents.
- Building a verdict scoring agent? → feed `truth.json#/judgement_rubric` to the
  scoring agent.

## File map

| File | Purpose | Audience |
|------|---------|----------|
| `truth.json` | Ground truth (immutable) | Scoring agent only |
| `script.md` | Literary screenplay | Author / solo reader |
| `dm_handbook.md` | Full spoiler guide | DM / facilitator |
| `player_briefing.md` | Spoiler-free intro | Player |
| `timeline.md` | Master timeline table | DM / scoring agent |
| `evidence_graph.md` | Evidence relationships | DM / designer |
| `npcs/*.json` | Individual NPC profiles | Roleplay subagents |
| `evidence/evidence.json` | Full evidence set | Both dev layers |
| `manifest.json` | Package inventory + checksums | CI / integrity checks |

## Integrity

All files listed in `manifest.json` have SHA256 checksums. Re-run
`package_handoff.py --verify` to verify integrity and spoiler-leak checks.

## Known design notes

- The case was created under the `detective-case-creator` skill's phase pipeline
  and passed all seven reviewer gates at the time of packaging.
- If you edit files after packaging, the manifest checksums will stop matching —
  re-run the packager.
