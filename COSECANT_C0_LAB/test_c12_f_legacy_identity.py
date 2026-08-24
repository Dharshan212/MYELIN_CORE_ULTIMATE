"""C12-F -- the identity-free compatibility tunnel.

``_expected_identity`` returns ``LEGACY_IDENTITY`` when a command carries no
expected-identity group at all, and both admission guards answered that with
an unconditional ``return True``.  Any command that simply omits the fields
therefore walked straight past the C11-A stale-generation fence.

Step one is the PRODUCTION CALLER MATRIX: prove whether any live production
sender can actually produce an identity-free command.  Only if none can is the
tunnel dead authority that may be closed.
"""

from __future__ import annotations

import ast

import pytest

import _lab

ULTIMATE = _lab.ULTIMATE


# ---------------------------------------------------------------------------
# F1 -- production caller matrix
# ---------------------------------------------------------------------------

#: command kind -> (sender file, controller method, required identity fields)
CALLER_MATRIX = {
    "study_prepare": (
        "CONTROL_STATION/controller.py",
        "prepare_study",
        ("expected_study_block_id", "expected_study_generation"),
    ),
    "study_action": (
        "CONTROL_STATION/controller.py",
        "request_study_action",
        ("expected_study_block_id", "expected_study_generation"),
    ),
    "study_break": (
        "CONTROL_STATION/controller.py",
        "request_study_break",
        ("expected_study_block_id", "expected_study_generation"),
    ),
    "cosecant_return_intent": (
        "CONTROL_STATION/controller.py",
        "request_cosecant_return_intent",
        (
            "expected_break_id",
            "expected_cosecant_generation",
            "expected_study_block_id",
            "expected_study_generation",
        ),
    ),
}


def _controller_tree():
    return ast.parse(
        (ULTIMATE / "CONTROL_STATION" / "controller.py").read_text(encoding="utf-8")
    )


def _method(name: str):
    return next(
        node
        for node in ast.walk(_controller_tree())
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_every_production_sender_is_in_the_matrix():
    """No identity-sensitive command kind is dispatched from anywhere else."""

    sources = [
        path
        for path in ULTIMATE.rglob("*.py")
        if path.name != "monitor.py"
    ]
    for kind in CALLER_MATRIX:
        senders = {
            str(path.relative_to(ULTIMATE)).replace("\\", "/")
            for path in sources
            if f'"{kind}"' in path.read_text(encoding="utf-8")
        }
        assert senders == {CALLER_MATRIX[kind][0]}, (kind, senders)


@pytest.mark.parametrize("kind", sorted(CALLER_MATRIX))
def test_production_sender_always_supplies_complete_identity(kind):
    """The controller is transport: it copies identity in unconditionally."""

    _, method_name, fields = CALLER_MATRIX[kind]
    body = ast.unparse(_method(method_name))

    if method_name == "request_cosecant_return_intent":
        for field in fields:
            assert field in body, field
    else:
        # Study commands build the pair through one helper.
        assert "_expected_study_identity(" in body
        helper = ast.unparse(_method("_expected_study_identity"))
        for field in fields:
            assert field in helper, field


def test_identity_fields_are_never_conditionally_omitted():
    """Every identity key is emitted on every call, defaults included.

    ``expected_study_block_id=""`` with ``expected_study_generation=0`` is a
    COMPLETE identity, not an absent one -- it is exactly what a Study runtime
    that has never prepared a block publishes.
    """

    helper = _method("_expected_study_identity")
    returns = [
        node for node in ast.walk(helper) if isinstance(node, ast.Return)
    ]
    assert len(returns) == 1
    assert isinstance(returns[0].value, ast.Dict)
    keys = {key.value for key in returns[0].value.keys}
    assert keys == {"expected_study_block_id", "expected_study_generation"}

    intent = _method("request_cosecant_return_intent")
    calls = [
        node
        for node in ast.walk(intent)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_enqueue_command"
    ]
    assert len(calls) == 1
    payload = calls[0].args[1]
    assert isinstance(payload, ast.Dict)
    assert {key.value for key in payload.keys} == {
        "expected_break_id",
        "expected_cosecant_generation",
        "expected_study_block_id",
        "expected_study_generation",
    }


def test_ui_emitters_read_identity_from_the_displayed_snapshot():
    """The Study view names what the user was looking at, not a default."""

    view = ast.parse(
        (ULTIMATE / "COSECANT_STUDY_MODE" / "view.py").read_text(encoding="utf-8")
    )
    emitters = {
        node.name: ast.unparse(node)
        for node in ast.walk(view)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_emit_study_action", "_emit_break", "_emit_prepare"}
    }
    assert set(emitters) == {"_emit_study_action", "_emit_break", "_emit_prepare"}
    for name, body in emitters.items():
        assert "_expected_study_identity()" in body, name

    intent = next(
        node
        for node in ast.walk(view)
        if isinstance(node, ast.FunctionDef) and node.name == "_emit_return_intent"
    )
    body = ast.unparse(intent)
    for field in ("break_id", "generation", "study_block_id", "study_generation"):
        assert f"snapshot.{field}" in body, field


# ---------------------------------------------------------------------------
# F2 -- the tunnel itself
# ---------------------------------------------------------------------------

def test_legacy_identity_bypass_is_gone_from_production():
    source = (ULTIMATE / "CORE_ENGINE" / "monitor.py").read_text(encoding="utf-8")
    assert "LEGACY_IDENTITY" not in source, (
        "the identity-free compatibility tunnel is still present"
    )
