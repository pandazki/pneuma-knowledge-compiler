"""Port protocols (architecture.md §6). All Protocol; every method's first
argument is user_id (invariant I1: user_id isolation, no cross-user
read path exists). One port per file.

Every port method is `async def`: a port is by definition an I/O boundary, and the
service runs a single uvicorn process on a single event loop — a blocking port call
would stall every other request on that loop. An adapter whose backing client has no
truly-async face wraps it in `asyncio.to_thread` internally and says so; the port
signature stays async either way. The data-shape Protocols in these modules
(`ClaimHit`, `Job`, `LexicalHit`, `SemanticChunk`, `SemanticHit`) are attribute bags,
not I/O, and carry no methods.
"""
