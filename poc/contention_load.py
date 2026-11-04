"""STORY-01-03 helper: background resource-contention generator.
Loads faster-whisper medium.en and loops transcription over the real-voice
clips, while also looping Piper synthesis, to approximate STT/TTS being
"also loaded" (per the story's task) while bench_llm.py measures LLM
latency in a separate process. Run this in the background, then run
`bench_llm.py contention` in the foreground; Ctrl-C or kill this process
when the foreground run finishes.
"""
import glob
import itertools
import time

from faster_whisper import WhisperModel
from piper import PiperVoice

CLIPS = sorted(glob.glob("samples/real_voice/clip*.wav"))
FILLER_TEXT = (
    "This is filler text being synthesized in a loop to keep the "
    "text to speech engine busy during the LLM benchmark."
)


def main():
    print("Loading medium.en (STT) and Piper voice for contention load...")
    stt = WhisperModel("medium.en", device="cpu", compute_type="int8")
    voice = PiperVoice.load("voices/en_US-lessac-medium.onnx")

    print("Contention load running -- Ctrl-C to stop.")
    for clip in itertools.cycle(CLIPS):
        t0 = time.time()
        segments, _ = stt.transcribe(clip, language="en")
        _ = " ".join(s.text for s in segments)
        with open("/dev/null", "wb") as f:
            for chunk in voice.synthesize(FILLER_TEXT):
                f.write(chunk.audio_int16_bytes)
        print(f"[contention] cycle on {clip}: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nContention load stopped.")
