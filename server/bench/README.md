# LLM benchmark: Ollama vs MLX (Chronix AE-2)

This benchmark compares LLM engines on the same model and under the same
conditions. It answers one question: how much faster, or lighter on
memory, the voice companion would be with MLX instead of Ollama
(llama.cpp). It answers the same question for a 12–14B candidate model.

It measures the LLM step only. The rest of the pipeline doesn't depend on
the engine: STT (~0.5s) and Piper's first chunk (~0.1s). That gives:

    first audio ≈ STT + first_sentence_s + ~0.1s

## What makes it fair

- **Same input.** Every engine gets:
  - the same recorded conversation (your voice → whisper → text);
  - the production system prompt (`compose_system_prompt`, with the
    fixture's character and level, without memory).
- **Same prompts on every turn.** The default `--mode teacher` puts the
  script's reference reply into history, not the model's own reply. So
  turn N is byte-identical for every engine. Run `--mode free` separately
  to read how each engine actually talks; its timings aren't comparable.
- **Same decoding.** Greedy (`temperature 0`), `seed 42`, the same
  `--max-tokens`.
- **Cold and warm turns are separated.** Each repeat starts with a random
  tag at the top of the system prompt, so its first turn is uncached
  (`cold`). The remaining turns reuse the cached prefix, which is what
  live sessions depend on. `--warmup` repeats (model load, shader
  compile) are thrown away.
- **One engine at a time, on an idle Mac.** Run on the power adapter,
  with the AI English server, other models and heavy apps closed.
  `compare.py` warns if fixture, mode, text source, parameters or
  machine differ between result files.
- **Same 4-bit weights.** Ollama `gemma2:27b` is Q4_0, and MLX 4-bit
  (group size 64) is also ~4.5 bits/weight. The weight size is the same,
  so any difference comes from the engine.

## Steps

All commands run from `/server`.

### 1. Record your voice (once, no model needed)

```
uv run --group bench python -m bench.record bench/scripts/smalltalk_b1.yaml
uv run --group bench python -m bench.record bench/scripts/interview_coach_b1.yaml
```

Read each line the way you would talk in the app. You can play back or
re-record each line. If you stop, the next run continues where you left
off. To redo specific turns: `--redo 3 7`. To pick a mic:
`--list-devices`, then `--device N`.

The recordings go to `bench/fixtures/` and are **gitignored**: they're
your voice, and the repo is public.

### 2. Transcribe the recordings (once; starts whisper-server)

```
uv run python -m bench.transcribe bench/fixtures/smalltalk_b1
```

Stop the AI English server first, because this uses the same STT port.
Lines where whisper heard something different from the script are marked
`≠ script`. That's fine: the real pipeline would get the same text.

### 3. Baseline memory (before any engine starts)

```
uv run python -m bench.memory        # -> pass as --baseline-system-mb
```

### 4. Ollama

```
OLLAMA_KEEP_ALIVE=1h ollama serve        # nothing else running
uv run python -m bench.run bench/fixtures/smalltalk_b1 \
    --backend ollama --model gemma2:27b --label ollama-gemma2-27b \
    --process-pattern llama-server --baseline-system-mb <from step 3>
```

Stop Ollama afterwards and wait for memory to drop back to the baseline.

### 5. MLX

`mlx-lm` is deliberately **not** a dependency of the server. Run it on
its own:

```
uvx --from mlx-lm mlx_lm.server --model <mlx 4-bit gemma-2-27b-it repo> --port 8080
uv run python -m bench.run bench/fixtures/smalltalk_b1 \
    --backend openai --model <same repo id> --base-url http://127.0.0.1:8080 \
    --label mlx-gemma2-27b --process-pattern mlx_lm --baseline-system-mb <from step 3>
```

For Gemma 2 use `mlx-community/gemma-2-27b-it-bf16-4bit` and pass
`--fold-system`:

- The fp16 conversion (`gemma-2-27b-it-4bit`) overflows and outputs only
  `<pad>`.
- Gemma 2's HF chat template rejects the system role. `--fold-system`
  merges it into the first user turn, exactly as Ollama's gemma2 template
  does.

Hugging Face metadata can be wrong. The fp16 repo lists two files with
the same hash, and `hf download` wrote a truncated shard. Check every
`.safetensors` against its `lfs.sha256` before trusting a run. Any other OpenAI-compatible server
(llama-server, LM Studio) works the same way with `--backend openai`.

### 6. Compare

```
uv run python -m bench.compare bench/results/ollama-*.json bench/results/mlx-*.json \
    --replies bench/results/replies.md
```

The first file is the baseline. Other rows show the change against it,
and ✓ marks an improvement of 5% or more. Copy the table into the AE-2
results and the ADR.

### Free mode and `--prewarm-reply`

`--mode free` keeps each engine's own replies, as a live session does.
Timings aren't byte-comparable, but this is where cache behaviour shows.
`--prewarm-reply` (Ollama) re-evaluates history + reply after each turn,
mirroring `ConversationEngine`'s reply prewarm (ADR-0013). Each turn's
`prewarm_s` must stay well under the reply's playback time.

## Metrics

| Field | Meaning |
|---|---|
| `ttft_s` | Request sent → first token. Mostly prefill. |
| `first_sentence_s` | Request sent → first complete sentence, which is when TTS can start. **The main number.** |
| `decode_tps` | Tokens/s after the first token. Uses the server's token count, or the number of stream chunks if the server reports none. |
| `prefill_tps` (server) | Server-reported prompt tokens ÷ prompt eval time. Ollama counts only the tokens it actually evaluated, i.e. cache misses. Not comparable field by field across engines. |
| `peak RSS` | RSS of the matching processes. Metal buffers may not all show up here. |
| `peak system Δ` | `vm_stat` used memory (active + wired + compressed) above the baseline from step 3. Includes GPU allocations in unified memory. |

## Results so far

See ADR-0013:
- Ollama and MLX decode at the same speed (~14.5 tok/s, bandwidth-bound).
- MLX's per-turn advantage came from caching its own replies. Ollama now
  gets the same through the reply prewarm.
- The decision: stay on Ollama.

This measures the LLM layer, not the live WebSocket pipeline. Confirm
any change there with `ws_turn_timing` in a real session.
