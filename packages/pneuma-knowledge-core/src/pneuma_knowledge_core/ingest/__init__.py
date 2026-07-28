"""Ingest: SourceAdapter registry + normalization (architecture.md §4 layer ①).

The adapter layer is the ONLY layer allowed to grow with data-type diversity.
It produces NormalizedSource (blocks + structure map + metadata + checksum) and
knows only "what shape this is", not "what should be remembered".
"""
