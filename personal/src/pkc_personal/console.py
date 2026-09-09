"""The console's built page: packaged with the wheel, or downloaded from its own release.

The edition never imports the console's source (design §4.12); what it serves is a built
`dist` directory. A wheel built inside this repository carries one as an artifact, but the
README's one-line install builds from the git tree, where that directory is ignored — so the
same directory is published as a release asset and fetched here, verified against the digest
published beside it before a single file is written.

Three places are looked at, in one order: `PKC_CONSOLE_DIST` (a local build, the developer's
own), the wheel's copy, then the home's downloaded copy. Everything is sync: this is a CLI
helper, and nothing here awaits.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath

from pkc_personal import __version__
from pkc_personal.home import Home, replace_directory

RELEASE_URL = (
    "https://github.com/pandazki/pneuma-knowledge-compiler/releases/download/"
    "personal-console-v{version}/pkc-console-{version}.tar.gz"
)
PACKAGED_DIST = Path(__file__).resolve().parent / "console" / "dist"
TIMEOUT_SECONDS = 60.0
# A console build is a few megabytes; this bound is what a truncated read costs at worst.
MAX_BYTES = 128 * 1024 * 1024
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class ConsoleUnavailable(RuntimeError):
    """The page could not be fetched or trusted; one line, naming the URL and the reason."""


def console_version() -> str:
    """The installed distribution's version — the asset is published under the same one."""
    try:
        return distribution_version("pkc-personal")
    except PackageNotFoundError:
        return __version__


def tarball_url(version: str | None = None) -> str:
    return os.environ.get("PKC_CONSOLE_URL") or RELEASE_URL.format(version=version or console_version())


def _complete(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def env_dist() -> Path | None:
    """A local build named by the developer; a name that is not a directory is refused."""
    raw = os.environ.get("PKC_CONSOLE_DIST", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise ValueError(f"PKC_CONSOLE_DIST is not a directory: {path}")
    return path


def packaged_dist() -> Path | None:
    return PACKAGED_DIST if _complete(PACKAGED_DIST) else None


def home_dist(home: Home, version: str | None = None) -> Path | None:
    path = home.path / "console" / (version or console_version()) / "dist"
    return path if _complete(path) else None


def console_dist(home: Home) -> Path | None:
    return env_dist() or packaged_dist() or home_dist(home)


def console_state(home: Home) -> str:
    """What `pkchome status` says about the page, in the words `console install` uses."""
    try:
        local = env_dist()
    except ValueError as exc:
        return str(exc)
    if local is not None:
        return f"local build at {local}"
    if packaged_dist() is not None:
        return "packaged"
    if home_dist(home) is not None:
        return f"downloaded v{console_version()}"
    return "missing — run pkchome console install"


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"pkc-personal/{console_version()}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ConsoleUnavailable(f"console not fetched from {url}: larger than {MAX_BYTES} bytes")
    return payload


def _member(info: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    """The stdlib's `data` filter, and no links at all: a page is files and directories.

    macOS `tar` writes an AppleDouble `._name` beside every entry; those carry no page and
    are dropped rather than served (the release script disables them, older assets have them).
    """
    if PurePosixPath(info.name).name.startswith("._"):
        return None
    checked = tarfile.data_filter(info, path)
    if checked is not None and (checked.issym() or checked.islnk()):
        raise tarfile.FilterError(f"refused: {checked.name} is a link")
    return checked


def install_console(home: Home, *, fetch: Callable[[str], bytes] | None = None) -> Path:
    """Download, verify and publish the console page under `<home>/console/<version>/dist`.

    Idempotent: a copy already there is returned untouched. The digest is checked before
    anything is extracted, so a refused download leaves no half-written page behind.
    """
    read = fetch or _fetch
    version = console_version()
    target = home.path / "console" / version / "dist"
    if _complete(target):
        return target
    url = tarball_url(version)
    try:
        payload = read(url)
        published = read(f"{url}.sha256").decode("utf-8", "replace")
    except ConsoleUnavailable:
        raise
    except urllib.error.HTTPError as exc:
        raise ConsoleUnavailable(f"console not fetched from {url}: HTTP {exc.code}") from None
    except OSError as exc:  # URLError and every socket failure under it
        reason = getattr(exc, "reason", None) or exc
        raise ConsoleUnavailable(f"console not fetched from {url}: {reason}") from None

    expected = published.split()[0].lower() if published.split() else ""
    if not DIGEST_PATTERN.fullmatch(expected):
        raise ConsoleUnavailable(f"console not installed from {url}: {url}.sha256 holds no sha256 digest")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ConsoleUnavailable(
            f"console not installed from {url}: sha256 mismatch (published {expected}, downloaded {actual})"
        )

    root = home.path / "console"
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=root, prefix=f".{version}.staging."))
    try:
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
                archive.extractall(staging, filter=_member)
        except (tarfile.TarError, OSError, ValueError) as exc:
            raise ConsoleUnavailable(f"console not installed from {url}: {exc}") from None
        extracted = staging / "dist"
        if not _complete(extracted):
            raise ConsoleUnavailable(f"console not installed from {url}: the tarball has no dist/ directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        replace_directory(extracted, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target
