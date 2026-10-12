"""Tests for the MEMBERSHIP_ACTION fast-engine short-circuit.

Critical invariant: the membership action path MUST NOT raise.
A raise triggers fast_fallback_to_baseline in query.py, which would try to
answer a join/leave command as a RAG question — wrong behavior.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys, os, importlib, types

# Stub heavy transitive dependencies so we can import membership_action in isolation.
for mod in ['neo4j_client', 'neo4j_client.client', 'neo4j_client.models',
            'common', 'common.service_client',
            'src.services.keyword_retriever',
            'src.settings']:
    if mod not in sys.modules:
        stub = types.ModuleType(mod)
        sys.modules[mod] = stub

# Minimal settings stub
_settings = types.SimpleNamespace(postgres_user='u', postgres_password='p',
                                   postgres_host='h', postgres_port=5432,
                                   postgres_db='db')
sys.modules['src.settings'].settings = _settings

src_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')
sys.path.insert(0, os.path.dirname(src_root))  # so "src.services.membership_action" resolves

spec = importlib.util.spec_from_file_location(
    "src.services.membership_action",
    os.path.join(src_root, "services", "membership_action.py"),
)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
handle = _mod.handle
_parse_action_and_target = _mod._parse_action_and_target


# ── _parse_action_and_target ──────────────────────────────────────────────────

@pytest.mark.parametrize("query,expected_action,expected_target", [
    ("join the AI/ML workgroup", "join", "AI/ML"),
    ("leave PQC group", "leave", "PQC"),
    ("follow the Next Gen programme", "join", "Next Gen"),
    ("unfollow Wi-Fi Design group", "leave", "Wi-Fi Design"),
    ("add the IoT HaLow workgroup", "join", "IoT HaLow"),
    ("remove AI/ML", "leave", "AI/ML"),
])
def test_parse_action_and_target(query, expected_action, expected_target):
    action, target = _parse_action_and_target(query)
    assert action == expected_action
    assert target is not None
    assert expected_target.lower() in target.lower()


def test_parse_unrecognised_returns_none():
    action, target = _parse_action_and_target("what is Wi-Fi 7")
    assert action is None


# ── handle() never raises ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_no_user_id_returns_friendly_message():
    result = await handle("join the AI/ML workgroup", user_id=None, neo4j_client=None)
    assert isinstance(result, str)
    assert len(result) > 0
    # Should not raise, should return a helpful string


@pytest.mark.asyncio
async def test_handle_no_neo4j_client_returns_friendly_message():
    result = await handle("join the PQC group", user_id="user-123", neo4j_client=None)
    assert isinstance(result, str)
    # No match possible without Neo4j → friendly not-found message


@pytest.mark.asyncio
async def test_handle_neo4j_error_returns_friendly_message():
    """Neo4j query failure must NOT propagate — handle() catches it."""
    bad_client = MagicMock()
    bad_client.execute_query = MagicMock(side_effect=RuntimeError("Neo4j down"))

    # Should not raise
    result = await handle("join the AI/ML workgroup", user_id="user-123", neo4j_client=bad_client)
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_handle_ambiguous_match_returns_disambiguation():
    mock_client = MagicMock()
    mock_client.execute_query = MagicMock(return_value=[
        {"datasource_id": "wba_extranet_aa1", "name": "AI/ML Working Group"},
        {"datasource_id": "wba_extranet_aa2", "name": "AI/ML Sub-Group"},
    ])

    result = await handle("join AI/ML", user_id="user-123", neo4j_client=mock_client)
    assert isinstance(result, str)
    # Should ask user to be more specific
    assert "AI/ML" in result or "specific" in result.lower() or "found" in result.lower()


@pytest.mark.asyncio
async def test_handle_successful_join():
    mock_client = MagicMock()
    mock_client.execute_query = MagicMock(return_value=[
        {"datasource_id": "wba_extranet_abc", "name": "AI/ML Working Group"},
    ])

    _mod._call_backend = AsyncMock(return_value=True)
    result = await handle("join the AI/ML workgroup", user_id="user-123", neo4j_client=mock_client)

    assert "joined" in result.lower() or "done" in result.lower()
    assert "AI/ML Working Group" in result


@pytest.mark.asyncio
async def test_handle_successful_leave():
    mock_client = MagicMock()
    mock_client.execute_query = MagicMock(return_value=[
        {"datasource_id": "wba_extranet_abc", "name": "PQC Group"},
    ])

    _mod._call_backend = AsyncMock(return_value=True)
    result = await handle("leave PQC", user_id="user-123", neo4j_client=mock_client)

    assert "left" in result.lower() or "done" in result.lower()


@pytest.mark.asyncio
async def test_handle_backend_failure_does_not_raise():
    mock_client = MagicMock()
    mock_client.execute_query = MagicMock(return_value=[
        {"datasource_id": "wba_extranet_abc", "name": "PQC Group"},
    ])

    _mod._call_backend = AsyncMock(return_value=False)
    # Must not raise
    result = await handle("join PQC", user_id="user-123", neo4j_client=mock_client)

    assert isinstance(result, str)
    assert "wrong" in result.lower() or "failed" in result.lower() or "try again" in result.lower()
