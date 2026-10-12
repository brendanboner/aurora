"""
WFA Attendance Sheet Parser

Parses Wi-Fi Alliance Causeway attendance Excel files without LLM involvement.
These files are ~300KB cumulative spreadsheets that are too large for the LLM
and cause truncation errors when processed generically.

WFA attendance file structure:
  Sheet 1 (Attendance / Participants):
    - Columns: Name | Company/Affiliation | Email | [Mtg 1 date] | ... | [THIS MEETING]
    - The LAST date-like column = current meeting attendance
    - Cell values: P/Y/1 = present, R = remote, E = excused, A/blank = absent
    - The file is CUMULATIVE — every new file contains all prior meetings plus the new one

  Additional sheets (often "Votes", "Motions", "Ballot"):
    - Rows = individual motions
    - Columns: Motion text | Result | Yes% | No% | Abstain% | [Sponsor] | [Notes]
    - Identifies: what was voted on and how the group decided

Output:
  - Compact text summary suitable for Neo4j Resource.summary (~200–400 chars)
  - Structured data for Neo4j relationship creation (Person-ATTENDED-Event, VoteRecord)
"""

import io
import re
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Cell values that mean "attended this meeting"
PRESENT_VALUES = {"p", "y", "yes", "1", "x", "r", "remote", "present", "attendee"}
# Cell values that mean "excused / absent with notice"
EXCUSED_VALUES = {"e", "excused", "ea", "absent with notice"}
# Column header patterns for locating the name column
NAME_HEADERS = {"name", "full name", "first name", "participant", "member", "attendee"}
# Column header patterns for the company/affiliation column
COMPANY_HEADERS = {"company", "organization", "organisation", "affiliation", "employer", "member company"}
# Column header patterns for vote sheets
VOTE_MOTION_HEADERS = {"motion", "ballot", "proposal", "item", "description", "resolution"}
VOTE_RESULT_HEADERS = {"result", "outcome", "status", "decision", "passed", "failed"}
VOTE_YES_HEADERS = {"yes", "for", "approve", "in favor", "aye", "affirm"}
VOTE_NO_HEADERS = {"no", "against", "oppose", "nay", "reject"}
VOTE_ABSTAIN_HEADERS = {"abstain", "abstention", "abstained", "not voting"}

# Max rows to scan for the header row
MAX_HEADER_SCAN = 8


def _cell_str(val: Any) -> str:
    """Convert cell value to stripped string."""
    if val is None:
        return ""
    return str(val).strip()


