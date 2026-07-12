#!/usr/bin/env python
"""Generate TownWorld replay read-model and static viewer artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from annie.town import write_town_replay_read_model, write_town_replay_viewer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a local TownWorld replay viewer.")
    parser.add_argument("manifest", type=Path, help="Path to a TownWorld run manifest.json")
    parser.add_argument("--read-model", type=Path, default=None)
    parser.add_argument("--viewer-dir", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    read_model_path = write_town_replay_read_model(args.manifest, args.read_model)
    paths = write_town_replay_viewer(
        args.manifest,
        args.viewer_dir,
        read_model_path=read_model_path,
    )
    print(f"Read model: {read_model_path}")
    print(f"Viewer: {paths['viewer_index']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
