#!/usr/bin/env python3
"""Export the two authorities of the library in the running stack into prebuilt/.

The mirror image of `./app.py restore`, and the reason this example can be browsed with no
API key. Only the authorities are written, because they are the only things that cannot be
recomputed (architecture.md §2):

  prebuilt/canonical.bundle  the canonical library as a git bundle — every commit, so the
                             compile history is browsable in the restored copy too;
  prebuilt/l0.jsonl.gz       the NormalizedSource rows verbatim, one JSON object per line.
                             Source ids are system-assigned at ingest, so a re-ingest of
                             my-data/ could never reproduce the ids the canonical cites —
                             which is exactly why they are shipped rather than rebuilt.

Everything else (L1, L2, L3, the component projections) is derived and is rebuilt by the
restore. Nothing here calls a model.

    ./build-record/export-prebuilt.py            # writes ../prebuilt/
"""

from __future__ import annotations

import asyncio
import gzip
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PREBUILT = PROJECT / "prebuilt"
sys.path.insert(0, str(PROJECT))
import app as driver  # noqa: E402 — the project's own driver, for .env, settings and the tenant


async def main() -> int:
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.prebuilt import (
        BUNDLE_NAME,
        L0_DUMP_NAME,
        L0_MEDIA_DIR_NAME,
    )
    from pneuma_knowledge_service.wiring import build_context

    skill = driver.load_contract_skill()
    settings = driver.build_settings(base_version=skill.version, require_key=False)
    ctx = await build_context(settings)
    try:
        uid = UserId(driver.user_id())
        PREBUILT.mkdir(parents=True, exist_ok=True)
        repo = ctx.canonical.repo_path(uid)
        if not (Path(repo) / ".git").is_dir():
            print(f"error: no canonical repository at {repo}", file=sys.stderr)
            return 1
        subprocess.run(
            ["git", "-C", str(repo), "bundle", "create", str(PREBUILT / BUNDLE_NAME), "--all"],
            capture_output=True,
            text=True,
            check=True,
        )
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        commits = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        print(f"  canonical.bundle: HEAD {head[:12]}, {commits} commit(s)")

        sources = images = 0
        with gzip.open(PREBUILT / L0_DUMP_NAME, "wt", encoding="utf-8") as handle:
            for raw in await ctx.store.list(uid):
                normalized = await ctx.store.get(uid, raw.source_id)
                handle.write(
                    json.dumps(normalized.model_dump(mode="json"), ensure_ascii=False) + "\n"
                )
                sources += 1
                for block in normalized.blocks:
                    for image in block.images:
                        payload = (
                            PREBUILT
                            / L0_MEDIA_DIR_NAME
                            / "sha256"
                            / image.sha256[:2]
                            / image.sha256
                        )
                        payload.parent.mkdir(parents=True, exist_ok=True)
                        payload.write_bytes(await ctx.media.get(uid, image.storage_key))
                        images += 1
        print(f"  l0.jsonl.gz: {sources} source(s), {images} image object(s)")
        documents = len(await ctx.canonical.list(uid))
        print(f"\nExported the library of {uid}: {documents} canonical document(s).")
        print("Restore it into an empty stack with ./app.py restore.")
    finally:
        await ctx.aclose()
    return 0


def _reexec_through_the_framework_env() -> None:
    import os

    try:
        import pneuma_knowledge_service  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("PNEUMA_APP_REEXEC") == "1":
        sys.exit("error: the framework package is still missing after the uv re-exec.")
    repo = driver.find_framework_repo()
    if repo is None:
        sys.exit("error: framework repository not found. Set PNEUMA_APP_FRAMEWORK_REPO in .env.")
    os.environ["PNEUMA_APP_REEXEC"] = "1"
    os.execvpe(
        "uv",
        ["uv", "run", "--project", str(repo), "python", str(Path(__file__).resolve())],
        os.environ,
    )


if __name__ == "__main__":
    driver.load_env_file(PROJECT / ".env")
    _reexec_through_the_framework_env()
    raise SystemExit(asyncio.run(main()))