def _is_date_like(header: str) -> bool:
    """Return True if the column header looks like a meeting date."""
    h = header.strip()
    # ISO date: 2026-05-21
    if re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", h):
        return True
    # US date: 05/21/2026 or 5-21-26
    if re.match(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", h):
        return True
    # Month Year: "May 2026", "May-21-2026"
    if re.match(r"[A-Za-z]{3,9}[- ]\d{1,2}[,- ]\d{4}", h):
        return True
    if re.match(r"[A-Za-z]{3,9}[- ]\d{4}", h):
        return True
    # Excel serial number (large integer like 46203)
    try:
        n = float(h)
        if 30000 < n < 100000:  # plausible Excel date serial
            return True
    except ValueError:
        pass
    return False


def _parse_excel_date(val: Any) -> Optional[str]:
    """Try to return an ISO date string from a cell value."""
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    # ISO
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # US: MM/DD/YYYY
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return None


def _find_col(headers: List[str], target_set: set) -> Optional[int]:
    """Find index of first header matching any keyword in target_set."""
    for i, h in enumerate(headers):
        if any(kw in h.lower() for kw in target_set):
            return i
    return None


def _is_attendance_sheet(sheet_name: str, headers: List[str]) -> bool:
    """Return True if this sheet looks like the main attendance list."""
    sn = sheet_name.lower()
    if any(kw in sn for kw in ("attendance", "participant", "member", "roster")):
        return True
    # Check if headers have name + date-like columns
    has_name = any(any(kw in h.lower() for kw in NAME_HEADERS) for h in headers)
    has_dates = sum(1 for h in headers if _is_date_like(h))
    return has_name and has_dates >= 2


def _is_vote_sheet(sheet_name: str, headers: List[str]) -> bool:
    """Return True if this sheet looks like a votes/motions sheet."""
    sn = sheet_name.lower()
    if any(kw in sn for kw in ("vote", "ballot", "motion", "resolution")):
        return True
    has_motion = any(any(kw in h.lower() for kw in VOTE_MOTION_HEADERS) for h in headers)
    has_result = any(any(kw in h.lower() for kw in VOTE_RESULT_HEADERS | VOTE_YES_HEADERS) for h in headers)
    return has_motion and has_result


def parse_wfa_attendance_xlsx(content: bytes, filename: str,
                               url: Optional[str] = None) -> Dict[str, Any]:
    """
    Parse a WFA Causeway attendance Excel file.

    Returns a dict with:
      summary     — compact human-readable summary (for Neo4j Resource.summary)
      text        — slightly longer text (for oracle search)
      attendees   — list of {name, company, attended, excused}
      companies   — set of unique company names
      votes       — list of {motion, result, yes_pct, no_pct, abstain_pct}
      meeting_date — ISO date of THIS meeting (from last date column)
      working_group — extracted from URL or filename
      total_count  — total unique people in file (all historical)
      this_meeting_count — people who attended THIS meeting
    """
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise ImportError("openpyxl is required: pip install openpyxl")

    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)

    attendees: List[Dict] = []
    companies: set = set()
    votes: List[Dict] = []
    meeting_date: Optional[str] = None
    working_group: Optional[str] = None

    # Extract working group from URL
    if url:
        m = re.search(r"/wg/([^/]+)", url)
        if m:
            working_group = m.group(1)

    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]

        # Find the header row (scan first MAX_HEADER_SCAN rows)
        header_row_idx = None
        headers: List[str] = []
        rows_scanned: List[List[Any]] = []

        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= MAX_HEADER_SCAN + 30:  # safety limit for sparse sheets
                break
            rows_scanned.append(list(row))
            cells = [_cell_str(c) for c in row]
            non_empty = [c for c in cells if c]
            if len(non_empty) >= 3:
                # Check if this row contains name/company-like headers
                if any(any(kw in c.lower() for kw in NAME_HEADERS | COMPANY_HEADERS) for c in cells):
                    header_row_idx = i
                    headers = cells
                    break
                # Or all date-like non-empty values (header of a vote sheet sometimes)
                if any(any(kw in c.lower() for kw in VOTE_MOTION_HEADERS | VOTE_RESULT_HEADERS) for c in cells):
                    header_row_idx = i
                    headers = cells
                    break

        if header_row_idx is None or not headers:
            continue  # sheet has no recognisable structure

        if _is_attendance_sheet(sheet_name, headers):
            _parse_attendance(sheet, headers, header_row_idx, rows_scanned,
                              attendees, companies)
            # Extract meeting date from last date-like column header
            date_cols = [i for i, h in enumerate(headers) if _is_date_like(h)]
            if date_cols:
                last_date_header = headers[date_cols[-1]]
                meeting_date = _parse_excel_date(last_date_header) or last_date_header

        elif _is_vote_sheet(sheet_name, headers):
            _parse_votes(sheet, headers, header_row_idx, votes)

    wb.close()

    # Compute this-meeting statistics
    this_meeting_attendees = [a for a in attendees if a.get("attended")]
    this_meeting_companies = {a["company"] for a in this_meeting_attendees if a.get("company")}

    # Generate summary
    summary = _build_summary(
        working_group=working_group,
        meeting_date=meeting_date,
        this_count=len(this_meeting_attendees),
        this_companies=this_meeting_companies,
        total_count=len(attendees),
        votes=votes,
    )

    # Generate longer text for oracle
    text = _build_text(
        summary=summary,
        this_attendees=this_meeting_attendees,
        votes=votes,
        meeting_date=meeting_date,
        working_group=working_group,
    )

    return {
        "summary": summary,
        "text": text,
        "attendees": attendees,
        "companies": companies,
        "votes": votes,
        "meeting_date": meeting_date,
        "working_group": working_group,
        "total_count": len(attendees),
        "this_meeting_count": len(this_meeting_attendees),
        "this_meeting_companies": this_meeting_companies,
    }


def _parse_attendance(sheet, headers: List[str], header_row_idx: int,
                      pre_rows: List[List[Any]],
                      attendees: List[Dict], companies: set) -> None:
    """Parse the main attendance sheet, populating attendees and companies."""
    name_col = _find_col(headers, NAME_HEADERS)
    company_col = _find_col(headers, COMPANY_HEADERS)

    # Find all date-like columns — last one = this meeting
    date_cols = [i for i, h in enumerate(headers) if _is_date_like(h)]
    last_meeting_col = date_cols[-1] if date_cols else None

    # Stream through rows after the header
    row_num = 0
    for row in sheet.iter_rows(values_only=True):
        if row_num <= header_row_idx:
            row_num += 1
            continue
        row_num += 1

        cells = [_cell_str(c) for c in row]
        if not any(cells):
            continue

        # Extract name
        name = cells[name_col].strip() if name_col is not None and name_col < len(cells) else ""
        if not name or name.lower() in ("none", "n/a", "name", "total"):
            continue

        # Extract company
        company = ""
        if company_col is not None and company_col < len(cells):
            company = cells[company_col].strip()
            if company and company.lower() not in ("none", "n/a", ""):
                companies.add(company)

        # Extract this-meeting attendance (last date column)
        attended = False
        excused = False
        if last_meeting_col is not None and last_meeting_col < len(cells):
            val = cells[last_meeting_col].lower().strip()
            if val in PRESENT_VALUES:
                attended = True
            elif val in EXCUSED_VALUES:
                excused = True

        attendees.append({
            "name": name,
            "company": company,
            "attended": attended,
            "excused": excused,
        })


