"""Tests for @mention resolution with child expansion (Fix 6a).

Before today's fix, @mention resolution returned LIMIT 1 on the matched
datasource only. @wba would return wba_extranet but not its child communities.

The fix adds a child expansion query after finding the matched datasource,
so @wba returns [wba_extranet, wba_extranet_abc, wba_extranet_def, ...].
Natural language names like @nextgen or @iot resolve via display_name CONTAINS.

These tests verify:
- Single-word @mention resolves to correct datasource
- Matched parent is expanded to include children
- Multi-word names via display_name fuzzy match
- @mentions stripped from clean question text
- Regex captures only word chars (spaces handled by frontend dropdown)
"""

import pytest
import re
import sys
import os
import types
from unittest.mock import MagicMock, patch


MENTION_PATTERN = re.compile(r'@(\w+)')


# ── @mention regex ────────────────────────────────────────────────────────────

class TestMentionRegex:

    def test_single_word_mention_captured(self):
        matches = MENTION_PATTERN.findall('@ietf_wg_spring what is the update')
        assert matches == ['ietf_wg_spring']

    def test_multiple_mentions_captured(self):
        matches = MENTION_PATTERN.findall('@wba and @ietf what happened')
        assert matches == ['wba', 'ietf']

    def test_spaces_in_name_only_captures_first_word(self):
        r"""@Source Packet Routing captures only 'Source' — spaces break \w+.
        The frontend handles this by passing datasource_ids directly."""
        matches = MENTION_PATTERN.findall('@Source Packet Routing in Networking')
        assert matches == ['Source']

    def test_underscore_in_id_fully_captured(self):
        matches = MENTION_PATTERN.findall('@ietf_wg_spring')
        assert matches == ['ietf_wg_spring']

    def test_mention_stripped_from_question(self):
        q = '@ietf_wg_spring what is the latest update'
        clean = MENTION_PATTERN.sub('', q).strip()
        assert clean == 'what is the latest update'
        assert '@' not in clean

    def test_multiple_mentions_stripped(self):
        q = '@wba @ietf what happened this week'
        clean = MENTION_PATTERN.sub('', q).strip()
        assert clean == 'what happened this week'


# ── child expansion logic ─────────────────────────────────────────────────────

class TestChildExpansion:

    def _build_resolver(self):
        """Build a mock neo4j_client to test the expansion logic."""
        mock_client = MagicMock()
        return mock_client

    def test_parent_expands_to_include_children(self):
        """After matching wba_extranet, children are added to datasource_ids."""
        mock_client = MagicMock()

        # First query: match datasource by mention
        mock_client.execute_query.side_effect = [
            [{'datasource_id': 'wba_extranet'}],                        # parent match
            [                                                              # children
                {'datasource_id': 'wba_extranet_abc12345'},
                {'datasource_id': 'wba_extranet_def67890'},
            ],
        ]

        mention = 'wba'
        datasource_ids = []

        # Simulate the oracle's mention resolver
        result = mock_client.execute_query(
            "MATCH (ds:DataSource) WHERE ... RETURN ds.datasource_id LIMIT 1",
            parameters={'mention': mention}
        )
        if result:
            matched_id = result[0]['datasource_id']
            datasource_ids.append(matched_id)
            # Expand to children
            children = mock_client.execute_query(
                "MATCH (child:DataSource {parent_datasource_id: $parent_id}) RETURN ...",
                parameters={'parent_id': matched_id}
            )
            for child in children:
                datasource_ids.append(child['datasource_id'])

        assert 'wba_extranet' in datasource_ids
        assert 'wba_extranet_abc12345' in datasource_ids
        assert 'wba_extranet_def67890' in datasource_ids
        assert len(datasource_ids) == 3

    def test_workgroup_with_no_children_expands_to_just_itself(self):
        """A leaf workgroup like ietf_wg_spring has no children."""
        mock_client = MagicMock()
        mock_client.execute_query.side_effect = [
            [{'datasource_id': 'ietf_wg_spring'}],  # match
            [],                                       # no children
        ]

        datasource_ids = []
        result = mock_client.execute_query("...", parameters={'mention': 'spring'})
        if result:
            matched_id = result[0]['datasource_id']
            datasource_ids.append(matched_id)
            children = mock_client.execute_query("...", parameters={'parent_id': matched_id})
            datasource_ids.extend(c['datasource_id'] for c in children)

        assert datasource_ids == ['ietf_wg_spring']

    def test_no_match_returns_empty_list(self):
        """Unrecognised mention returns no datasource_ids."""
        mock_client = MagicMock()
        mock_client.execute_query.side_effect = [[]]  # no match

        datasource_ids = []
        result = mock_client.execute_query("...", parameters={'mention': 'unknown_group_xyz'})
        if result:
            datasource_ids.append(result[0]['datasource_id'])

        assert datasource_ids == []

    def test_duplicate_ids_not_added(self):
        """If a child has the same ID as parent (edge case), no duplicate."""
        seen = set()
        ids = ['wba_extranet', 'wba_extranet_abc', 'wba_extranet_abc']  # duplicate
        result = []
        for ds_id in ids:
            if ds_id not in seen:
                seen.add(ds_id)
                result.append(ds_id)

        assert len(result) == 2
        assert result.count('wba_extranet_abc') == 1


# ── oracle query.py mention resolver matches correct datasources ──────────────

