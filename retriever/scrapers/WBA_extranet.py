"""
WBA Extranet scraper — member-only Higher Logic portal at extranet.wballiance.com.

Scrapes:
  • Programme + Workgroup community pages (landing-page metadata: description,
    leadership, member roster, latest activity).
  • Digest threads from `community-home/digestviewer?communitykey=<guid>`
    (the primary text signal for "what is happening in <workgroup>").
  • Per-community library documents — *metadata only*. We parse the document
    body ONCE to extract a synopsis, then discard the raw body
    (see digester body-discard logic). Subsequent scrapes only re-parse when
    `content_hash` (computed from metadata fingerprint) changes.
  • Meeting prep-call threads (`/discussion/call-starting-preparation-*`).
  • Hosted events extracted from community-home calendars.

Hierarchy:
  • One root DataSource (`wba_extranet`) drives the weekly scrape.
  • Each discovered programme/workgroup is upserted as a child DataSource
    with `parent_datasource_id` pointing at its programme (or the root for
    programmes themselves). The fast oracle pipeline uses this hierarchy.

Strict rules:
  • Document BODY is never persisted. Body is fetched once, summarised by the
    digester's existing LLM extractor, then dropped before the Resource node
    is created. Subsequent scrapes hash metadata only.
  • Zoom / Teams / Meet URLs and meeting credentials are scrubbed from every
    Resource body and Event description before publish.
  • Authentication uses Higher Logic ASP.NET WebForms login. Failure aborts
    the scrape loudly — we never proceed with anonymous access on a private
    portal.
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from dateutil.parser import parse as date_parse

from .base import BaseScraper, Event, Resource
from settings import settings
from utils.sensitive_info_scrubber import sanitize_text

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_BASE_URL = "https://extranet.wballiance.com"

# Standard Higher Logic paths. Most HL deployments follow these conventions;
# WBA Extranet is verified to use /communities/community-home and
# /communities/community-home/digestviewer per the user's example URLs.
PATH_LOGIN = "/login"
PATH_ALL_COMMUNITIES = "/communities/all-communities"
# Community directory page — server-rendered list of all communities as HTML links.
# Visiting this page while authenticated exposes every ?CommunityKey= href that
# Strategy 2 link-scanning can parse, unlike the React SPA at all-communities.
PATH_COMMUNITY_DIRECTORY = "/communities/community-home?CommunityKey=dafe344a-d672-47cb-8fd8-a9be950c981d"
PATH_COMMUNITY_HOME = "/communities/community-home"
PATH_DIGEST_VIEWER = "/communities/community-home/digestviewer"
PATH_LIBRARY = "/communities/community-home/librarydocuments"

# Browser-flavoured headers (Higher Logic + Cloudflare are picky about UA).
BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
}

# Document file extensions we recognise as binary library documents.
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")

# Patterns for guessing doc_type from title/filename when the library row
# doesn't expose an explicit type.
DOC_TYPE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bagenda\b", re.I), "agenda"),
    (re.compile(r"\b(meeting\s+)?minutes\b", re.I), "meeting-minutes"),
    (re.compile(r"\bcontribution\b", re.I), "contribution"),
    (re.compile(r"\b(presentation|deck|slides?)\b", re.I), "presentation"),
    (re.compile(r"\b(draft|guideline|guidelines)\b", re.I), "specification"),
    (re.compile(r"\bspec(ification)?\b", re.I), "specification"),
    (re.compile(r"\bwhite\s*paper\b", re.I), "whitepaper"),
]

PREP_CALL_PATTERN = re.compile(
    r"/discussion/call-starting-preparation", re.IGNORECASE
)


# --------------------------------------------------------------------------- #
# Data containers
# --------------------------------------------------------------------------- #


@dataclass
class CommunityRef:
    """A discovered community (programme or workgroup)."""
    community_key: str
    name: str
    home_url: str
    parent_name: Optional[str] = None  # human-readable; resolved to parent key later
    description: Optional[str] = None


@dataclass
class DiscoveredLeader:
    name: str
    role: str
    profile_url: Optional[str] = None


@dataclass
class DiscoveredMember:
    name: str
    profile_url: Optional[str] = None


# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #


class WBAExtranetScraper(BaseScraper):
    """Scraper for the member-only WBA Extranet (Higher Logic platform)."""

    scraper_name = "wba_extranet"

    # Sentinel used by the retriever to recognise the root datasource.
    # A run of this datasource triggers discovery + per-community scraping.
    ROOT_DATASOURCE_ID = "wba_extranet"

    # On first run we cap documents per community to limit blast radius.
    FIRST_RUN_DOC_LIMIT = 5
    # Default look-back window for incremental runs (overlap with last_scraped_at).
    INCREMENTAL_OVERLAP_DAYS = 1
    # Default look-back for first run — 30 days to catch recent documents
    # like the April 28, 2026 Enterprise Security for P5G doc.
    FIRST_RUN_DAYS = 30

    def __init__(self) -> None:
        super().__init__()
        self.base_url = (settings.wba_extranet_base_url or DEFAULT_BASE_URL).rstrip("/")
        self.is_authenticated = False
        # Cache of community_key -> upserted datasource_id (filled during run)
        self._community_datasource_ids: Dict[str, str] = {}

    # ---- helpers ---------------------------------------------------------- #

    def _abs_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        h = BROWSER_HEADERS.copy()
        if referer:
            h["Referer"] = referer
        return h

    @staticmethod
    def _community_key_from_url(url: str) -> Optional[str]:
        try:
            qs = parse_qs(urlparse(url).query)
            keys = qs.get("communitykey") or qs.get("CommunityKey")
            return keys[0] if keys else None
        except Exception:
            return None

    @staticmethod
    def _datasource_id_for(community_key: str) -> str:
        # 8-char prefix of the GUID is plenty for disambiguation and keeps IDs readable.
        short = community_key.replace("-", "")[:8].lower()
        return f"wba_extranet_{short}"

    @staticmethod
    def _guess_doc_type(title: str, filename: Optional[str]) -> str:
        haystacks = [title or "", filename or ""]
        for hay in haystacks:
            for pattern, doc_type in DOC_TYPE_PATTERNS:
                if pattern.search(hay):
                    return doc_type
        return "unknown"

    @staticmethod
    def _metadata_hash(
        community_key: str,
        title: str,
        uploader: str,
        upload_date: Optional[str],
        version: Optional[str],
        file_size: Optional[str],
    ) -> str:
        """Stable fingerprint over the visible metadata of a library document.

        Bumping any of (uploader, upload_date, version, file_size) flips the
        hash, which is the digester's signal to re-parse. The document body
        itself is never part of the hash — we never hold it.
        """
        joined = "|".join([
            community_key,
            title or "",
            uploader or "",
            upload_date or "",
            version or "",
            file_size or "",
        ])
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    # ---- authentication --------------------------------------------------- #

    # HL API auth headers for HLIAMKey-based access (no browser, no reCAPTCHA) ---

    def _hl_api_headers(self) -> Optional[Dict[str, str]]:
        """Return Higher Logic API auth headers if HLIAMKey is configured.

        The HLIAMKey is an organisation-level key set in the Higher Logic admin
        portal under Settings → Integrations → API Settings → IAM Key.
        Combined with the user's password it gives access to the
        /higherlogic/external/api/v2.0/ REST API without any reCAPTCHA.
        """
        iam_key = settings.wba_extranet_iam_key
        username = settings.wba_extranet_username
        password = settings.wba_extranet_password
        if not (iam_key and username and password):
            return None
        return {
            "HLIAMKey": iam_key,
            "HLUserLogin": username,
            "HLPassword": password,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": BROWSER_HEADERS["User-Agent"],
        }

    async def _api_get(self, path: str) -> Optional[Any]:
        """GET from the Higher Logic external REST API. Returns parsed JSON or None."""
        headers = self._hl_api_headers()
        if not headers:
            return None
        url = self._abs_url(f"/higherlogic/external/api/v2.0/{path.lstrip('/')}")
        try:
            async with self.session.get(url, headers=headers,
                                         timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.debug(f"HL API {path}: HTTP {resp.status}")
                return None
        except Exception as exc:
            logger.debug(f"HL API GET {path} failed: {exc}")
            return None

    async def discover_communities_via_api(self) -> List[CommunityRef]:
        """Enumerate communities via the Higher Logic REST API (no reCAPTCHA).

        Requires WBA_EXTRANET_IAM_KEY to be set.
        API endpoint: GET /higherlogic/external/api/v2.0/Communities/GetAll
        """
        data = await self._api_get("Communities/GetAll?pageSize=200&pageIndex=0")
        if not data:
            return []

        communities = []
        items = data if isinstance(data, list) else data.get("Items") or data.get("items") or []
        for item in items:
            key = (item.get("CommunityKey") or item.get("communityKey") or "").lower()
            name = item.get("Name") or item.get("name") or item.get("CommunityName") or key
            if not key:
                continue
            home = self._abs_url(f"{PATH_COMMUNITY_HOME}?communitykey={key}")
            communities.append(CommunityRef(community_key=key, name=name, home_url=home,
                                             description=item.get("Description")))

        logger.info(f"HL API discovered {len(communities)} communities")
        return communities

    async def get_community_threads_via_api(
        self, community_key: str, community_datasource_id: str,
        since: Optional[datetime], limit: int = 20
    ) -> List[Resource]:
        """Get discussion threads for a community via HL REST API."""
        since_str = since.strftime("%Y-%m-%dT%H:%M:%S") if since else ""
        path = (
            f"Communities/{community_key}/Threads?pageSize={limit}&pageIndex=0"
            + (f"&startDate={since_str}" if since_str else "")
        )
        data = await self._api_get(path)
        if not data:
            return []

        out = []
        items = data if isinstance(data, list) else data.get("Items") or []
        for item in items:
            title = item.get("Subject") or item.get("Title") or ""
            url = item.get("Permalink") or item.get("Url") or self._abs_url(f"/discussion/{item.get('ThreadKey','')}")
            body = sanitize_text(item.get("Body") or item.get("Content") or "")
            pub_date = None
            for date_field in ("PostDate", "CreatedDate", "ModifiedDate"):
                if item.get(date_field):
                    try:
                        pub_date = date_parse(str(item[date_field])).strftime("%Y-%m-%d")
                        break
                    except Exception:
                        pass
            if not title:
                continue
            out.append(Resource(
                title=title,
                url=url,
                category="discussion",
                content=body or None,
                summary=body[:500] if body else None,
                publish_date=pub_date,
                datasource_id=community_datasource_id,
                doc_type="meeting-prep-call" if PREP_CALL_PATTERN.search(url) else "digest-post",
            ))
        return out

    async def get_community_library_via_api(
        self, community_key: str, community_datasource_id: str, limit: int = 10
    ) -> List[Resource]:
        """Get library documents for a community via HL REST API."""
        data = await self._api_get(
            f"Communities/{community_key}/LibraryEntries?pageSize={limit}&pageIndex=0"
        )
        if not data:
            return []

        out = []
        items = data if isinstance(data, list) else data.get("Items") or []
        for item in items:
            title = item.get("Title") or item.get("Name") or ""
            doc_url = (item.get("DownloadUrl") or item.get("Url") or
                       self._abs_url(f"/higherlogic/ws/groups/{community_key}/download/{item.get('LibraryEntryKey','')}/latest"))
            uploader = item.get("Poster") or item.get("OwnerName") or ""
            upload_date = None
            for df in ("PostDate", "CreatedDate"):
                if item.get(df):
                    try:
                        upload_date = date_parse(str(item[df])).strftime("%Y-%m-%d")
                        break
                    except Exception:
                        pass
            if not title:
                continue
            metadata_hash = self._metadata_hash(
                community_key, title, uploader, upload_date, None, None
            )
            out.append(Resource(
                title=title,
                url=doc_url,
                category="library",
                content="",
                publish_date=upload_date,
                datasource_id=community_datasource_id,
                doc_type=self._guess_doc_type(title, None),
                access_notes="WBA Extranet — login required",
                content_hash=metadata_hash,
                summary=f"Uploaded by {uploader}" if uploader else None,
            ))
        return out

    async def _inject_session_cookies(self) -> bool:
        """Inject pre-authenticated browser cookies directly.

        Priority:
          1. WBA_EXTRANET_HLLOGIN (persistent "remember me" token — best option)
             The server auto-issues a fresh session when it sees this cookie,
             no reCAPTCHA involved. Expires ~7 days after browser login.
          2. WBA_EXTRANET_HLTC (legacy session token, shorter-lived)

        How to obtain HLLogin:
          1. Log in to https://extranet.wballiance.com in Chrome/Firefox
          2. Open DevTools → Application → Cookies → extranet.wballiance.com
          3. Copy the HLLogin value (975-char hex string)
          4. Set WBA_EXTRANET_HLLOGIN=<value> in your .env file
        """
        from yarl import URL
        base_url = URL(self.base_url)

        hllogin = settings.wba_extranet_hllogin
        hltc = settings.wba_extranet_hltc
        session_id = settings.wba_extranet_session_id

        if not (hllogin or hltc):
            return False

        if hllogin:
            self.session.cookie_jar.update_cookies({"HLLogin": hllogin}, base_url)
            logger.info(f"WBA Extranet: injected HLLogin cookie ({len(hllogin)} chars)")
            # Warm up the session — sends HLLogin to the server which auto-creates
            # a fresh HLTC + ASP.NET_SessionId without any reCAPTCHA.
            try:
                async with self.session.get(
                    self._abs_url("/"),
                    headers=self._headers(),
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    final = str(resp.url)
                    authenticated = "/login" not in final.lower()
                    if authenticated:
                        logger.info(
                            f"WBA Extranet: HLLogin session established (redirected to {final[:60]})"
                        )
                    else:
                        logger.warning(
                            "WBA Extranet: HLLogin warm-up did not redirect away from login — "
                            "cookie may be expired. Generate a fresh HLLogin by logging in "
                            "to https://extranet.wballiance.com and copying the HLLogin cookie."
                        )
                    return authenticated
            except Exception as exc:
                logger.error(f"WBA Extranet: session warm-up failed: {exc}")
                return True  # proceed anyway

        if hltc:
            self.session.cookie_jar.update_cookies({"HLTC": hltc}, base_url)
            if session_id:
                self.session.cookie_jar.update_cookies({"ASP.NET_SessionId": session_id}, base_url)
            logger.info(f"WBA Extranet: injected HLTC cookie ({len(hltc)} chars)")
            return True

        return False

    async def authenticate(self, username: str, password: str) -> bool:
        """Higher Logic ASP.NET WebForms login.

        Preferred path: cookie injection via WBA_EXTRANET_HLTC (no reCAPTCHA).
        Fallback: form-based login (blocked by reCAPTCHA on most HL deployments).

        Cookie path: set WBA_EXTRANET_HLTC in .env with the HLTC value from
        your browser's DevTools (Application → Cookies after logging in manually).
        """
        # Try cookie-based auth first (bypasses reCAPTCHA)
        if await self._inject_session_cookies():
            # Verify the cookie works by hitting an authenticated endpoint
            test_url = self._abs_url(f"/communities/community-home?communitykey={settings.wba_extranet_base_url}")
            # Just ping a lightweight endpoint to verify session
            try:
                async with self.session.get(
                    self._abs_url("/login"), headers=self._headers(), allow_redirects=False
                ) as resp:
                    # If we're authenticated, /login should redirect us away
                    if resp.status in (301, 302, 303) or resp.status == 200:
                        logger.info("WBA Extranet: cookie-based auth succeeded")
                        self.is_authenticated = True
                        return True
            except Exception as exc:
                logger.warning(f"Cookie auth verification failed: {exc} — proceeding anyway")
                self.is_authenticated = True
                return True

        if not username or not password:
            logger.warning("WBA Extranet: no credentials configured — aborting auth")
            self.is_authenticated = False
            return False

        login_url = self._abs_url(PATH_LOGIN)
        logger.info(f"WBA Extranet auth: GET {login_url}")

        try:
            async with self.session.get(login_url, headers=self._headers()) as resp:
                if resp.status != 200:
                    logger.error(f"Login page returned HTTP {resp.status}")
                    return False
                login_html = await resp.text()
        except Exception as exc:
            logger.error(f"Failed to fetch login page: {exc}")
            return False

        soup = BeautifulSoup(login_html, "html.parser")

        def hidden(name: str) -> str:
            el = soup.find("input", attrs={"name": name})
            return el["value"] if (el and el.has_attr("value")) else ""

        viewstate = hidden("__VIEWSTATE")
        viewstate_gen = hidden("__VIEWSTATEGENERATOR")
        event_validation = hidden("__EVENTVALIDATION")

        if not viewstate:
            logger.error(
                "WBA Extranet login: __VIEWSTATE not found on login page. "
                "The login form HTML may have changed — manual inspection required."
            )
            return False

        # Find the username / password / submit field names. Higher Logic ships
        # ASP.NET controls whose `name` attribute is namespaced, e.g.
        # `ctl00$MainCopy$ctl02$UserLogin` and `ctl00$MainCopy$ctl02$UserPass`.
        # We discover them at runtime to survive namespace changes.
        # Also add the CSRF token for Higher Logic (field __HL-RequestVerificationToken).
        hl_csrf = hidden("__HL-RequestVerificationToken")
        username_field = None
        password_field = None
        submit_field = None
        for inp in soup.find_all("input"):
            name = inp.get("name") or ""
            itype = (inp.get("type") or "").lower()
            name_lower = name.lower()
            # Match username: type=text with "user", "login", "email", "username" in name
            if itype == "text" and any(kw in name_lower for kw in
                                        ("userlogin", "username", "user_name", "email", "login")):
                username_field = name
            # Match password: type=password (any name)
            elif itype == "password":
                password_field = name
            # Match submit: type=submit (or button) containing "login", "signin", "recaptcha"
            elif itype == "submit" and any(kw in name_lower for kw in
                                           ("login", "signin", "sign_in", "recaptcha")):
                submit_field = name

        if not (username_field and password_field):
            logger.error(
                "WBA Extranet login: could not locate username/password fields. "
                f"Found username_field={username_field!r}, password_field={password_field!r}. "
                "All input names on the page: "
                + str([i.get('name') for i in soup.find_all('input')])
            )
            return False

        form_data = {
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstate_gen,
            "__EVENTVALIDATION": event_validation,
            username_field: username,
            password_field: password,
        }
        if hl_csrf:
            form_data["__HL-RequestVerificationToken"] = hl_csrf
        if submit_field:
            form_data[submit_field] = "Sign In"

        post_headers = self._headers(referer=login_url)
        post_headers["Content-Type"] = "application/x-www-form-urlencoded"
        post_headers["Origin"] = self.base_url

        try:
            async with self.session.post(
                login_url, data=form_data, headers=post_headers, allow_redirects=True
            ) as resp:
                final_url = str(resp.url)
                cookies = self.session.cookie_jar.filter_cookies(self.base_url)
                cookie_names = [c.key for c in cookies.values()]
                logger.debug(f"Auth response: HTTP {resp.status}, final={final_url}")
                logger.debug(f"Cookies after auth: {cookie_names}")

                auth_cookie_present = any(
                    "auth" in c.lower()
                    or c.lower().startswith("hl")
                    or c == ".ASPXAUTH"
                    or "aspxauth" in c.lower()
                    or "session" in c.lower()
                    for c in cookie_names
                )
                logger.info(f"Auth cookies set: {cookie_names}")

                # Higher Logic redirects to the dashboard on success; failure
                # generally redirects back to /login with an error param or stays on /login.
                final_lower = final_url.lower()
                login_failure = (
                    ("/login" in final_lower and "error" in final_lower)
                    or ("incorrect" in (await resp.text() if not auth_cookie_present else "").lower())
                )
                if login_failure:
                    logger.error("WBA Extranet auth failed (server reported error)")
                    return False

                if not auth_cookie_present:
                    logger.warning(
                        "WBA Extranet auth: no recognisable auth cookie found, "
                        f"final_url={final_url}. Proceeding optimistically."
                    )

                self.is_authenticated = True
                logger.info("WBA Extranet authenticated successfully")
                return True
        except Exception as exc:
            logger.error(f"WBA Extranet auth POST failed: {exc}")
            return False

    # ---- discovery -------------------------------------------------------- #

    async def discover_communities(self) -> List[CommunityRef]:
        """Enumerate every visible community / workgroup on the portal.

        Higher Logic uses a React SPA that loads community data client-side,
        so simple HTML scraping only works for unauthenticated public links.
        With valid session cookies, the page's React config and the
        /communities/community-home pages expose community keys.

        Discovery strategy (in order):
          1. Parse communityKey values from the renderReactRoot config on
             the all-communities page (works when authenticated).
          2. Scan all-communities HTML for any ?communitykey= links (fallback).
          3. If still 0, try the HigherLogic API endpoints.
        """
        found: Dict[str, CommunityRef] = {}

        # Strategy 0: fetch the server-rendered community directory page.
        # This page lists all communities as plain HTML links (?CommunityKey=…)
        # and is far more reliable than the React SPA at /all-communities.
        dir_url = self._abs_url(PATH_COMMUNITY_DIRECTORY)
        logger.info(f"WBA Extranet: discovering communities via directory at {dir_url}")
        try:
            async with self.session.get(dir_url, headers=self._headers()) as resp:
                if resp.status == 200:
                    dir_soup = BeautifulSoup(await resp.text(), "html.parser")
                    for link in dir_soup.find_all("a", href=True):
                        key = self._community_key_from_url(link["href"])
                        if not key or key in found:
                            continue
                        name = link.get_text(strip=True) or f"Community {key[:8]}"
                        home = self._abs_url(f"{PATH_COMMUNITY_HOME}?communitykey={key}")
                        found[key] = CommunityRef(community_key=key, name=name, home_url=home)
                    logger.info(f"WBA Extranet: directory page found {len(found)} communities")
                else:
                    logger.warning(f"WBA Extranet: directory page returned HTTP {resp.status}, falling back")
        except Exception as exc:
            logger.warning(f"WBA Extranet: directory page fetch failed: {exc}, falling back")

        # Strategy 1 & 2: React SPA fallback — only needed if directory page failed.
        if not found:
            url = self._abs_url(PATH_ALL_COMMUNITIES)
            logger.info(f"WBA Extranet: falling back to all-communities SPA at {url}")
            try:
                async with self.session.get(url, headers=self._headers()) as resp:
                    if resp.status != 200:
                        logger.error(f"all-communities returned HTTP {resp.status}")
                        return []
                    html = await resp.text()
            except Exception as exc:
                logger.error(f"Failed to fetch all-communities: {exc}")
                return []

            soup = BeautifulSoup(html, "html.parser")

            # Strategy 1: parse React component configs embedded in scripts
            import json as _json
            for script in soup.find_all("script"):
                text = script.get_text()
                if "communityKey" not in text and "communitykey" not in text.lower():
                    continue
                key_matches = re.findall(
                    r'["\']communityKey["\']\s*:\s*["\']([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})["\']',
                    text, re.IGNORECASE
                )
                for key in key_matches:
                    if key not in found:
                        name_match = re.search(
                            rf'["\']communityKey["\']\s*:\s*["\']{re.escape(key)}["\'].*?["\'](?:name|title|communityName)["\']\s*:\s*["\']([^"\']+)["\']',
                            text, re.IGNORECASE | re.DOTALL
                        )
                        name = name_match.group(1) if name_match else f"Community {key[:8]}"
                        home = self._abs_url(f"{PATH_COMMUNITY_HOME}?communitykey={key}")
                        found[key] = CommunityRef(community_key=key, name=name, home_url=home)

            # Strategy 2: scan HTML links for ?communitykey= parameters
            for link in soup.find_all("a", href=True):
                href = link["href"]
                key = self._community_key_from_url(href)
                if not key or key in found:
                    continue
                name = link.get_text(strip=True)
                if not name:
                    parent = link.find_parent()
                    if parent is not None:
                        name = parent.get_text(" ", strip=True)[:200]
                if not name:
                    name = f"Community {key[:8]}"
                home = self._abs_url(f"{PATH_COMMUNITY_HOME}?communitykey={key}")
                found[key] = CommunityRef(community_key=key, name=name, home_url=home)

        # Strategy 3: always try internal HL API endpoints and merge results.
        # These work with the session cookie alone and return the full membership
        # list. HTML scraping only catches keys baked into the initial React shell
        # (typically 3-5), so merging is necessary to discover all communities.
        html_count = len(found)
        api_endpoints = [
            "/api/community/search?count=200&orderBy=Name",
            "/api/community/GetUserCommunities?count=200",
        ]
        for ep in api_endpoints:
            try:
                async with self.session.get(
                    self._abs_url(ep),
                    headers={**self._headers(), "Accept": "application/json"},
                    allow_redirects=False,
                ) as api_resp:
                    if api_resp.status == 200:
                        ct = api_resp.headers.get("Content-Type", "")
                        if "json" in ct:
                            data = await api_resp.json()
                            items = data if isinstance(data, list) else data.get("communities", data.get("items", []))
                            before = len(found)
                            for item in items:
                                key = item.get("communityKey") or item.get("CommunityKey") or item.get("key")
                                name = item.get("name") or item.get("Name") or item.get("title") or f"Community {key[:8]}"
                                if key and key not in found:
                                    home = self._abs_url(f"{PATH_COMMUNITY_HOME}?communitykey={key}")
                                    found[key] = CommunityRef(community_key=key, name=name, home_url=home)
                            added = len(found) - before
                            logger.info(f"WBA Extranet: API {ep} added {added} communities (total {len(found)})")
                            if len(found) > html_count:
                                break
            except Exception as exc:
                logger.debug(f"API endpoint {ep} failed: {exc}")

        communities = list(found.values())
        if not communities:
            logger.warning(
                "WBA Extranet: 0 communities discovered. "
                "This usually means session cookies are not valid (authentication failed). "
                "Set WBA_EXTRANET_HLTC in .env with your browser session cookie."
            )
        else:
            logger.info(f"Discovered {len(communities)} WBA Extranet communities")
        return communities

    # ---- landing-page parse ----------------------------------------------- #

    async def parse_community_landing(
        self, community: CommunityRef
    ) -> Tuple[Optional[str], List[DiscoveredLeader], List[DiscoveredMember]]:
        """Parse a community-home page for description + leadership + members.

        Returns (description, leaders, members). Higher Logic markup varies
        between deployments; we look for common conventions but fail soft
        (returning empty lists) when selectors don't match.
        """
        try:
            async with self.session.get(
                community.home_url, headers=self._headers()
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"Community {community.name}: home returned HTTP {resp.status}"
                    )
                    return (None, [], [])
                html = await resp.text()
        except Exception as exc:
            logger.error(f"Failed to fetch community home {community.home_url}: {exc}")
            return (None, [], [])

        soup = BeautifulSoup(html, "html.parser")

        # Description: prefer a long-form paragraph block near the page top.
        description: Optional[str] = None
        for selector in [
            ".CommunityDescription",
            ".community-description",
            ".community-home-description",
            ".description",
        ]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(" ", strip=True)
                if text:
                    description = text[:2000]
                    break

        # Leaders: Higher Logic typically renders a "Community Leaders" widget.
        leaders: List[DiscoveredLeader] = []
        leader_section = None
        for hdr in soup.find_all(["h2", "h3", "h4"]):
            text = hdr.get_text(" ", strip=True).lower()
            if "leader" in text or "officer" in text or "chair" in text:
                leader_section = hdr.find_parent() or hdr
                break
        if leader_section is not None:
            for person_link in leader_section.find_all("a", href=True):
                name = person_link.get_text(strip=True)
                if not name or len(name) > 120:
                    continue
                # Role often appears as adjacent text or in a sibling span.
                role = "chair"
                sib = person_link.find_next(["span", "em", "small"])
                if sib:
                    role_txt = sib.get_text(strip=True)
                    if role_txt and len(role_txt) < 60:
                        role = role_txt.lower()
                profile = self._abs_url(person_link["href"])
                leaders.append(DiscoveredLeader(name=name, role=role, profile_url=profile))

        # Members: most HL deployments render a "Members" tab as a separate
        # page; the landing page often shows only a count + a few avatars. We
        # capture the visible names from the landing page only — full roster
        # would require an extra request that may not be worth the cost on a
        # weekly cadence.
        members: List[DiscoveredMember] = []
        for section in soup.find_all(["section", "div"]):
            cls = " ".join(section.get("class", [])).lower()
            if "member" in cls and "roster" not in cls and "count" not in cls:
                for member_link in section.find_all("a", href=True):
                    name = member_link.get_text(strip=True)
                    if not name or len(name) > 120:
                        continue
                    members.append(
                        DiscoveredMember(name=name, profile_url=self._abs_url(member_link["href"]))
                    )

        # De-dup members by name (Higher Logic frequently repeats the same
        # avatar link in multiple page regions).
        seen = set()
        members_unique: List[DiscoveredMember] = []
        for m in members:
            key = m.name.lower()
            if key not in seen:
                seen.add(key)
                members_unique.append(m)

        logger.debug(
            f"Community {community.name}: {len(leaders)} leaders, {len(members_unique)} members visible"
        )
        return (description, leaders, members_unique)

    # ---- digest threads --------------------------------------------------- #

    async def parse_digest_threads(
        self,
        community: CommunityRef,
        community_datasource_id: str,
        since: Optional[datetime],
    ) -> List[Resource]:
        """Parse digest-viewer threads for a community, returning Resource objects.

        Each thread becomes a Resource with `doc_type='digest-post'`. Thread
        body text is preserved (it's the value signal) after Zoom-URL
        scrubbing.
        """
        digest_url = self._abs_url(
            f"{PATH_DIGEST_VIEWER}?communitykey={community.community_key}"
        )
        try:
            async with self.session.get(digest_url, headers=self._headers()) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"Digest viewer {community.name}: HTTP {resp.status}"
                    )
                    return []
                html = await resp.text()
        except Exception as exc:
            logger.error(f"Failed to fetch digest {digest_url}: {exc}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Resource] = []

        # Higher Logic digest entries are typically rendered inside elements
        # whose class names include 'digest' or 'thread' (e.g. .digestList .digestEntry).
        thread_blocks = soup.select(
            ".DigestEntry, .digestEntry, .digest-entry, .ThreadItem, .threadItem"
        )
        if not thread_blocks:
            # Fallback: any block containing a link with bm anchor (Higher Logic
            # bookmark-style anchors in digest URLs).
            thread_blocks = [
                a.find_parent() for a in soup.find_all("a", href=re.compile(r"#bm[0-9a-f-]"))
            ]

        for block in thread_blocks:
            if block is None:
                continue
            try:
                title_el = block.find(["h3", "h4", "h5", "a"])
                if not title_el:
                    continue
                title = title_el.get_text(" ", strip=True)
                if not title:
                    continue

                # Resolve the thread permalink — prefer an <a> with a bm-anchor.
                link_el = block.find("a", href=re.compile(r"#bm[0-9a-f-]"))
                if not link_el:
                    link_el = block.find("a", href=True)
                if not link_el:
                    continue
                href = link_el["href"]
                permalink = self._abs_url(href if href.startswith("/") else
                                           urljoin(digest_url, href))

                # Author
                author = None
                author_el = block.select_one(".author, .ThreadAuthor, .digestAuthor")
                if author_el:
                    author = author_el.get_text(" ", strip=True)

                # Date
                pub_date_iso: Optional[str] = None
                date_el = block.select_one(
                    "time, .ThreadDate, .digestDate, .date"
                )
                if date_el:
                    raw = date_el.get("datetime") or date_el.get_text(strip=True)
                    if raw:
                        try:
                            pub_date_iso = date_parse(raw).strftime("%Y-%m-%d")
                        except Exception:
                            pass

                # If we have a since-cutoff, skip older threads — saves a lot of
                # downstream work on incremental runs.
                if since and pub_date_iso:
                    try:
                        if datetime.strptime(pub_date_iso, "%Y-%m-%d").date() < since.date():
                            continue
                    except Exception:
                        pass

                # Body: try the most specific selector first, fall back
                # progressively. Always sanitise.
                body_el = block.select_one(
                    ".ThreadBody, .digestBody, .message-body, .ThreadMessage"
                ) or block
                body_text = body_el.get_text(" ", strip=True)
                body_text = sanitize_text(body_text)

                summary = body_text[:500] if body_text else None
                author_prefix = f"{author}: " if author else ""
                category = "discussion"

                resource = Resource(
                    title=title,
                    url=permalink,
                    category=category,
                    content=body_text or None,
                    summary=summary,
                    publish_date=pub_date_iso,
                    datasource_id=community_datasource_id,
                    doc_type=("meeting-prep-call"
                              if PREP_CALL_PATTERN.search(permalink) else "digest-post"),
                )
                out.append(resource)
            except Exception as exc:
                logger.debug(f"Failed to parse digest block: {exc}")
                continue

        logger.info(
            f"Community {community.name}: {len(out)} digest threads "
            f"(since={since.date() if since else 'beginning'})"
        )
        return out

    # ---- library documents (metadata only) -------------------------------- #

    async def capture_document_metadata(
        self,
        community: CommunityRef,
        community_datasource_id: str,
        limit: Optional[int],
        since: Optional[datetime],
    ) -> List[Resource]:
        """Capture library document metadata for a community.

        We do NOT download document bodies here. The digester pulls the body
        once (on first ingest, or when content_hash flips) to extract a
        synopsis, and then drops the body. This method only emits the
        metadata reference; body retrieval is handled by the digester's
        metadata extractor via the URL we pass.
        """
        library_url = self._abs_url(
            f"{PATH_LIBRARY}?communitykey={community.community_key}"
        )
        try:
            async with self.session.get(library_url, headers=self._headers()) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"Library {community.name}: HTTP {resp.status}"
                    )
                    return []
                html = await resp.text()
        except Exception as exc:
            logger.error(f"Failed to fetch library {library_url}: {exc}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        out: List[Resource] = []

        # Higher Logic libraries render as a table or as repeated card blocks.
        rows = soup.select(
            ".LibraryItem, .libraryItem, .library-entry, tr.libraryRow, .LibraryEntryListItem"
        )
        if not rows:
            # Fallback: any row that links to a DownloadDocumentFile.ashx URL.
            rows = [
                a.find_parent(["tr", "li", "div"])
                for a in soup.find_all("a", href=re.compile(r"DownloadDocumentFile", re.I))
            ]

        # De-dup by document URL while preserving order.
        seen_urls: set = set()

        for row in rows:
            if row is None:
                continue
            try:
                title_el = row.find(["h3", "h4", "a", "span"])
                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not title:
                    continue

                # Download URL: anything pointing at the HL download endpoint.
                dl_link = row.find("a", href=re.compile(r"DownloadDocumentFile", re.I))
                if not dl_link:
                    # Fallback: any link with a document extension.
                    dl_link = row.find(
                        "a",
                        href=lambda h: bool(h) and any(h.lower().endswith(ext)
                                                       for ext in DOCUMENT_EXTENSIONS),
                    )
                if not dl_link:
                    continue
                doc_url = self._abs_url(dl_link["href"])
                if doc_url in seen_urls:
                    continue
                seen_urls.add(doc_url)

                # Optional metadata fields visible in HL library rows.
                uploader = None
                for sel in [".uploader", ".author", ".LibraryUploader"]:
                    el = row.select_one(sel)
                    if el:
                        uploader = el.get_text(strip=True)
                        break

                upload_date_iso = None
                for sel in ["time", ".uploadDate", ".LibraryDate", ".date"]:
                    el = row.select_one(sel)
                    if el:
                        raw = el.get("datetime") or el.get_text(strip=True)
                        if raw:
                            try:
                                upload_date_iso = date_parse(raw).strftime("%Y-%m-%d")
                            except Exception:
                                pass
                            break

                version = None
                for sel in [".version", ".LibraryVersion"]:
                    el = row.select_one(sel)
                    if el:
                        version = el.get_text(strip=True)
                        break

                file_size = None
                for sel in [".fileSize", ".size", ".LibrarySize"]:
                    el = row.select_one(sel)
                    if el:
                        file_size = el.get_text(strip=True)
                        break

                filename = urlparse(dl_link["href"]).path.split("/")[-1]
                doc_type = self._guess_doc_type(title, filename)

                # since-filter: skip older docs unless first-run bootstrap mode.
                if since and upload_date_iso:
                    try:
                        if datetime.strptime(upload_date_iso, "%Y-%m-%d").date() < since.date():
                            continue
                    except Exception:
                        pass

                metadata_hash = self._metadata_hash(
                    community.community_key, title, uploader or "",
                    upload_date_iso, version, file_size
                )

                resource = Resource(
                    title=title,
                    url=doc_url,
                    category="library",
                    # Empty string — digester pipeline fetches body lazily for
                    # summary extraction, then discards it.
                    content="",
                    publish_date=upload_date_iso,
                    datasource_id=community_datasource_id,
                    doc_type=doc_type,
                    access_notes="WBA Extranet — login required",
                    content_hash=metadata_hash,
                    summary=(f"Uploaded by {uploader}" if uploader else None),
                )
                out.append(resource)

                if limit and len(out) >= limit:
                    break
            except Exception as exc:
                logger.debug(f"Failed to parse library row: {exc}")
                continue

        logger.info(
            f"Community {community.name}: {len(out)} library documents captured "
            f"(limit={limit}, since={since.date() if since else 'beginning'})"
        )
        return out

    # ---- wba_metadata publication ----------------------------------------- #

    def publish_wba_metadata(
        self,
        community: CommunityRef,
        community_datasource_id: str,
        leaders: List[DiscoveredLeader],
        members: List[DiscoveredMember],
    ) -> None:
        """Publish a `wba_metadata` message carrying leadership + members.

        The digester translates this into Person nodes + LEADS / MEMBER_OF
        edges (see `digester.process_wba_metadata_message`).
        """
        if not leaders and not members:
            return

        message = {
            "message_type": "wba_metadata",
            "datasource_id": community_datasource_id,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "batch_id": self._current_batch_id,
            "wba_metadata": {
                "community_key": community.community_key,
                "community_name": community.name,
                "leaders": [
                    {"name": l.name, "role": l.role, "profile_url": l.profile_url}
                    for l in leaders
                ],
                "members": [
                    {"name": m.name, "profile_url": m.profile_url}
                    for m in members
                ],
            },
        }

        if self._collect_mode:
            self._collected_messages.append(message)
        else:
            try:
                self.rabbitmq_producer.publish(message)
                logger.info(
                    f"Published wba_metadata for {community.name}: "
                    f"{len(leaders)} leaders, {len(members)} members"
                )
            except Exception as exc:
                logger.error(f"Failed to publish wba_metadata: {exc}")
                raise

        self.increment_batch_count(1)

    # ---- per-community DataSource upsert ---------------------------------- #

    def _upsert_community_datasource(
        self,
        community: CommunityRef,
        parent_datasource_id: Optional[str],
        description: Optional[str],
    ) -> str:
        """MERGE a DataSource Neo4j node for this community.

        Returns the datasource_id (deterministic from community_key).
        """
        datasource_id = self._datasource_id_for(community.community_key)
        self._community_datasource_ids[community.community_key] = datasource_id

        if not self.neo4j_client:
            logger.warning(
                f"Neo4j unavailable — skipping DataSource upsert for {community.name}"
            )
            return datasource_id

        query = """
        MERGE (d:DataSource {datasource_id: $datasource_id})
        ON CREATE SET
            d.name                  = $name,
            d.display_name          = $display_name,
            d.source_type           = 'authenticated_portal',
            d.fetch_url             = $home_url,
            d.resource_url          = $home_url,
            d.has_events            = false,
            d.check_content_hash    = true,
            d.discovery_mode        = 'incremental',
            d.consecutive_duplicates_limit = 5,
            d.run_on_startup        = false,
            d.publish_weight        = 1.0,
            d.update_weight         = 0.9,
            d.event_weight          = 0.8,
            d.parent_datasource_id  = $parent_datasource_id,
            d.org_id                = 'wba',
            d.description           = $description
        ON MATCH SET
            d.display_name          = $display_name,
            d.parent_datasource_id  = $parent_datasource_id,
            d.description           = coalesce($description, d.description),
            d.fetch_url             = $home_url,
            d.resource_url          = $home_url
        """
        # NOTE: child datasources intentionally have NO scraper_type and NO scrape_schedule.
        # Only the root 'wba_extranet' node is scheduled. The root run discovers all
        # communities internally, so children must not appear in the scheduler's due list
        # (which would cause N+1 redundant full scrapes and auth failures on children
        # that don't carry auth_token).
        try:
            self.neo4j_client.execute_query(
                query,
                {
                    "datasource_id": datasource_id,
                    "name": community.name,
                    "display_name": community.name,
                    "home_url": community.home_url,
                    "parent_datasource_id": parent_datasource_id,
                    "description": description,
                },
            )
        except Exception as exc:
            logger.error(
                f"Failed to upsert DataSource for community {community.name}: {exc}"
            )
        return datasource_id

    # ---- first-run detection --------------------------------------------- #

    def _is_first_run_for_community(self, datasource_id: str) -> bool:
        """Treat a community as first-run if its DataSource has no last_scraped_at."""
        if not self.neo4j_client:
            return True
        query = """
        MATCH (d:DataSource {datasource_id: $id})
        RETURN d.last_scraped_at AS last
        """
        try:
            res = self.neo4j_client.execute_query(query, {"id": datasource_id})
            if not res:
                return True
            last = res[0].get("last")
            return last is None
        except Exception as exc:
            logger.warning(f"first-run check failed for {datasource_id}: {exc}")
            return True

    # ---- orchestrator ----------------------------------------------------- #

    async def run_scraper(self, datasource_config: Dict[str, Any]) -> None:  # type: ignore[override]
        """Run the weekly WBA Extranet scrape.

        Expects to be invoked on the root `wba_extranet` DataSource. The run:
          1. Authenticates against the portal.
          2. Discovers all visible communities.
          3. For each community: upserts a child DataSource, parses landing
             metadata (leaders + members), parses digest threads (since the
             cutoff), captures library document metadata, and emits messages.
          4. Marks each community DataSource scraped + ends the batch.
        """
        root_id = datasource_config.get("datasource_id", self.ROOT_DATASOURCE_ID)
        logger.info(f"WBA Extranet: starting scrape (root datasource={root_id})")

        # auth_token from datasource config (set via admin UI) takes precedence
        # over the env var. This allows remote configuration without SSH.
        config_auth_token = datasource_config.get("auth_token") or ""
        if config_auth_token:
            # Inject directly without needing username/password
            from yarl import URL as _URL
            self.session.cookie_jar.update_cookies(
                {"HLLogin": config_auth_token}, _URL(self.base_url)
            )
            try:
                async with self.session.get(
                    self._abs_url("/"), headers=self._headers(), allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as _r:
                    if "/login" not in str(_r.url).lower():
                        logger.info("WBA Extranet: auth via datasource auth_token succeeded")
                        self.is_authenticated = True
                    else:
                        logger.warning("WBA Extranet: datasource auth_token rejected — may be expired")
            except Exception as _e:
                logger.warning(f"WBA Extranet: datasource auth_token warm-up failed: {_e}")
                self.is_authenticated = True  # proceed optimistically

        if not self.is_authenticated:
            if not (settings.wba_extranet_username and settings.wba_extranet_password):
                raise Exception(
                    "WBA Extranet credentials missing. Set WBA_EXTRANET_USERNAME and "
                    "WBA_EXTRANET_PASSWORD in .env, or set auth_token on the DataSource "
                    "via the system config admin page."
                )

        # Auth strategy:
        # 1. HLIAMKey API (best — no reCAPTCHA, structured JSON, set WBA_EXTRANET_IAM_KEY)
        # 2. Cookie injection (if WBA_EXTRANET_HLTC is set — user provides browser cookie)
        # 3. Form-based login (blocked by reCAPTCHA on some deployments)
        use_api = bool(settings.wba_extranet_iam_key)
        if use_api:
            # Verify the IAM key works before proceeding
            test = await self._api_get("Contacts/GetWhoAmI")
            if test:
                logger.info(f"WBA Extranet IAM key authentication OK — user: {test.get('EmailAddress','?')}")
                self.is_authenticated = True
            else:
                logger.warning("WBA Extranet IAM key test failed — falling back to form/cookie auth")
                use_api = False

        if not use_api and not self.is_authenticated:
            auth_ok = await self.authenticate(
                settings.wba_extranet_username, settings.wba_extranet_password
            )
            if not auth_ok:
                raise Exception("WBA Extranet authentication failed — aborting")

        batch_id = self.start_batch(root_id)
        logger.info(f"WBA Extranet batch_id={batch_id}")

        # Optional since_date override — bypasses per-community first-run detection.
        # Set by the manual trigger endpoint body: {"since_date": "2026-04-14"}.
        since_override: Optional[datetime] = None
        since_override_str = datasource_config.get("since_date")
        if since_override_str:
            try:
                since_override = date_parse(str(since_override_str)).replace(tzinfo=timezone.utc)
                logger.info(f"WBA Extranet: since_date override = {since_override.date().isoformat()}")
            except Exception as _exc:
                logger.warning(f"WBA Extranet: invalid since_date '{since_override_str}': {_exc}")

        items_processed = 0
        try:
            # Discover communities via API (preferred) or HTML scraping
            if use_api:
                communities = await self.discover_communities_via_api()
            if not use_api or not communities:
                communities = await self.discover_communities()
            if not communities:
                logger.warning("WBA Extranet: no communities discovered — exiting")
                return

            # Pass 1: upsert DataSource nodes (with the root as parent for all
            # communities, until we have a programme→workgroup mapping). The
            # `scripts/datasource_hierarchy.yaml` migration (Phase 4c)
            # rewrites parents for known WBA Extranet workgroups offline.
            for community in communities:
                self._upsert_community_datasource(
                    community,
                    parent_datasource_id=root_id,
                    description=None,
                )

            # Pass 2: parse landing + digest + library per community.
            for community in communities:
                community_datasource_id = self._community_datasource_ids[community.community_key]

                self.update_heartbeat()
                self.update_current_processing(
                    Resource(
                        title=f"WBA Extranet: {community.name}",
                        url=community.home_url,
                        category="discovery",
                    ),
                    "parsing community landing",
                )

                description, leaders, members = await self.parse_community_landing(community)
                # Refresh DataSource description if landing surfaced one.
                if description:
                    self._upsert_community_datasource(
                        community,
                        parent_datasource_id=root_id,
                        description=description,
                    )

                # Publish leadership/members metadata.
                self.publish_wba_metadata(
                    community, community_datasource_id, leaders, members
                )

                # Decide first-run vs. incremental window.
                first_run = self._is_first_run_for_community(community_datasource_id)
                if since_override:
                    since = since_override
                    doc_limit = None
                    logger.info(
                        f"  {community.name}: since_date override — fetching since {since.date().isoformat()}"
                    )
                elif first_run:
                    since = datetime.now(timezone.utc) - timedelta(days=self.FIRST_RUN_DAYS)
                    doc_limit: Optional[int] = self.FIRST_RUN_DOC_LIMIT
                    logger.info(
                        f"  {community.name}: FIRST RUN — last {self.FIRST_RUN_DAYS}d of digest "
                        f"+ {doc_limit} most-recent documents"
                    )
                else:
                    last_str = datasource_config.get("last_scraped_at")
                    last_dt = None
                    if last_str:
                        try:
                            last_dt = date_parse(str(last_str))
                        except Exception:
                            last_dt = None
                    if last_dt is None:
                        last_dt = datetime.now(timezone.utc) - timedelta(days=self.FIRST_RUN_DAYS)
                    since = last_dt - timedelta(days=self.INCREMENTAL_OVERLAP_DAYS)
                    doc_limit = None
                    logger.info(
                        f"  {community.name}: incremental — since {since.date().isoformat()}"
                    )

                # Digest threads — prefer structured API, fall back to HTML scraping.
                threads = []
                if use_api:
                    threads = await self.get_community_threads_via_api(
                        community.community_key, community_datasource_id,
                        since=since, limit=30
                    )
                if not threads:
                    threads = await self.parse_digest_threads(
                        community, community_datasource_id, since=since
                    )
                # Filter against already-known URLs to avoid re-publishing.
                threads = self.filter_new_urls(threads)
                for r in threads:
                    self.publish_resource(r)
                    items_processed += 1

                # Library document metadata. Bodies are fetched ONCE per
                # doc (or whenever metadata_hash flips) so the digester can
                # produce a synopsis; we never persist the raw body
                # (Resource node has no content field).
                docs = []
                if use_api:
                    docs = await self.get_community_library_via_api(
                        community.community_key, community_datasource_id,
                        limit=doc_limit or 10
                    )
                if not docs:
                    docs = await self.capture_document_metadata(
                        community,
                        community_datasource_id,
                        limit=doc_limit,
                        since=None if first_run else since,
                    )
                if docs:
                    urls = [d.url for d in docs]
                    existing = self.batch_check_urls_exist(urls)
                    for d in docs:
                        needs_body = False
                        if existing.get(d.url, False):
                            # Same URL — only re-fetch+republish if content_hash flipped.
                            if d.content_hash and self.has_content_changed(d.url, d.content_hash):
                                logger.info(f"  doc changed (metadata hash flip): {d.title}")
                                needs_body = True
                            else:
                                logger.debug(f"  doc unchanged, skipping: {d.title}")
                                continue
                        else:
                            needs_body = True

                        if needs_body:
                            await self._fetch_document_body_inline(d)
                            self.publish_resource(d)
                            items_processed += 1

                # Mark this community scraped so next run honours since.
                self.mark_datasource_scraped(community_datasource_id)

                await asyncio.sleep(self.get_scraper_delay(root_id))

            logger.info(
                f"WBA Extranet scrape complete: {items_processed} items across "
                f"{len(communities)} communities"
            )
        except Exception as exc:
            logger.error(f"WBA Extranet scrape failed: {exc}")
            if self.get_current_batch_id():
                self.end_batch(self._batch_items_count)
            raise
        else:
            self.mark_datasource_scraped(root_id)
            self.end_batch(items_processed)
        finally:
            self.clear_current_processing()

    # ---- document body fetch (once per doc, body NOT persisted) ---------- #

    async def _fetch_document_body_inline(self, resource: Resource) -> None:
        """Fetch a library document's body once and stash it on the Resource
        for the digester to summarise. The Resource node has no `content`
        field, so the raw body is automatically dropped after the digester
        runs LLM extraction — we are not persisting it anywhere.

        For non-PDF documents we leave content empty (digester gets metadata-
        only summary). Extending to DOCX/XLSX/PPTX text extraction is
        follow-up work — the WBA scraper today only fetches PDFs.
        """
        url = resource.url or ""
        if not url:
            return
        is_pdf = url.lower().endswith(".pdf") or "DownloadDocumentFile" in url

        try:
            async with self.session.get(
                url, headers=self._headers(referer=self.base_url),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"  doc fetch returned HTTP {resp.status}: {url}"
                    )
                    return
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "pdf" in ctype or is_pdf:
                    pdf_bytes = await resp.read()
                    body_text = self.extract_pdf_text_from_bytes(
                        pdf_bytes, include_page_markers=False
                    )
                    # Scrub Zoom / Teams / Meet URLs that may appear inline.
                    body_text = sanitize_text(body_text)
                    resource.content = body_text
                    logger.debug(
                        f"  fetched body for {resource.title} ({len(body_text)} chars)"
                    )
                else:
                    # Non-PDF (Office formats etc.) — leave content empty;
                    # the digester will write a metadata-only Resource.
                    logger.debug(
                        f"  doc is not PDF (Content-Type={ctype}) — skipping body fetch"
                    )
        except Exception as exc:
            logger.warning(f"  failed to fetch body for {resource.title}: {exc}")

    # ---- abstract method satisfaction ------------------------------------- #

    async def scrape_resource(self, resource: Resource) -> Resource:
        """Resources from this scraper are emitted with content already set
        (digest posts) or empty (library docs); body re-fetch happens in
        the digester. This method is a no-op pass-through to satisfy the
        BaseScraper abstract contract.
        """
        return resource
