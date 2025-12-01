from dataclasses import dataclass, field

from ebook_translator.pipeline.base import ExecutionMode, PhaseBase, PhaseName
from ebook_translator.pipeline.context import ChunkContext
from ebook_translator.segmentation.chunk import Chunk


@dataclass
class DummyPhase(PhaseBase):
    """Phase factice utilisée pour l'initialisation."""

    name = PhaseName.DUMMY
    max_tokens: int = field(default=0, init=False)
    overlap_ratio: float = field(default=0, init=False)
    execution_mode = ExecutionMode.SEQUENTIAL
    max_workers: int = field(default=0, init=False)
    store_readonly: bool = field(default=True, init=False)
    checks = []

    def render_prompt(self, chunk: "Chunk", context: "ChunkContext") -> str:
        return ""
