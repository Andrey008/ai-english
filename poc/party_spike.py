"""Party-mode spike: can one LLM call voice TWO distinct characters?

Question this answers (go/no-go for a group-conversation mode):
  With a single generation per user turn, tagged by speaker
  ("[DANIEL] ...", "[PRIYA] ..."), does gemma2:27b
    1. keep the tag format parseable,
    2. stay within <= 2 AI lines per turn (user must not become a listener),
    3. hand the floor back to the user at the end of every turn,
    4. let the addressed person answer when the user names someone,
    5. keep both characters in play and distinct,
    6. stay in English,
  over 20 turns, with first-speakable-sentence latency comparable to 1:1?

Throwaway: no server code touched. Run:
  cd poc && uv run python party_spike.py            # scripted, both scenarios
  cd poc && uv run python party_spike.py --chat pub # interactive, type as the user
Outputs: poc/results/party_transcripts/<scenario>.json + summary printed.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

import ollama

MODEL = "gemma2:27b"  # current primary model (ADR-0012)
MAX_LINES = 2          # hard cap enforced in code, counted as a violation
OUT_DIR = Path(__file__).parent / "results" / "party_transcripts"

PARTY_TEMPLATE = """You voice TWO people in a live, spoken group conversation with the user,
who is practising spoken English. The user is a real third participant.

THE TWO PEOPLE:
{people}

LANGUAGE (non-negotiable): only English, always.

OUTPUT FORMAT (strict, your text is parsed by a program and read aloud):
- Every line starts with a speaker tag: {tags}, then what that person says.
- Never write lines for the user, never use any other tag, no narration,
  no stage directions, no markdown.

TURN-TAKING RULES (most important):
- Most replies are ONE line from ONE person. Use a second line only now
  and then, when the other person has something real to add (a reaction,
  a disagreement, a joke) -- never just to agree, praise or repeat.
  Never more than 2 lines in total.
- If the user speaks to someone by name, THAT person answers first.
- The reply must END with a direct question to the user (or a clear
  invitation for the user to speak). Nothing comes after that question.
  So if two people speak, the short reaction comes FIRST and the person
  asking the user something speaks LAST.
- The two people must not end up just talking to each other.
- Each line is short spoken dialogue: 1-2 sentences.
- Over the conversation, both people take part; keep their personalities,
  opinions and speaking styles clearly different.

SPEECH RECOGNITION: the user's words come from speech recognition and may
be misheard; go with the most likely meaning.

