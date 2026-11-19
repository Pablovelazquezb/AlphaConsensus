"""Official House Clerk PTR ingestion (free historical STOCK Act data).

The House publishes an annual ZIP with an XML index of every financial
disclosure and the individual Periodic Transaction Reports as PDFs. Unlike the
3-month Bargo free tier, these filings go back years — enough to backtest
credibility today, at zero data cost.

Pipeline:
  1. download ``{year}FD.zip`` and read ``{year}FD.xml`` (index only, ~100 KB);
  2. filter ``FilingType == "P"`` (periodic transaction reports) by member;
  3. download ``ptr-pdfs/{year}/{doc_id}.pdf``;
  4. extract text with ``pdftotext -layout`` (fallback: pypdf);
  5. parse the tabular rows into ``CongressTrade`` records.

Known limitations: some filings are scanned images (no text layer), amounts
are ranges, and amended filings can duplicate trades (deduplicated here).
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET

from .congress import CongressTrade

BASE = "https://disclosures-clerk.house.gov/public_disc"
INDEX_URL = BASE + "/financial-pdfs/{year}FD.zip"
PDF_URL = BASE + "/ptr-pdfs/{year}/{doc_id}.pdf"
USER_AGENT = "Mozilla/5.0 (AlphaConsensus research; contact: local)"

DEFAULT_MEMBERS = (
    "Gilbert Cisneros",
    "Kevin Hern",
    "Rohit Khanna",
    "Maria Elvira Salazar",
    "David Taylor",
    "April McClain Delaney",
    "Pete Sessions",
    "Michael McCaul",
    "Jonathan Jackson",
    "Thomas Kean",
    "Josh Gottheimer",
    "French Hill",
    "Nancy Pelosi",
    "John Boozman",
    "Richard Blumenthal",
)

DATE_PAIR = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})")
TYPE_AT_END = re.compile(r"\b(S\s*\(partial\)|P|S|E)\s*$")
TICKER = re.compile(r"\(([A-Z]{1,6})\)")
AMOUNT = re.compile(r"\$([\d,]+)(?:\s*-\s*\$?([\d,]+))?")
OWNER = re.compile(r"^(SP|JT|DC|JTWROS|TTE|TR|IRA|HSA|ESOP)\s+")
ASSET_TYPE = re.compile(r"\[([A-Z]{2})\]")
VALID_TICKERS_BLACKLIST = {"ADR", "ETF", "REIT", "LP", "LLC", "INC", "CS", "OP"}


@dataclass(frozen=True)
class Filing:
    member: str
    first: str
    last: str
    state: str
    year: int
    doc_id: str
    filing_date: date

    @property
    def slug(self) -> str:
        return slugify(self.member)


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return cleaned.strip("-")


def _matches_member(full_name: str, queries: Sequence[str]) -> bool:
    """Token match so "David Taylor" also finds "David J. Taylor"."""
    tokens = set(re.findall(r"[a-z]+", full_name.lower()))
    for query in queries:
        wanted = re.findall(r"[a-z]+", query.lower())
        if wanted and all(token in tokens for token in wanted):
            return True
    return False


def _parse_us_date(value: str) -> Optional[date]:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


class HouseClerkSource:
    name = "house_clerk"

    def __init__(self, cache_dir: Optional[Path] = None, timeout: int = 60) -> None:
        self.cache_dir = Path(cache_dir or "data/raw")
        self.timeout = timeout
        self.index_dir = self.cache_dir / "index"
        self.pdf_dir = self.cache_dir / "pdfs"
        self.stats: Dict[str, int] = {
            "filings": 0,
            "pdfs_downloaded": 0,
            "pdfs_cached": 0,
            "pdfs_empty": 0,
            "rows_parsed": 0,
            "rows_without_ticker": 0,
        }

    # -- index -----------------------------------------------------------
    def _download(self, url: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    path.write_bytes(response.read())
                return
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise RuntimeError(f"No se pudo descargar {url}: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))

    def _index_path(self, year: int) -> Path:
        path = self.index_dir / f"{year}FD.zip"
        if not path.exists():
            self._download(INDEX_URL.format(year=year), path)
        return path

    def filings(
        self,
        members: Optional[Sequence[str]] = None,
        years: Sequence[int] = (2024, 2025, 2026),
    ) -> List[Filing]:
        queries = list(members or DEFAULT_MEMBERS)
        out: List[Filing] = []
        for year in years:
            path = self._index_path(year)
            with zipfile.ZipFile(path) as archive:
                root = ET.fromstring(archive.read(f"{year}FD.xml").decode("utf-8", "replace"))
            for member in root.findall("Member"):
                if (member.findtext("FilingType") or "").strip() != "P":
                    continue
                first = (member.findtext("First") or "").strip()
                last = (member.findtext("Last") or "").strip()
                full = f"{first} {last}".strip()
                if queries and not _matches_member(full, queries):
                    continue
                filing_date = _parse_us_date(member.findtext("FilingDate") or "")
                doc_id = (member.findtext("DocID") or "").strip()
                if filing_date is None or not doc_id:
                    continue
                out.append(
                    Filing(
                        member=full,
                        first=first,
                        last=last,
                        state=(member.findtext("StateDst") or "").strip(),
                        year=year,
                        doc_id=doc_id,
                        filing_date=filing_date,
                    )
                )
        self.stats["filings"] = len(out)
        return out

    # -- documents -------------------------------------------------------
    def fetch_pdf(self, filing: Filing) -> Path:
        path = self.pdf_dir / f"{filing.year}_{filing.doc_id}.pdf"
        if path.exists():
            self.stats["pdfs_cached"] += 1
            return path
        self._download(PDF_URL.format(year=filing.year, doc_id=filing.doc_id), path)
        self.stats["pdfs_downloaded"] += 1
        return path

    @staticmethod
    def extract_text(path: Path) -> str:
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        try:  # fallback when poppler is not installed
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""

    # -- parsing ---------------------------------------------------------
    def parse_ptr(self, text: str, filing: Filing) -> List[CongressTrade]:
        lines = text.splitlines()
        trades: List[CongressTrade] = []
        for i, line in enumerate(lines):
            match = None
            type_match = None
            for candidate in DATE_PAIR.finditer(line):
                left = line[: candidate.start()].rstrip()
                found = TYPE_AT_END.search(left)
                if found:
                    match, type_match = candidate, found
                    break
            if match is None or type_match is None:
                continue

            left = line[: match.start()].rstrip()
            asset_part = left[: type_match.start()].strip()
            owner = OWNER.match(asset_part)
            if owner:
                asset_part = asset_part[owner.end():].strip()

            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            combined = f"{asset_part} {next_line}"

            if "[OP]" in combined or "[CS]" in combined:
                continue
            bracket = ASSET_TYPE.search(combined)
            if bracket and bracket.group(1) != "ST":
                continue

            ticker_match = TICKER.search(asset_part) or TICKER.search(next_line)
            if ticker_match is None:
                self.stats["rows_without_ticker"] += 1
                continue
            ticker = ticker_match.group(1)
            if ticker in VALID_TICKERS_BLACKLIST:
                continue

            tail = line[match.end():].strip()
            amount_match = AMOUNT.search(f"{tail} {next_line}")
            low = high = None
            if amount_match:
                low = float(amount_match.group(1).replace(",", ""))
                high = float((amount_match.group(2) or amount_match.group(1)).replace(",", ""))
                if amount_match.group(2) is None and tail.rstrip().endswith("-"):
                    # Ranges wrap: "$15,001 -" on the row, "$50,000" below it.
                    following = " ".join(lines[i + 1: i + 3])
                    wrapped = re.search(r"\$([\d,]+)", following)
                    if wrapped:
                        high = float(wrapped.group(1).replace(",", ""))

            transaction_date = _parse_us_date(match.group(1))
            if transaction_date is None:
                continue

            kind = "purchase" if type_match.group(1) == "P" else (
                "exchange" if type_match.group(1) == "E" else "sale"
            )
            amount_range = (
                f"${low:,.0f} - ${high:,.0f}" if low is not None and high is not None else ""
            )
            asset = re.sub(r"\s+", " ", asset_part).strip()
            trades.append(
                CongressTrade(
                    member=filing.member,
                    member_slug=filing.slug,
                    chamber="house",
                    state=filing.state,
                    ticker=ticker,
                    asset=asset,
                    type=kind,
                    amount_low=low,
                    amount_high=high,
                    amount_range=amount_range,
                    transaction_date=transaction_date,
                    disclosure_date=filing.filing_date,
                    est_price=None,
                    recent_price=None,
                    perf_pct=None,
                    outcome="",
                )
            )
        self.stats["rows_parsed"] += len(trades)
        return trades

    # -- orchestration ---------------------------------------------------
    def sync(
        self,
        filings: Sequence[Filing],
        progress: Optional[Callable[[int, int, Filing, int], None]] = None,
    ) -> List[CongressTrade]:
        collected: List[CongressTrade] = []
        for index, filing in enumerate(filings, start=1):
            try:
                path = self.fetch_pdf(filing)
                text = self.extract_text(path)
            except Exception:
                self.stats["pdfs_empty"] += 1
                continue
            if not text.strip():
                self.stats["pdfs_empty"] += 1
                if progress:
                    progress(index, len(filings), filing, 0)
                continue
            rows = self.parse_ptr(text, filing)
            collected.extend(rows)
            if progress:
                progress(index, len(filings), filing, len(rows))
            time.sleep(0.15)

        deduped: Dict[Tuple, CongressTrade] = {}
        for trade in collected:
            key = (
                trade.member_slug, trade.ticker, trade.transaction_date,
                trade.type, trade.amount_low, trade.amount_high,
            )
            deduped.setdefault(key, trade)
        return sorted(deduped.values(), key=lambda t: t.transaction_date or date.min)


def save_trades(trades: Iterable[CongressTrade], path: Path) -> Path:
    """Persist parsed trades as JSON (dates as ISO strings)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for trade in trades:
        rows.append(
            {
                "member": trade.member,
                "member_slug": trade.member_slug,
                "chamber": trade.chamber,
                "state": trade.state,
                "ticker": trade.ticker,
                "asset": trade.asset,
                "type": trade.type,
                "amount_low": trade.amount_low,
                "amount_high": trade.amount_high,
                "amount_range": trade.amount_range,
                "transaction_date": trade.transaction_date.isoformat() if trade.transaction_date else None,
                "disclosure_date": trade.disclosure_date.isoformat() if trade.disclosure_date else None,
                "lag_days": trade.lag_days,
            }
        )
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
