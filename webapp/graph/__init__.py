"""Line-detection + graph-extraction package (Stream 2).

Pure-algorithm package: the core modules (``tracer``, ``linker``, ``resolver``,
``assembler``, ``fallback``) import cleanly without a database or network. The
only I/O boundary is :mod:`webapp.graph.loader` (filesystem reads) and
:mod:`webapp.graph.pipeline` (orchestration + file write).

Data model + ``canonical_graph.json`` shape match the predecessor design at
``docs/superpowers/specs/2026-06-05-graph-extraction-design.md`` §3.
"""

from webapp.graph.tracer import (
    LineSegment,
    LineTracer,
    NoopLineTracer,
    OpenCVLineTracer,
)

__all__ = [
    "LineSegment",
    "LineTracer",
    "NoopLineTracer",
    "OpenCVLineTracer",
]