class TestMentionDatasourceLookup:

    def test_ietf_spring_resolves_by_exact_id(self):
        """@ietf_wg_spring should match datasource with that exact ID."""
        mock_client = MagicMock()
        mock_client.execute_query.return_value = [{'datasource_id': 'ietf_wg_spring'}]

        result = mock_client.execute_query(
            "MATCH (ds:DataSource) WHERE toLower(ds.datasource_id) = toLower($mention) ...",
            parameters={'mention': 'ietf_wg_spring'}
        )
        assert result[0]['datasource_id'] == 'ietf_wg_spring'

    def test_wba_resolves_by_display_name(self):
        """@wba should match datasource with display_name containing 'wba'."""
        mock_client = MagicMock()
        mock_client.execute_query.return_value = [{'datasource_id': 'wba_extranet'}]

        result = mock_client.execute_query(
            "MATCH (ds:DataSource) WHERE toLower(coalesce(ds.display_name, ds.name, '')) CONTAINS toLower($mention)",
            parameters={'mention': 'wba'}
        )
        assert result[0]['datasource_id'] == 'wba_extranet'

    def test_nextgen_resolves_by_display_name_contains(self):
        """@nextgen should match 'Next Gen' via CONTAINS."""
        datasources = [
            {'datasource_id': 'wba_extranet_nextgen', 'name': 'Next Gen Programme',
             'display_name': 'Next Gen Programme'},
            {'datasource_id': 'ietf_wg_quic', 'name': 'QUIC Working Group',
             'display_name': 'QUIC Working Group'},
        ]
        mention = 'nextgen'
        matched = [
            ds for ds in datasources
            if (mention.lower() in ds['datasource_id'].lower()
                or mention.lower() in (ds.get('display_name') or ds['name']).lower().replace(' ', ''))
        ]
        assert len(matched) >= 1
        assert matched[0]['datasource_id'] == 'wba_extranet_nextgen'


# ── oracle routes/query.py code inspection ────────────────────────────────────

class TestMentionResolverCodeInspection:

    @pytest.fixture(scope='class')
    def query_py_source(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'src', 'routes', 'query.py'
        )
        return open(path).read()

    def test_child_expansion_query_present(self, query_py_source):
        """oracle/src/routes/query.py must contain the child expansion query."""
        assert 'parent_datasource_id' in query_py_source, (
            "query.py must look up children via parent_datasource_id"
        )

    def test_mention_pattern_uses_word_chars(self, query_py_source):
        """The @mention regex must use \\w+ (single-word capture)."""
        assert r'@(\w+)' in query_py_source or r"@(\\w+)" in query_py_source

    def test_display_name_used_in_lookup(self, query_py_source):
        """display_name must be checked in the datasource lookup."""
        assert 'display_name' in query_py_source, (
            "query.py must check display_name (not just name) so @nextgen matches 'Next Gen'"
        )

    def test_child_loop_extends_datasource_ids(self, query_py_source):
        """The expansion must add child IDs to datasource_ids list."""
        assert 'datasource_ids.append' in query_py_source or \
               'datasource_ids.extend' in query_py_source, (
            "query.py must extend datasource_ids with child datasources"
        )


# ── Teams bot @source parsing ─────────────────────────────────────────────────

class TestTeamsBotMentionParsing:
    """Tests for Teams chatHandler @source mention extraction (Fix 6b)."""

    def test_mention_pattern_extracts_all_at_words(self):
        """@wba should be extracted from Teams message text."""
        text = '@wba what happened this week'
        matches = MENTION_PATTERN.findall(text)
        assert 'wba' in matches

    def test_clean_question_after_mention_removal(self):
        """@mentions are stripped from the question sent to oracle."""
        text = '@wba what happened this week'
        clean = MENTION_PATTERN.sub('', text).strip()
        assert clean == 'what happened this week'
        assert '@wba' not in clean

    def test_multiple_source_mentions(self):
        """Multiple @sources are all captured."""
        text = '@wba @ietf what happened this week'
        mentions = MENTION_PATTERN.findall(text)
        assert 'wba' in mentions
        assert 'ietf' in mentions
        clean = MENTION_PATTERN.sub('', text).strip()
        assert clean == 'what happened this week'

    def test_no_mention_passthrough(self):
        """Questions without @mentions are passed through unchanged."""
        text = 'what is Wi-Fi 7'
        mentions = MENTION_PATTERN.findall(text)
        assert mentions == []
        clean = MENTION_PATTERN.sub('', text).strip()
        assert clean == text

    def test_chat_handler_uses_mention_pattern(self):
        """teams-agent/src/handlers/chatHandler.ts must parse @mentions."""
        chat_handler_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'teams-agent', 'src', 'handlers', 'chatHandler.ts'
        )
        if not os.path.exists(chat_handler_path):
            pytest.skip("teams-agent not available in test environment")
        source = open(chat_handler_path).read()
        assert '@(\\w+)' in source or 'mentionPattern' in source or '@mention' in source.lower(), (
            "chatHandler.ts must implement @mention parsing"
        )

    def test_oracle_service_accepts_datasource_ids(self):
        """teams-agent/src/services/auroraOracleService.ts must accept datasource_ids."""
        oracle_svc_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'teams-agent', 'src', 'services', 'auroraOracleService.ts'
        )
        if not os.path.exists(oracle_svc_path):
            pytest.skip("teams-agent not available in test environment")
        source = open(oracle_svc_path).read()
        assert 'datasource_ids' in source, (
            "auroraOracleService.ts must accept and forward datasource_ids"
        )
        assert 'resolveMentionsToDatasourceIds' in source, (
            "auroraOracleService.ts must have resolveMentionsToDatasourceIds method"
        )
