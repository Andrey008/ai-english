"""STORY-01-07: barge-in resource-feasibility spike.

Runs LLM generation + TTS playback while continuously listening on the
live mic for a new utterance (real barge-in condition: VAD/STT ready
while LLM+TTS are both active). Measures:
- stop latency: VAD-detected speech onset -> TTS playback actually killed
- memory/resource behavior across several cycles (endurance check)
"""
import json
import queue
import subprocess
import threading
import time

import numpy as np
import ollama
import sounddevice as sd
import torch
from silero_vad import VADIterator, load_silero_vad

MODEL = "qwen2.5:32b"
PIPER_VOICE = "voices/en_US-lessac-medium"
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512  # ~32ms at 16kHz, silero-recommended
SYSTEM_PROMPT = (
    "You are a friendly conversational partner helping someone practice "
    "spoken English. Give a longer, detailed answer (4-6 sentences) so "
    "there's time to interrupt you mid-response."
)
PROMPTS = [
    "Tell me a detailed story about a road trip you imagine taking.",
    "Describe your ideal weekend in a lot of detail.",
    "Explain, in detail, how you'd plan a surprise birthday party.",
    "Tell me a long story about learning a new hobby.",
    "Describe in detail what your dream house would look like.",
    "Tell me a detailed story about exploring a new city for the first time.",
    "Describe, in detail, your favorite meal and how you'd cook it.",
    "Tell me a long story about a memorable holiday you imagine having.",
]

interrupt_event = threading.Event()
interrupt_time = [None]
vad_stop = threading.Event()


def vad_listener_thread():
    vad_model = load_silero_vad()
    vad_iter = VADIterator(vad_model, sampling_rate=SAMPLE_RATE, threshold=0.5)
    q = queue.Queue()

    def callback(indata, frames, time_info, status):
        q.put(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                         blocksize=CHUNK_SAMPLES, callback=callback):
        while not vad_stop.is_set():
            try:
                chunk = q.get(timeout=0.5)
            except queue.Empty:
                continue
            x = torch.from_numpy(chunk[:, 0])
            if len(x) != CHUNK_SAMPLES:
                continue
            result = vad_iter(x)
            if result and "start" in result and not interrupt_event.is_set():
                interrupt_time[0] = time.perf_counter()
                interrupt_event.set()


def run_cycle(prompt: str, cycle_idx: int) -> dict:
    interrupt_event.clear()
    interrupt_time[0] = None

    t_cycle_start = time.perf_counter()
    stream = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        stream=True,
    )

    buf = ""
    full_reply = ""
    sentences_played = 0
    current_proc = None
    interrupted = False
    t_stop_confirmed = None
    t_first_audio = None

    import re
    sentence_end = re.compile(r"[.!?]+[\"')\]]?\s")

    for chunk in stream:
        if interrupt_event.is_set():
            interrupted = True
            break
        piece = chunk["message"]["content"]
        buf += piece
        full_reply += piece
        m = sentence_end.search(buf)
        if m:
            sentence = buf[:m.end()].strip()
            buf = buf[m.end():]
            if interrupt_event.is_set():
                interrupted = True
                break
            out = f"results/bargein_endurance_samples/cycle{cycle_idx}_s{sentences_played}.wav"
            subprocess.run(
                ["uv", "run", "python", "-m", "piper",
                 "-m", f"{PIPER_VOICE}.onnx", "-c", f"{PIPER_VOICE}.onnx.json",
                 "-f", out],
                input=sentence, text=True, capture_output=True, check=True,
            )
            if interrupt_event.is_set():
                interrupted = True
                break
            if current_proc and current_proc.poll() is None:
                current_proc.wait()
            current_proc = subprocess.Popen(["afplay", out])
            if t_first_audio is None:
                t_first_audio = time.perf_counter()
            sentences_played += 1
            # poll for interrupt while this chunk plays
            while current_proc.poll() is None:
                if interrupt_event.is_set():
                    interrupted = True
                    current_proc.terminate()
                    current_proc.wait()
                    t_stop_confirmed = time.perf_counter()
                    break
                time.sleep(0.02)
            if interrupted:
                break

    if interrupted and t_stop_confirmed is None:
        # interrupted before/between playback (no proc to kill)
        t_stop_confirmed = time.perf_counter()
        if current_proc and current_proc.poll() is None:
            current_proc.terminate()
            current_proc.wait()

    stop_latency = None
    if interrupted and interrupt_time[0] is not None and t_stop_confirmed is not None:
        stop_latency = t_stop_confirmed - interrupt_time[0]

    return {
        "cycle": cycle_idx,
        "prompt": prompt,
        "interrupted": interrupted,
        "sentences_played_before_stop": sentences_played,
        "full_reply_so_far": full_reply,
        "stop_latency_s": round(stop_latency, 3) if stop_latency else None,
        "time_to_first_audio_s": round(t_first_audio - t_cycle_start, 3) if t_first_audio else None,
        "cycle_wall_time_s": round(time.perf_counter() - t_cycle_start, 3),
    }


if __name__ == "__main__":
    import os
    os.makedirs("results/bargein_endurance_samples", exist_ok=True)

    listener = threading.Thread(target=vad_listener_thread, daemon=True)
    listener.start()
    time.sleep(1)  # let mic stream initialize

    print("Warming up LLM...")
    ollama.chat(model=MODEL, messages=[{"role": "user", "content": "hi"}])

    results = []
    for i, prompt in enumerate(PROMPTS):
        print(f"\n=== CYCLE {i+1}/{len(PROMPTS)} — interrupt me anytime by talking ===")
        r = run_cycle(prompt, i)
        print(json.dumps(r, indent=2))
        results.append(r)
        time.sleep(2)

    vad_stop.set()
    with open("results/bargein_endurance.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nDone.")
