
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MUTATIONS = {
    "src/glip/routes.py": {
        "create_stage", "link_provider", "create_task", "create_milestone",
        "create_schedule", "create_budget", "create_knowledge", "promote_memory",
        "cap_draft", "edit", "request", "approve", "reject", "create_document",
        "create_decision", "create_asset", "create_communication",
    },
    "src/glip/artifact_routes.py": {
        "render_artifact", "upload_architecture_source", "queue_bim_semantic_extraction",
        "create_architecture_scene", "queue_cad_semantic_extraction",
        "queue_scene_geometry_build",
    },
    "src/glip/pricing/routes.py": {
        "create_mapping", "approve_mapping", "construction_estimate",
        "professional_fee_estimate", "create_cost_event",
    },
}


def _functions(rel: str):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _calls(node):
    result = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            try:
                result.append(ast.unparse(child.func))
            except Exception:
                pass
    return result


def test_mutations_use_archive_write_barrier():
    for rel, names in MUTATIONS.items():
        funcs = _functions(rel)
        assert names <= funcs.keys()
        for name in sorted(names):
            assert "mutable_project_or_409" in _calls(funcs[name]), f"{rel}:{name}"


def test_calculation_posts_are_not_misclassified_as_writes():
    funcs = _functions("src/glip/routes.py")
    assert "mutable_project_or_409" not in _calls(funcs["cap_summary"])
    assert "mutable_project_or_409" not in _calls(funcs["cap_risk"])


def test_barrier_preserves_tenant_lookup_precedence():
    funcs = _functions("src/glip/context.py")
    source = ast.unparse(funcs["mutable_project_or_409"])
    assert source.index("project_or_404") < source.index("archived_at")
    assert "project_archived" in source


def test_cognitive_profile_readonly_guard_precedes_lazy_creation():
    funcs = _functions("src/glip/routes.py")
    source = ast.unparse(funcs["cognitive_profile"])
    calls = _calls(funcs["cognitive_profile"])
    assert "project_or_404" in calls
    assert "mutable_project_or_409" not in calls
    assert "ProjectCognitiveProfile" in source
    assert "cognitive_profile_not_found" in source
    assert source.index("archived_at") < source.index("ensure_cognitive_profile")
