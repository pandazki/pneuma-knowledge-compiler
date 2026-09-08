"""The middleware stack this engine runs on, as one rendered compose file.

Four services and nothing else — Postgres (L0 and the job queue), Qdrant (L2), Meilisearch
(L1), RustFS (media) — bound to loopback under a named compose project. The application
layer (API, worker, web) is not here on purpose: the personal edition runs the engine as a
process on the host, and the scaffold's generated project carries its own optional console
profile. What both editions share is exactly these four, and this is the one place their
images, healthchecks and environment are written down.

The scaffold's `docker-compose.yml` stays a verbatim, environment-driven template — it is
copied byte for byte into a generated project and carries the console profile besides — so
it is not rendered from here. A test pins the two descriptions of the four services against
each other instead, which is what keeps them from drifting.
"""

from __future__ import annotations

import yaml

#: Pinned images. A digest for RustFS because its tags move.
POSTGRES_IMAGE = "postgres:16"
QDRANT_IMAGE = "qdrant/qdrant:v1.18.0"
MEILISEARCH_IMAGE = "getmeili/meilisearch:v1.11"
RUSTFS_IMAGE = "rustfs/rustfs@sha256:41fe89380f4120a337790c02af192c3fe7bb55c3edc2e6e9357b487b47c6ab21"

#: The database Postgres is created with, and the role that owns it.
PG_DATABASE = "pneuma_knowledge"
PG_USER = "pneuma_knowledge"

#: Ports the caller must supply, in the order they appear in the file.
PORT_KEYS = ("pg", "qdrant", "qdrant_grpc", "meili", "rustfs", "rustfs_console")

#: Where each service keeps its state inside the container, and the named volume used when
#: the caller does not give a host directory.
DATA_PATHS = {
    "postgres": ("/var/lib/postgresql/data", "postgres_data"),
    "qdrant": ("/qdrant/storage", "qdrant_data"),
    "meilisearch": ("/meili_data", "meili_data"),
    "rustfs": ("/data", "rustfs_data"),
}

_HEADER = """\
# The middleware this knowledge library runs on: Postgres (L0 + the job queue), Qdrant (L2),
# Meilisearch (L1) and RustFS (media). Rendered by
# pneuma_knowledge_service.infra.compose.render_middleware_compose — edit the renderer, not
# this file, or the next render will overwrite what you wrote.
#
# Everything binds 127.0.0.1 only; the compose project name owns the volumes and the
# network, so renaming it orphans the old volumes.
#
#   docker compose -f docker-compose.yml up -d --wait
"""


def _service_volume(service: str, data_dir: str | None) -> str:
    container_path, volume_name = DATA_PATHS[service]
    if data_dir is None:
        return f"{volume_name}:{container_path}"
    return f"{data_dir.rstrip('/')}/{service}:{container_path}"


def _healthcheck(test: list[str], *, retries: int) -> dict:
    return {"test": test, "interval": "5s", "timeout": "5s", "retries": retries}


def render_middleware_compose(
    *,
    project_name: str,
    ports: dict[str, int],
    data_dir: str | None = None,
    pg_password: str,
    meili_key: str,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    subnet: str | None = None,
) -> str:
    """The four-service compose file, with every value written out literally.

    `ports` must carry `pg`, `qdrant`, `qdrant_grpc`, `meili`, `rustfs` and
    `rustfs_console`; nothing is defaulted, because a stack that silently lands on a
    default port is a stack two libraries can collide on.

    `data_dir` given, each service bind-mounts `<data_dir>/<service>` — the personal
    edition keeps its state under the home, where a person can see it and back it up.
    Omitted, the four named volumes are used, which is what a generated project does.

    `subnet` given, the default network is pinned to it: every compose project otherwise
    consumes one of Docker's predefined address pools, and a machine with many stacks runs
    them dry.
    """
    missing = [key for key in PORT_KEYS if key not in ports]
    if missing:
        raise ValueError(f"render_middleware_compose needs ports for: {', '.join(missing)}")
    if not project_name:
        raise ValueError("render_middleware_compose needs a compose project name")

    document: dict = {
        "name": project_name,
        "services": {
            "postgres": {
                "image": POSTGRES_IMAGE,
                "restart": "unless-stopped",
                "environment": {
                    "POSTGRES_DB": PG_DATABASE,
                    "POSTGRES_USER": PG_USER,
                    "POSTGRES_PASSWORD": pg_password,
                },
                "ports": [f"127.0.0.1:{ports['pg']}:5432"],
                "volumes": [_service_volume("postgres", data_dir)],
                "healthcheck": _healthcheck(
                    ["CMD-SHELL", f"pg_isready -U {PG_USER} -d {PG_DATABASE}"], retries=20
                ),
            },
            "qdrant": {
                "image": QDRANT_IMAGE,
                "restart": "unless-stopped",
                "ports": [
                    f"127.0.0.1:{ports['qdrant']}:6333",
                    f"127.0.0.1:{ports['qdrant_grpc']}:6334",
                ],
                "volumes": [_service_volume("qdrant", data_dir)],
                "healthcheck": _healthcheck(
                    ["CMD-SHELL", "bash -c ':> /dev/tcp/127.0.0.1/6333' || exit 1"], retries=20
                ),
            },
            "meilisearch": {
                "image": MEILISEARCH_IMAGE,
                "restart": "unless-stopped",
                "environment": {
                    "MEILI_MASTER_KEY": meili_key,
                    "MEILI_NO_ANALYTICS": "true",
                },
                "ports": [f"127.0.0.1:{ports['meili']}:7700"],
                "volumes": [_service_volume("meilisearch", data_dir)],
                "healthcheck": _healthcheck(
                    ["CMD", "curl", "-f", "http://localhost:7700/health"], retries=20
                ),
            },
            "rustfs": {
                "image": RUSTFS_IMAGE,
                "restart": "unless-stopped",
                "environment": {
                    "RUSTFS_ADDRESS": "0.0.0.0:9000",
                    "RUSTFS_CONSOLE_ENABLE": "true",
                    "RUSTFS_CONSOLE_ADDRESS": "0.0.0.0:9001",
                    "RUSTFS_ACCESS_KEY": rustfs_access_key,
                    "RUSTFS_SECRET_KEY": rustfs_secret_key,
                },
                "command": ["/data"],
                "ports": [
                    f"127.0.0.1:{ports['rustfs']}:9000",
                    f"127.0.0.1:{ports['rustfs_console']}:9001",
                ],
                "volumes": [_service_volume("rustfs", data_dir)],
                "healthcheck": _healthcheck(
                    ["CMD-SHELL", "curl -f http://127.0.0.1:9000/health || exit 1"], retries=20
                ),
            },
        },
    }
    if data_dir is None:
        document["volumes"] = {name: None for _, name in DATA_PATHS.values()}
    if subnet:
        document["networks"] = {"default": {"ipam": {"config": [{"subnet": subnet}]}}}

    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"{_HEADER}\n{body}"


__all__ = [
    "DATA_PATHS",
    "MEILISEARCH_IMAGE",
    "PG_DATABASE",
    "PG_USER",
    "PORT_KEYS",
    "POSTGRES_IMAGE",
    "QDRANT_IMAGE",
    "RUSTFS_IMAGE",
    "render_middleware_compose",
]
