"""The shipped project must follow the current machinery and accept incremental work."""

from pathlib import Path
import subprocess
import yaml

from pneuma_knowledge_core.compile.documents import parse_document
from pneuma_knowledge_core.compile.gate import run_gate
from pneuma_knowledge_core.compile.overview import check_overviews, ledger_anchors
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.domain.canonical import CanonicalDocument

ROOT = Path(__file__).resolve().parents[1]


def test_opc_runtime_is_the_scaffold_runtime():
    for name in ("app.py", "start.sh", "server.py", "worker.py", "docker-compose.yml"):
        assert (ROOT / "examples/opc" / name).read_bytes() == (ROOT / "scaffold/templates" / name).read_bytes()


def test_shipped_bundle_allows_incremental_compile_and_exposes_historical_overview_debt(tmp_path):
    bare = tmp_path / "canonical.git"
    subprocess.run(["git", "clone", "--quiet", "--bare", str(ROOT / "examples/opc/prebuilt/canonical.bundle"), str(bare)], check=True)

    def git(*args):
        return subprocess.check_output(["git", "--git-dir", str(bare), *args], text=True)

    documents = []
    for path in git("ls-tree", "-r", "--name-only", "HEAD").splitlines():
        if path.endswith(".md"):
            fields, body = parse_document(git("show", f"HEAD:{path}"))
            documents.append(CanonicalDocument(doc_id=fields["doc_id"], path=path, frontmatter=fields, body=body))
    contract = yaml.safe_load((ROOT / "examples/opc/engine/compile/contract.md").read_text().split("---", 2)[1])
    draft = PatchDraft.from_canonical(documents, contract["path_templates"])
    target = "product/seamlog.md"
    anchor = sorted(ledger_anchors(draft.read(target).body))[0]
    draft.append_block(target, "Review", f"The ledger records this subject. c:{anchor}")
    assert run_gate(draft, []) == []
    audit = check_overviews(draft.new_bodies())
    assert audit and any("product/seamlog.md" == path for _, path, _ in audit)
