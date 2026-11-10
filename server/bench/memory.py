"""Memory sampling while a backend is under test.

Two views, because neither is complete on Apple Silicon:
- **process RSS** of the backend (matched by command line, e.g.
  `llama-server` for Ollama's runner, `mlx_lm.server` for MLX) — Metal
  buffers may not all show up here;
- **system used memory** from `vm_stat` (active + wired + compressed
  pages), which does include GPU allocations in unified memory. Compare
  its peak against a baseline taken *before the backend server starts*
  (`python -m bench.memory`, passed to `run.py --baseline-system-mb`) —
  `mlx_lm.server` loads its model at launch, so a baseline taken by
  `run.py` itself would already include it. Only meaningful on an
  otherwise idle machine.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import dataclass

_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
_PAGES = re.compile(r"^(Pages [^:]+|Pages stored in compressor|Pages occupied by compressor):\s+(\d+)\.", re.M)


def parse_vm_stat(text: str) -> float:
    """Used memory in MB: active + wired + occupied-by-compressor pages."""
    page_size = int(_PAGE_SIZE.search(text).group(1))
    pages = {name: int(count) for name, count in _PAGES.findall(text)}
    used = pages.get("Pages active", 0) + pages.get("Pages wired down", 0) + pages.get("Pages occupied by compressor", 0)
    return used * page_size / 2**20


def parse_ps_rss(text: str, pattern: str, exclude_pids: frozenset[int] = frozenset()) -> float:
    """Summed RSS in MB of processes whose command line matches `pattern`
    (`ps -axo pid=,rss=,command=` output; RSS is in KB). The benchmark's
    own processes are excluded: its argv contains the pattern itself
    (`--process-pattern llama-server`)."""
    regex = re.compile(pattern)
    total_kb = 0
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if (
            len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit()
            and int(parts[0]) not in exclude_pids and regex.search(parts[2])
        ):
            total_kb += int(parts[1])
    return total_kb / 1024


def system_used_mb() -> float:
    return parse_vm_stat(subprocess.run(["vm_stat"], capture_output=True, text=True, check=True).stdout)


def process_rss_mb(pattern: str) -> float:
    out = subprocess.run(["ps", "-axo", "pid=,rss=,command="], capture_output=True, text=True, check=True).stdout
    return parse_ps_rss(out, pattern, frozenset({os.getpid(), os.getppid()}))


@dataclass
class MemoryPeaks:
    rss_mb: float = 0.0
    system_mb: float = 0.0


class MemorySampler:
    """Polls every `interval_s` in a thread, so sampling never stalls the
    event loop that times the stream. `window()` returns and resets the
    peak since the last call (per-turn peaks); `overall` keeps the run's."""

    def __init__(self, process_pattern: str | None, interval_s: float = 0.25):
        self._pattern = process_pattern
        self._interval_s = interval_s
        self._task: asyncio.Task | None = None
        self._window = MemoryPeaks()
        self.overall = MemoryPeaks()

    def _sample(self) -> MemoryPeaks:
        rss = process_rss_mb(self._pattern) if self._pattern else 0.0
        return MemoryPeaks(rss_mb=rss, system_mb=system_used_mb())

    async def _loop(self) -> None:
        while True:
            sample = await asyncio.to_thread(self._sample)
            for peaks in (self._window, self.overall):
                peaks.rss_mb = max(peaks.rss_mb, sample.rss_mb)
                peaks.system_mb = max(peaks.system_mb, sample.system_mb)
            await asyncio.sleep(self._interval_s)

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    def window(self) -> MemoryPeaks:
        peaks, self._window = self._window, MemoryPeaks()
        return peaks

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.wait({self._task})


if __name__ == "__main__":
    print(f"system used memory: {system_used_mb():.0f} MB")
