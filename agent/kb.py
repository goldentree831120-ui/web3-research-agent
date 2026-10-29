"""Small local knowledge base: markdown notes in kb/, split by heading, ranked with BM25.

BM25 instead of embeddings keeps it offline, free and deterministic, which matters for
measuring the agent (same question -> same retrieved notes). Swap in embeddings later if the
notes grow beyond a few hundred chunks.
"""
import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class Chunk:
    source: str
    heading: str
    text: str


def _tokens(s: str) -> list[str]:
    return TOKEN.findall(s.lower())


def load_chunks(kb_dir: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(kb_dir.glob("*.md")):
        heading, buf = path.stem, []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                if "".join(buf).strip():
                    chunks.append(Chunk(path.name, heading, "\n".join(buf).strip()))
                heading, buf = line.lstrip("# ").strip(), []
            else:
                buf.append(line)
        if "".join(buf).strip():
            chunks.append(Chunk(path.name, heading, "\n".join(buf).strip()))
    return chunks


class KnowledgeBase:
    def __init__(self, kb_dir: Path):
        self.chunks = load_chunks(kb_dir)
        if not self.chunks:
            raise ValueError(f"no notes found in {kb_dir}")
        self.bm25 = BM25Okapi([_tokens(c.heading + " " + c.text) for c in self.chunks])

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        scores = self.bm25.get_scores(_tokens(query))
        ranked = sorted(zip(self.chunks, scores), key=lambda x: x[1], reverse=True)
        return [(c, float(s)) for c, s in ranked[:k] if s > 0]