{scenario}"""

SCENARIOS = {
    "panel_interview": {
        "people": {
            "DANIEL": (
                "Daniel, a calm senior backend engineer. Asks technical "
                "questions one at a time, short precise follow-ups when an "
                "answer is vague. Polite, a little dry."
            ),
            "PRIYA": (
                "Priya, the warm, energetic engineering manager. Cares about "
                "teamwork, conflicts, motivation and how the candidate "
                "communicates. Sometimes builds on Daniel's question from a "
                "people angle."
            ),
        },
        "scenario": (
            "SCENARIO: a job interview for a backend developer role in an "
            "e-commerce integration team. Daniel and Priya are the interview "
            "panel, the user is the candidate. Drive the interview: warm-up, "
            "technical, behavioral, the candidate's questions, close. Never "
            "evaluate the answers during the interview."
        ),
        "opening_user": "(The candidate joins the call.) Hi, nice to meet you both.",
        "turns": [
            "Hi, yes, I hear you well.",
            "I am backend developer for six years, mostly PHP and Python.",
            "Yes.",
            "Daniel, can you repeat the question please?",
            "We had a queue with RabbitMQ and some workers, when the marketplace API was down we retry later.",
            "I don't know, maybe with exponential backoff?",
            "Priya, what is the team size?",
            "Okay.",
            "One time I disagree with my team lead about the database migration, we talk and find compromise.",
            "Hmm, I think I prefer to work remote but sometimes office is fine.",
            "Can I ask both of you, what do you like most in this company?",
            "Sounds good.",
            "Daniel, how do you do code review here?",
            "I usually write tests with pytest, unit and some integration.",
            "Sorry, I didn't understand.",
            "Probably because I want bigger challenges and better English environment.",
            "I am not sure.",
            "Priya, what are the next steps after this interview?",
            "No more questions, thank you.",
            "Thank you, bye!",
        ],
    },
    "pub": {
        "people": {
            "OLIVER": (
                "Oliver, a laid-back British guy from Manchester. Dry humour, "
                "teases people a bit, loves football and complaining about "
                "the weather. Uses casual British phrases."
            ),
            "MAYA": (
                "Maya, an enthusiastic American traveller from Seattle. "
                "Optimistic, asks lots of curious questions, loves food and "
                "hiking, often disagrees with Oliver for fun."
            ),
        },
        "scenario": (
            "SCENARIO: three friends having a drink in a pub on a Friday "
            "evening. Casual chat: weekend plans, food, travel, work, small "
            "arguments. Keep the user involved, it is their evening too."
        ),
        "opening_user": "Hey guys, sorry I'm late!",
        "turns": [
            "Traffic was terrible.",
            "Just a beer, thanks.",
            "Nothing special.",
            "Oliver, which team do you support?",
            "I don't really watch football.",
            "Maya, where did you travel last time?",
            "Wow, cool.",
            "I think the best food is in Georgia, khachapuri is amazing.",
            "Yes.",
            "What do you two think, is it better to live in a big city or small town?",
            "I agree with Maya actually.",
            "Hmm.",
            "My work is fine, a lot of meetings this week.",
            "Oliver, you always complain!",
            "I want to go hiking maybe next month.",
            "Okay.",
            "What are you doing tomorrow?",
            "I don't know, maybe sleep long.",
            "Ha ha, true.",
            "Okay guys, I need to go, see you!",
        ],
    },
}

TAG_RE = re.compile(r"\[([A-Z]+)\]\s*")
SENTENCE_END = re.compile(r"[.!?](\s|$)")


def build_prompt(sc: dict) -> str:
    people = "\n".join(f"[{tag}] {desc}" for tag, desc in sc["people"].items())
    tags = ", ".join(f"[{t}]" for t in sc["people"])
    return PARTY_TEMPLATE.format(people=people, tags=tags, scenario=sc["scenario"])


def parse_segments(text: str) -> tuple[list[tuple[str, str]], str]:
    """Split tagged output into (speaker, line). Returns (segments, untagged_prefix)."""
    parts = TAG_RE.split(text)
    prefix = parts[0].strip()
    segs = []
    for i in range(1, len(parts) - 1, 2):
        line = parts[i + 1].strip()
        if line:
            segs.append((parts[i], line))
    return segs, prefix


def generate(messages: list[dict]) -> dict:
    """Stream one reply; measure TTFT and time to first speakable sentence
    (first tag seen + first sentence end after it — what TTS could start on)."""
    t0 = time.perf_counter()
    ttft = first_sentence = None
    buf = ""
    for chunk in ollama.chat(
        model=MODEL, messages=messages, stream=True,
        options={"temperature": 0.7, "num_predict": 220}, keep_alive="1h",
    ):
        piece = chunk["message"]["content"]
        if piece and ttft is None:
            ttft = time.perf_counter() - t0
        buf += piece
        if first_sentence is None:
            m = TAG_RE.search(buf)
            if m and SENTENCE_END.search(buf[m.end():]):
                first_sentence = time.perf_counter() - t0
    return {"raw": buf, "ttft": ttft, "first_sentence": first_sentence,
            "total": time.perf_counter() - t0}


def non_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(not c.isascii() for c in letters) / len(letters) > 0.05


def addressed(user_text: str, people: list[str]) -> str | None:
    for p in people:
        if re.match(rf"\s*{p}\b", user_text, re.IGNORECASE):
            return p
    return None


def evaluate_turn(user_text: str, gen: dict, people: list[str]) -> dict:
    segs, prefix = parse_segments(gen["raw"])
    speakers = [s for s, _ in segs]
    issues = []
    if prefix:
        issues.append("untagged_text")
    if not segs:
        issues.append("no_segments")
    if any(s not in people for s in speakers):
        issues.append("unknown_tag:" + ",".join(s for s in speakers if s not in people))
    if len(segs) > MAX_LINES:
        issues.append(f"too_many_lines:{len(segs)}")
    kept = [(s, l) for s, l in segs if s in people][:MAX_LINES]
    if len(kept) == 2 and "?" in kept[0][1] and "?" not in kept[1][1]:
        kept = kept[:1]
        issues.append("dropped_trailing_line")  # code guard fired (fine, just counted)
    if kept and "?" not in kept[-1][1]:
        issues.append("no_handoff_question")  # heuristic, reviewed manually
    target = addressed(user_text, people)
    if target and kept and kept[0][0] != target:
        issues.append(f"wrong_responder:{kept[0][0]}!={target}")
    if non_english(gen["raw"]):
        issues.append("non_english")
    return {"segments": kept, "issues": issues, "n_lines": len(segs)}


def history_text(segs: list[tuple[str, str]]) -> str:
    return "\n".join(f"[{s}] {l}" for s, l in segs)


def run_scripted(name: str) -> dict:
    sc = SCENARIOS[name]
    people = list(sc["people"])
    messages = [{"role": "system", "content": build_prompt(sc)}]
    log = []
    for user_text in [sc["opening_user"], *sc["turns"]]:
        messages.append({"role": "user", "content": user_text})
        gen = generate(messages)
        ev = evaluate_turn(user_text, gen, people)
        # Feed back the cleaned, capped version — what the user actually heard.
        messages.append({"role": "assistant", "content": history_text(ev["segments"]) or gen["raw"]})
        log.append({"user": user_text, **gen, **ev})
        print(f"\nUSER: {user_text}")
        for s, l in ev["segments"]:
            print(f"  {s}: {l}")
        print(f"  [{gen['first_sentence'] or 0:.2f}s first sentence, {gen['total']:.2f}s total]"
              + (f"  ISSUES: {ev['issues']}" if ev["issues"] else ""))
    return {"scenario": name, "model": MODEL, "system_prompt": messages[0]["content"], "turns": log}


def summarize(res: dict) -> dict:
    t = res["turns"]
    people = list(SCENARIOS[res["scenario"]]["people"])
    lines = [s for turn in t for s, _ in turn["segments"]]
    issue_counts: dict[str, int] = {}
    for turn in t:
        for i in turn["issues"]:
            k = i.split(":")[0]
            issue_counts[k] = issue_counts.get(k, 0) + 1
    fs = [x["first_sentence"] for x in t if x["first_sentence"]]
    return {
        "scenario": res["scenario"],
        "turns": len(t),
        "clean_turns": sum(not [i for i in x["issues"] if i != "dropped_trailing_line"] for x in t),
        "issues": issue_counts,
        "lines_per_turn": dict(sorted({n: sum(x["n_lines"] == n for x in t) for n in {x["n_lines"] for x in t}}.items())),
        "speaker_share": {p: lines.count(p) for p in people},
        "first_sentence_s": {"median": round(statistics.median(fs), 2), "max": round(max(fs), 2)} if fs else None,
        "ttft_median_s": round(statistics.median(x["ttft"] for x in t if x["ttft"]), 2),
    }


def chat(name: str) -> None:
    sc = SCENARIOS[name]
    people = list(sc["people"])
    messages = [{"role": "system", "content": build_prompt(sc)}]
    print(f"Party chat: {', '.join(people)}. Empty line to quit.")
    while (user := input("\nYOU: ").strip()):
        messages.append({"role": "user", "content": user})
        gen = generate(messages)
        ev = evaluate_turn(user, gen, people)
        messages.append({"role": "assistant", "content": history_text(ev["segments"]) or gen["raw"]})
        for s, l in ev["segments"]:
            print(f"  {s}: {l}")
        print(f"  [{gen['first_sentence'] or 0:.2f}s]" + (f" ISSUES: {ev['issues']}" if ev["issues"] else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", choices=list(SCENARIOS))
    ap.add_argument("--only", choices=list(SCENARIOS))
    args = ap.parse_args()
    if args.chat:
        chat(args.chat)
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        summaries = []
        for name in [args.only] if args.only else list(SCENARIOS):
            res = run_scripted(name)
            res["summary"] = summarize(res)
            (OUT_DIR / f"{name}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
            summaries.append(res["summary"])
        print("\n=== SUMMARY ===")
        print(json.dumps(summaries, indent=2))
