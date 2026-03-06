#!/usr/bin/env python3
"""Stage 4 runtime worker loop with heartbeat/stall handling."""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from runtime.state_machine import RuntimeStateMachine, TransitionRecord


class RuntimeWorker:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.sm = RuntimeStateMachine(root_dir)

    def process_once(self) -> List[TransitionRecord]:
        transitions: List[TransitionRecord] = []
        now = datetime.now(timezone.utc)
        for path in sorted(self.sm.state_dir.glob("*.json")):
            run = self.sm.load_run(path.stem)
            if run.is_terminal:
                continue
            if not self.sm.is_stalled(run, now):
                continue

            run.heartbeat_missed += 1
            self.sm.persist_run(run)

            if run.current_state == "blocked_platform":
                transition = self.sm.step(run, "recovery_failed_or_caps_exceeded")
            else:
                transition = self.sm.step(run, "platform_error")
            transitions.append(transition)
        return transitions

    def run_loop(self, *, max_iterations: int = 0, sleep_seconds: int = 5) -> None:
        iteration = 0
        while True:
            transitions = self.process_once()
            if transitions:
                print(f"runtime-worker: applied {len(transitions)} transition(s)")
            iteration += 1
            if max_iterations > 0 and iteration >= max_iterations:
                return
            time.sleep(sleep_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 4 runtime worker.")
    parser.add_argument("--root", default="/Users/ai/SuperSystemV2", help="Project root directory")
    parser.add_argument("--once", action="store_true", help="Process one cycle and exit")
    parser.add_argument("--max-iterations", type=int, default=0, help="Max loop iterations (0=forever)")
    parser.add_argument("--sleep-seconds", type=int, default=5, help="Sleep between cycles")
    args = parser.parse_args()

    worker = RuntimeWorker(Path(args.root))
    if args.once:
        transitions = worker.process_once()
        print(f"runtime-worker: applied {len(transitions)} transition(s)")
        return 0

    worker.run_loop(max_iterations=args.max_iterations, sleep_seconds=args.sleep_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