def _parse_votes(sheet, headers: List[str], header_row_idx: int,
                 votes: List[Dict]) -> None:
    """Parse a vote/ballot sheet."""
    motion_col = _find_col(headers, VOTE_MOTION_HEADERS)
    result_col = _find_col(headers, VOTE_RESULT_HEADERS)
    yes_col = _find_col(headers, VOTE_YES_HEADERS)
    no_col = _find_col(headers, VOTE_NO_HEADERS)
    abstain_col = _find_col(headers, VOTE_ABSTAIN_HEADERS)

    if motion_col is None:
        return  # can't identify motions

    row_num = 0
    for row in sheet.iter_rows(values_only=True):
        if row_num <= header_row_idx:
            row_num += 1
            continue
        row_num += 1

        cells = [_cell_str(c) for c in row]
        if not any(cells):
            continue

        motion = cells[motion_col].strip() if motion_col < len(cells) else ""
        if not motion or len(motion) < 5:
            continue

        result = ""
        if result_col is not None and result_col < len(cells):
            result = cells[result_col].strip()

        def _pct(col):
            if col is None or col >= len(cells):
                return None
            val = cells[col].strip().rstrip("%")
            try:
                return round(float(val), 1)
            except ValueError:
                return None

        vote = {
            "motion": motion,
            "result": result,
            "yes_pct": _pct(yes_col),
            "no_pct": _pct(no_col),
            "abstain_pct": _pct(abstain_col),
        }
        # Infer result from percentages if not explicit
        if not vote["result"] and vote["yes_pct"] is not None:
            vote["result"] = "PASSED" if vote["yes_pct"] >= 50 else "FAILED"

        votes.append(vote)


def _build_summary(working_group: Optional[str], meeting_date: Optional[str],
                   this_count: int, this_companies: set,
                   total_count: int, votes: List[Dict]) -> str:
    """Build compact summary for Neo4j Resource.summary."""
    parts = []

    wg = working_group or "Wi-Fi Alliance workgroup"
    date_str = f" ({meeting_date})" if meeting_date else ""
    parts.append(f"{wg} meeting{date_str}: {this_count} attendees from {len(this_companies)} companies.")

    if this_companies:
        sample = sorted(this_companies)[:6]
        more = len(this_companies) - len(sample)
        co_list = ", ".join(sample)
        if more:
            co_list += f" (+{more} more)"
        parts.append(f"Companies: {co_list}.")

    if votes:
        passed = [v for v in votes if "PASS" in (v.get("result") or "").upper()]
        failed = [v for v in votes if "FAIL" in (v.get("result") or "").upper()]
        parts.append(f"{len(votes)} motion(s) voted: {len(passed)} passed, {len(failed)} failed.")

    return " ".join(parts)


def _build_text(summary: str, this_attendees: List[Dict], votes: List[Dict],
                meeting_date: Optional[str], working_group: Optional[str]) -> str:
    """Build full searchable text for oracle retrieval."""
    lines = [summary, ""]

    if this_attendees:
        lines.append(f"Attendees at this meeting ({len(this_attendees)}):")
        for a in sorted(this_attendees, key=lambda x: x.get("company", "")):
            co = f" ({a['company']})" if a.get("company") else ""
            lines.append(f"  • {a['name']}{co}")

    if votes:
        lines.append("")
        lines.append("Votes / Motions:")
        for v in votes:
            result = v.get("result", "")
            yes = f"{v['yes_pct']:.0f}% yes" if v.get("yes_pct") is not None else ""
            no = f"{v['no_pct']:.0f}% no" if v.get("no_pct") is not None else ""
            ab = f"{v['abstain_pct']:.0f}% abstain" if v.get("abstain_pct") is not None else ""
            stats = ", ".join(s for s in [yes, no, ab] if s)
            result_str = f" [{result}]" if result else ""
            stats_str = f" ({stats})" if stats else ""
            lines.append(f"  • {v['motion']}{result_str}{stats_str}")

    return "\n".join(lines)
