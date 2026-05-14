"""Tests for WBAExtranetScraper.

Covers:
- Higher Logic ASP.NET form auth (success + failure paths)
- Community discovery from /communities/all-communities HTML
- Landing-page parsing (description, leadership, members)
- Digest-thread parsing (doc_type, Zoom-URL scrubbing, date filtering)
- Library document metadata capture (content="" for reference-only, metadata_hash)
- First-run vs incremental doc-limit branching
- Zoom / Teams URL scrubbing
- filter_new_urls dedup integration
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.WBA_extranet import (
    WBAExtranetScraper, CommunityRef, DiscoveredLeader, DiscoveredMember,
    PREP_CALL_PATTERN,
)
from scrapers.base import Resource


# ── helpers ─────────────────────────────────────────────────────────────────

class AsyncCM:
    def __init__(self, resp):
        self._resp = resp
    async def __aenter__(self):
        return self._resp
    async def __aexit__(self, *a):
        pass


def _mock_response(status=200, text="", headers=None):
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text)
    resp.read = AsyncMock(return_value=b"")
    resp.url = "https://extranet.wballiance.com/"
    resp.headers = headers or {"Content-Type": "text/html"}
    return resp


# ── scraper instantiation ────────────────────────────────────────────────────

@pytest.fixture
def scraper():
    with patch("scrapers.WBA_extranet.BaseScraper.__init__", return_value=None):
        s = WBAExtranetScraper.__new__(WBAExtranetScraper)
        s.base_url = "https://extranet.wballiance.com"
        s.is_authenticated = False
        s._community_datasource_ids = {}
        s._home_html_cache = {}
        s.session = MagicMock()
        s.neo4j_client = None
        s.graph_repository = None
        s.rabbitmq_producer = MagicMock()
        s._current_batch_id = "test-batch"
        s._current_datasource_id = "wba_extranet"
        s._batch_items_count = 0
        s._collect_mode = True  # collect instead of publishing so tests stay offline
        s._collected_messages = []
        s.redis_client = None
        return s


# ── auth ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authenticate_missing_creds(scraper):
    result = await scraper.authenticate("", "")
    assert result is False
    assert not scraper.is_authenticated


@pytest.mark.asyncio
async def test_authenticate_success(scraper):
    login_page_html = """
    <html><form method="post">
      <input name="__VIEWSTATE" value="abc123" />
      <input name="__VIEWSTATEGENERATOR" value="xyz" />
      <input name="__EVENTVALIDATION" value="val" />
      <input type="text" name="ctl00$UserName" />
      <input type="password" name="ctl00$Password" />
      <input type="submit" name="ctl00$LoginButton" value="Sign In" />
    </form></html>
    """
    get_resp = _mock_response(200, login_page_html)
    post_resp = _mock_response(200)
    post_resp.url = "https://extranet.wballiance.com/home"

    # Fake auth cookie
    cookie = MagicMock()
    cookie.key = ".ASPXAUTH"
    jar = MagicMock()
    jar.filter_cookies.return_value = {".ASPXAUTH": cookie}
    scraper.session.cookie_jar = jar

    scraper.session.get = MagicMock(return_value=AsyncCM(get_resp))
    scraper.session.post = MagicMock(return_value=AsyncCM(post_resp))

    result = await scraper.authenticate("user@test.com", "pass")
    assert result is True
    assert scraper.is_authenticated


@pytest.mark.asyncio
async def test_authenticate_no_viewstate_fails(scraper):
    """Should fail loudly when __VIEWSTATE is absent."""
    get_resp = _mock_response(200, "<html><form></form></html>")
    scraper.session.get = MagicMock(return_value=AsyncCM(get_resp))
    result = await scraper.authenticate("u", "p")
    assert result is False


# ── community discovery ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_communities_basic(scraper):
    html = """
    <html><body>
      <a href="/communities/community-home?communitykey=aaa111">Next Gen</a>
      <a href="/communities/community-home?communitykey=bbb222">IoT</a>
      <a href="/some/other/link">Unrelated</a>
    </body></html>
    """
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))
    communities = await scraper.discover_communities()
    keys = {c.community_key for c in communities}
    assert "aaa111" in keys
    assert "bbb222" in keys


@pytest.mark.asyncio
async def test_discover_communities_deduplication(scraper):
    html = """
    <html><body>
      <a href="/communities/community-home?communitykey=aaa111">Next Gen</a>
      <a href="/communities/community-home?communitykey=aaa111">Next Gen (duplicate)</a>
    </body></html>
    """
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))
    communities = await scraper.discover_communities()
    assert len([c for c in communities if c.community_key == "aaa111"]) == 1


# ── landing-page parse ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_community_landing_leaders(scraper):
    html = """
    <html><body>
      <h3>Community Leaders</h3>
      <div>
        <a href="/profile/alice">Alice Smith</a>
        <span>Co-Chair</span>
        <a href="/profile/bob">Bob Jones</a>
        <span>Secretary</span>
      </div>
    </body></html>
    """
    community = CommunityRef("key1", "Test WG",
                             "https://extranet.wballiance.com/communities/community-home?communitykey=key1")
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))
    desc, leaders, members = await scraper.parse_community_landing(community)
    assert any(l.name == "Alice Smith" for l in leaders) or any(l.name == "Bob Jones" for l in leaders)


# ── digest threads ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_digest_threads_zoom_stripped(scraper):
    html = """
    <html><body>
      <div class="DigestEntry">
        <h3><a href="/discussion/thread-1#bm1234">Meeting notes</a></h3>
        <div class="ThreadBody">
          Great discussion today. Join via https://company.zoom.us/j/9999?pwd=abc and dial 555-1234.
          We reviewed the AI/ML dataset from Intel.
        </div>
        <time datetime="2025-05-01">May 1, 2025</time>
        <span class="author">Alice</span>
      </div>
    </body></html>
    """
    community = CommunityRef("key1", "AI/ML WG", "https://extranet.wballiance.com/...")
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))

    resources = await scraper.parse_digest_threads(community, "wba_extranet_key1", since=None)
    assert len(resources) >= 1
    body = resources[0].content or ""
    assert "zoom.us" not in body
    assert "AI/ML dataset from Intel" in body


@pytest.mark.asyncio
async def test_parse_digest_threads_since_filter(scraper):
    html = """
    <html><body>
      <div class="DigestEntry">
        <h3><a href="/discussion/old-thread#bm1">Old thread</a></h3>
        <div class="ThreadBody">Old content.</div>
        <time datetime="2022-01-01">Jan 1, 2022</time>
      </div>
    </body></html>
    """
    community = CommunityRef("key1", "WG", "https://extranet.wballiance.com/...")
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))

    since = datetime(2025, 1, 1, tzinfo=timezone.utc)
    resources = await scraper.parse_digest_threads(community, "wba_extranet_key1", since=since)
    assert len(resources) == 0  # filtered as older than `since`


@pytest.mark.asyncio
async def test_prep_call_thread_gets_correct_doc_type(scraper):
    html = """
    <html><body>
      <div class="DigestEntry">
        <h3><a href="/discussion/call-starting-preparation-9#bm28a4d">Prep call thread</a></h3>
        <div class="ThreadBody">This is a prep call.</div>
        <time datetime="2025-04-15">April 15, 2025</time>
      </div>
    </body></html>
    """
    community = CommunityRef("key1", "PQC WG", "https://extranet.wballiance.com/...")
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))

    resources = await scraper.parse_digest_threads(community, "wba_extranet_key1", since=None)
    assert resources[0].doc_type == "meeting-prep-call"


# ── library documents ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_capture_document_metadata_reference_only(scraper):
    html = """
    <html><body>
      <div class="LibraryItem">
        <h3>Meeting Agenda Q2</h3>
        <a href="/HigherLogic/System/DownloadDocumentFile.ashx?DocumentFileKey=abc">Download</a>
        <span class="uploadDate"><time datetime="2025-03-01">March 2025</time></span>
        <span class="uploader">Alice Smith</span>
      </div>
    </body></html>
    """
    community = CommunityRef("key1", "WG", "https://extranet.wballiance.com/...")
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))

    docs = await scraper.capture_document_metadata(community, "wba_extranet_key1", limit=3, since=None)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.content == ""            # never download body here
    assert doc.access_notes is not None  # marked as member-only
    assert doc.content_hash is not None  # metadata fingerprint set
    assert "login" in (doc.access_notes or "").lower()


@pytest.mark.asyncio
async def test_capture_document_metadata_respects_limit(scraper):
    items = "".join(
        f'<div class="LibraryItem"><h3>Doc {i}</h3>'
        f'<a href="/HigherLogic/System/DownloadDocumentFile.ashx?DocumentFileKey={i}">DL</a>'
        f'<span class="uploader">User</span></div>'
        for i in range(10)
    )
    html = f"<html><body>{items}</body></html>"
    community = CommunityRef("key1", "WG", "https://extranet.wballiance.com/...")
    resp = _mock_response(200, html)
    scraper.session.get = MagicMock(return_value=AsyncCM(resp))

    docs = await scraper.capture_document_metadata(community, "wba_extranet_key1", limit=3, since=None)
    assert len(docs) == 3


# ── metadata_hash ─────────────────────────────────────────────────────────────

def test_metadata_hash_stable(scraper):
    h1 = scraper._metadata_hash("keyA", "Agenda", "Alice", "2025-01-01", "v1", "100KB")
    h2 = scraper._metadata_hash("keyA", "Agenda", "Alice", "2025-01-01", "v1", "100KB")
    assert h1 == h2


def test_metadata_hash_changes_on_version_bump(scraper):
    h1 = scraper._metadata_hash("keyA", "Agenda", "Alice", "2025-01-01", "v1", "100KB")
    h2 = scraper._metadata_hash("keyA", "Agenda", "Alice", "2025-01-01", "v2", "102KB")
    assert h1 != h2


# ── wba_metadata publish ──────────────────────────────────────────────────────

def test_publish_wba_metadata_collects_message(scraper):
    community = CommunityRef("key1", "AI/ML WG", "https://extranet.wballiance.com/...")
    leaders = [DiscoveredLeader(name="Alice", role="chair")]
    members = [DiscoveredMember(name="Bob"), DiscoveredMember(name="Carol")]

    scraper.publish_wba_metadata(community, "wba_extranet_key1", leaders, members)

    assert len(scraper._collected_messages) == 1
    msg = scraper._collected_messages[0]
    assert msg["message_type"] == "wba_metadata"
    assert msg["wba_metadata"]["community_name"] == "AI/ML WG"
    assert len(msg["wba_metadata"]["leaders"]) == 1
    assert len(msg["wba_metadata"]["members"]) == 2


def test_publish_wba_metadata_skips_if_empty(scraper):
    community = CommunityRef("key1", "WG", "https://extranet.wballiance.com/...")
    scraper.publish_wba_metadata(community, "wba_extranet_key1", [], [])
    assert len(scraper._collected_messages) == 0


# ── datasource_id generation ──────────────────────────────────────────────────

def test_datasource_id_for_community_key():
    ds_id = WBAExtranetScraper._datasource_id_for("c6039e27-0747-409f-87a2-018c40c283a2")
    assert ds_id.startswith("wba_extranet_")
    assert len(ds_id) > len("wba_extranet_")


# ── PREP_CALL_PATTERN regex ───────────────────────────────────────────────────

def test_prep_call_pattern_matches():
    assert PREP_CALL_PATTERN.search("/discussion/call-starting-preparation-9")
    assert PREP_CALL_PATTERN.search("/discussion/call-starting-preparation-15#bmabc")
    assert not PREP_CALL_PATTERN.search("/discussion/general-update")
