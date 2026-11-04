"""STORY-03-04: live scenario-mode check — scripted, scenario-appropriate
user turns (not the generic passive stress-test lines in
`live_persona_spotcheck.py`) to verify a scenario's opening line and
`character_role_prompt_addendum`/`goal` actually shape the conversation.

Usage:
    uv run python scripts/live_scenario_check.py --scenario-id coffee_shop_test
"""
from __future__ import annotations

import argparse
import asyncio

from live_persona_spotcheck import print_transcript, run

COFFEE_SHOP_LINES = [
    "Hi.",
    "Can I get a medium latte?",
    "Oat milk, please.",
    "Sure, extra hot.",
    "It's Andrey.",
    "That's all, thanks.",
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/session")
    parser.add_argument("--character-id", default=None)
    parser.add_argument("--scenario-id", required=True)
    args = parser.parse_args()

    import live_persona_spotcheck as lps

    lps.USER_LINES = COFFEE_SHOP_LINES
    sid = asyncio.run(run(args.url, args.character_id, args.scenario_id, len(COFFEE_SHOP_LINES)))
    print_transcript(sid)
