"""STORY-01-05: end-to-end CLI pipeline & true TTFA measurement.

Wires: (recorded mic clip, trimmed to VAD-detected speech end) -> STT
(whisper.cpp + Core ML) -> LLM (Ollama, streamed) -> first-sentence
chunked TTS (Piper) -> speaker playback.

TTFA = wall-clock time from "speech end" (VAD-detected boundary within
the clip, standing in for a live VAD end-of-turn trigger) to the moment
the first response audio chunk starts playing.

Uses the 5 real-voice clips from STORY-01-02 as pre-recorded input,
run twice each (10 turns total) rather than live mic capture each turn
-- see /poc/results/e2e_latency.md for the rationale.
"""
import json
import os
import re
import subprocess
import time

import ollama
import soundfile as sf
import torch
from silero_vad import get_speech_timestamps, load_silero_vad

WHISPER_BIN = "whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL = "whisper.cpp/models/ggml-medium.en.bin"
PIPER_VOICE = "voices/en_US-lessac-medium"
LLM_MODEL = "qwen2.5:32b"
CLIPS = [f"samples/real_voice/clip{i}_{name}.wav" for i, name in [
    (1, "normal"), (2, "noise"), (3, "fast"), (4, "technical"), (5, "freeform"),
]]
SYSTEM_PROMPT = (
    "You are a friendly, engaging conversational partner helping someone "
    "practice spoken English. Respond naturally in 1-3 short sentences, "
    "like a real conversation partner would."
)

SENTENCE_END = re.compile(r"[.!?]+[\"')\]]?\s")

os.makedirs("results/e2e_samples", exist_ok=True)
vad_model = load_silero_vad()


def trim_to_speech_end(path: str) -> str:
    data, sr = sf.read(path, dtype="float32")
    wav = torch.from_numpy(data)
    ts = get_speech_timestamps(wav, vad_model, sampling_rate=sr, return_seconds=True)
    end_sample = int(ts[-1]["end"] * sr) if ts else len(data)
    trimmed = data[:end_sample]
    out = path.replace(".wav", "_trimmed.wav")
    sf.write(out, trimmed, sr)
    return out, ts[-1]["end"] if ts else len(data) / sr


def run_turn(clip: str) -> dict:
    trimmed_path, speech_end_s = trim_to_speech_end(clip)

    t_start = time.perf_counter()

    # STT
    proc = subprocess.run(
        [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", trimmed_path, "-nt"],
        capture_output=True, text=True, check=True,
    )
    transcript = " ".join(l.strip() for l in proc.stdout.splitlines() if l.strip())
    t_stt_done = time.perf_counter()

    # LLM, streamed, capture time to first complete sentence
    stream = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        stream=True,
    )
    buf = ""
    first_sentence = None
    t_first_sentence = None
    full_reply = ""
    for chunk in stream:
        piece = chunk["message"]["content"]
        buf += piece
        full_reply += piece
        if first_sentence is None:
            m = SENTENCE_END.search(buf)
            if m:
                first_sentence = buf[:m.end()].strip()
                t_first_sentence = time.perf_counter()
    if first_sentence is None:
        first_sentence = buf.strip()
        t_first_sentence = time.perf_counter()

    # TTS on first sentence only (this is what gates TTFA)
    tts_out = f"results/e2e_samples/{clip.split('/')[-1].replace('.wav','')}_reply.wav"
    subprocess.run(
        ["uv", "run", "python", "-m", "piper",
         "-m", f"{PIPER_VOICE}.onnx", "-c", f"{PIPER_VOICE}.onnx.json",
         "-f", tts_out],
        input=first_sentence, text=True, capture_output=True, check=True,
    )
    t_tts_done = time.perf_counter()

    # Playback (measuring launch overhead only, not full playback duration)
    t_playback_start = time.perf_counter()
    subprocess.Popen(["afplay", tts_out])

    ttfa = t_playback_start - t_start
    return {
        "clip": clip,
        "transcript": transcript,
        "first_sentence": first_sentence,
        "full_reply": full_reply,
        "stt_s": round(t_stt_done - t_start, 3),
        "llm_ttfb_s": round(t_first_sentence - t_stt_done, 3),
        "tts_s": round(t_tts_done - t_first_sentence, 3),
        "playback_launch_s": round(t_playback_start - t_tts_done, 3),
        "ttfa_s": round(ttfa, 3),
    }


if __name__ == "__main__":
    # warm-up: ensure LLM is loaded before timing starts
    print("Warming up LLM...")
    ollama.chat(model=LLM_MODEL, messages=[{"role": "user", "content": "hi"}])

    results = []
    for run_idx in range(2):
        for clip in CLIPS:
            print(f"\n=== run {run_idx+1}, {clip} ===")
            r = run_turn(clip)
            print(json.dumps(r, indent=2))
            results.append(r)
            time.sleep(3)  # let playback finish before next turn, don't overlap audio

    with open("results/e2e_latency.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nWritten to results/e2e_latency.json")
