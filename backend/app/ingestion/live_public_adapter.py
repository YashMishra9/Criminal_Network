"""Public/Live RSS Feed Adapter — DOC3 §3, DOC2 §6.3, B3.

Task B3: poll() against a public/open RSS feed, with cursor handling and
silent-failure behavior, tagged dataset='live_public'.

Key contract rules this adapter enforces (DOC3 §3 + DOC2 §6.3):

1. poll() MUST catch ALL network/parsing errors internally and return
   PollResult(records=[], next_cursor=<unchanged>) — it must NEVER raise.

2. Update AdapterDescriptor.last_run_status / last_error on EVERY call
   (success or failure) so the ingestion status endpoint can report state
   without the adapter throwing across the boundary.

3. Cursor ownership: the cursor is an opaque string owned by this adapter
   (here: an ISO-8601 timestamp). The Ingestion Orchestrator persists it and
   passes it back unchanged on the next call. No other component parses it.

4. Only public/open, ToS-compliant sources concerning organizations and
   public figures — never private individuals (DOC1 NFR6).

5. This adapter must NEVER become a hard dependency of the core demo
   (Contract Invariant 7). It is enabled only when
   LIVE_ADAPTER_ENABLED=true AND AdapterDescriptor.enabled=true.

6. No new infrastructure: uses Python stdlib only (urllib.request,
   xml.etree.ElementTree). No message queue, no worker process.
"""

import hashlib
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.error import URLError

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.ingestion.adapter_base import PollResult, SourceAdapter

logger = logging.getLogger(__name__)

_ADAPTER_ID = "rss_public_v1"
_DATASET = "live_public"
_SOURCE_TYPE = "rss"
_DEFAULT_TIMEOUT_SECONDS = 10


class LivePublicAdapter(SourceAdapter):
    """Poll-mode source adapter for a public/open RSS feed.

    Implements the SourceAdapter interface (B1) for the live_public dataset.
    Uses a public RSS endpoint configured via feed_url; no API key required.

    This adapter is OPTIONAL and NON-BLOCKING (DOC1 FR3, DOC2 §6.3,
    Contract Invariant 7):
    - poll() never raises — all errors are caught and logged internally.
    - The system runs correctly with this adapter disabled or unreachable.

    Cursor semantics:
        The cursor is an ISO-8601 timestamp string. Records published AFTER
        the cursor are returned. On the first call (cursor=None) all available
        items in the feed are returned. next_cursor is always set to the
        publication time of the newest item returned, or to the current time
        if no items were returned (so future calls don't re-process old items).
    """

    def __init__(
        self,
        feed_url: str,
        poll_interval_seconds: float = 300.0,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialise the adapter.

        Args:
            feed_url:               URL of the public RSS feed to poll.
            poll_interval_seconds:  How frequently the orchestrator calls poll()
                                    (informational; stored in descriptor only).
            timeout:                HTTP request timeout in seconds.
        """
        self._feed_url = feed_url
        self._poll_interval_seconds = poll_interval_seconds
        self._timeout = timeout

        self._last_run_at: Optional[str] = None
        self._last_run_status: str = "never_run"
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # SourceAdapter interface
    # ------------------------------------------------------------------

    def descriptor(self) -> AdapterDescriptor:
        """Return the static AdapterDescriptor for this adapter.

        Always succeeds — no I/O performed.
        """
        return AdapterDescriptor(
            adapter_id=_ADAPTER_ID,
            source_type=_SOURCE_TYPE,
            dataset=_DATASET,
            mode="poll",
            enabled=True,
            poll_interval_seconds=self._poll_interval_seconds,
            last_run_at=self._last_run_at,
            last_run_status=self._last_run_status,  # type: ignore[arg-type]
            last_error=self._last_error,
        )

    def fetch_batch(self) -> list[RawRecord]:
        """Not supported — this adapter is poll-only.

        Raises:
            NotImplementedError: always.
        """
        raise NotImplementedError(
            "LivePublicAdapter is poll-only (mode='poll'). "
            "Use poll(cursor) instead of fetch_batch()."
        )

    def poll(self, cursor: Optional[str]) -> PollResult:
        """Return RSS items published after cursor.

        DOC3 §3 / DOC2 §6.3 guarantee: this method NEVER raises. All network
        and parsing errors are caught, logged, and returned as an empty result
        with the cursor unchanged.

        Args:
            cursor: ISO-8601 timestamp of the last known item, or None for the
                    first call (return all available items).

        Returns:
            PollResult with new records and next_cursor. On any error,
            records=[] and next_cursor=cursor (unchanged, so the orchestrator
            can retry on the next scheduled interval).
        """
        call_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Safe fallback: if anything goes wrong, return this
        empty_result = PollResult(records=[], next_cursor=cursor or call_time)

        try:
            records, next_cursor = self._fetch_and_parse(cursor, call_time)
            self._last_run_at = call_time
            self._last_run_status = "ok"
            self._last_error = None
            logger.info(
                "LivePublicAdapter.poll() fetched %d new record(s) from %s",
                len(records),
                self._feed_url,
            )
            return PollResult(records=records, next_cursor=next_cursor)

        except Exception as exc:  # noqa: BLE001 — intentional broad catch (DOC3 §3)
            msg = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "LivePublicAdapter.poll() failed (returning empty result): %s", msg
            )
            self._last_run_at = call_time
            self._last_run_status = "error"
            self._last_error = msg
            # Return empty result, cursor unchanged — DOC3 §3 silent-failure rule
            return empty_result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_and_parse(
        self,
        cursor: Optional[str],
        ingested_at: str,
    ) -> tuple[list[RawRecord], str]:
        """Fetch the RSS feed and parse items newer than cursor.

        Args:
            cursor:      ISO-8601 cursor from the last poll, or None.
            ingested_at: ISO-8601 timestamp of this poll call.

        Returns:
            (records, next_cursor) where next_cursor is the pub-date of the
            newest item, or ingested_at if no new items were found.

        Raises:
            URLError:         on network failure.
            ET.ParseError:    on malformed XML.
            Exception:        any other unexpected error.
        """
        cursor_dt: Optional[datetime] = None
        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("Could not parse cursor '%s'; treating as None.", cursor)

        xml_bytes = self._http_get(self._feed_url)
        root = ET.fromstring(xml_bytes)

        # Locate RSS <channel><item> elements (handle RSS 2.0 and Atom namespaces)
        channel = root.find("channel")
        if channel is not None:
            items = channel.findall("item")
        else:
            # Atom feed fallback: <entry> elements
            atom_ns = "{http://www.w3.org/2005/Atom}"
            items = root.findall(f"{atom_ns}entry")

        records: list[RawRecord] = []
        newest_dt: Optional[datetime] = cursor_dt

        for item in items:
            pub_dt, record = self._parse_item(item, ingested_at)
            if record is None:
                continue

            if cursor_dt is not None and pub_dt is not None and pub_dt <= cursor_dt:
                # Already seen in a previous poll — skip
                continue

            records.append(record)
            if pub_dt is not None:
                if newest_dt is None or pub_dt > newest_dt:
                    newest_dt = pub_dt

        next_cursor = (
            newest_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            if newest_dt is not None
            else ingested_at
        )
        return records, next_cursor

    def _http_get(self, url: str) -> bytes:
        """Perform a simple HTTP GET with a timeout.

        Uses stdlib urllib — no external dependencies (B3 §17, Contract Invariant 7).
        """
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "CriminalNetworkAnalysis/1.0 (+synthetic-demo)"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as response:
            return response.read()

    def _parse_item(
        self,
        item: ET.Element,
        ingested_at: str,
    ) -> tuple[Optional[datetime], Optional[RawRecord]]:
        """Parse one RSS <item> or Atom <entry> into a RawRecord.

        Args:
            item:        The XML element.
            ingested_at: ISO-8601 timestamp for the ingested_at field.

        Returns:
            (pub_dt, record) where pub_dt may be None if no pub date was found,
            and record may be None if the item has no usable content.
        """
        atom_ns = "{http://www.w3.org/2005/Atom}"

        # Explicit is-not-None checks required: XML elements with no children
        # evaluate as falsy in Python 3.14+, breaking 'or' chaining.
        def _first(*tags: str) -> Optional[ET.Element]:
            for tag in tags:
                el = item.find(tag)
                if el is not None:
                    return el
            return None

        title_el = _first("title", f"{atom_ns}title")
        link_el = _first("link", f"{atom_ns}link")
        desc_el = _first("description", "summary", f"{atom_ns}summary")
        pubdate_el = _first(
            "pubDate", "published", f"{atom_ns}published",
            "updated", f"{atom_ns}updated",
        )

        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        # Atom <link> may use href attribute instead of text
        if not link and link_el is not None:
            link = link_el.get("href", "").strip()
        description = (desc_el.text or "").strip() if desc_el is not None else ""

        if not title and not link:
            # Not enough content to produce a meaningful record
            return None, None

        # Parse publication date
        pub_dt: Optional[datetime] = None
        occurred_at: Optional[str] = None
        if pubdate_el is not None and pubdate_el.text:
            raw_date = pubdate_el.text.strip()
            try:
                # RFC-2822 (RSS 2.0): "Mon, 01 Jan 2024 12:00:00 GMT"
                pub_dt = parsedate_to_datetime(raw_date)
                occurred_at = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                try:
                    # ISO-8601 (Atom): "2024-01-01T12:00:00Z"
                    pub_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    occurred_at = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    logger.debug("Could not parse pubDate '%s', occurred_at will be null.", raw_date)

        # Build a stable record_id from the link (or title if no link)
        id_source = link or title
        record_id = f"rss_{hashlib.sha256(id_source.encode()).hexdigest()[:16]}"

        payload = {
            "title": title,
            "link": link,
            "description": description,
            "pub_date_raw": pubdate_el.text.strip() if pubdate_el is not None and pubdate_el.text else None,
            "feed_url": self._feed_url,
        }
        payload_text = f"{title}. {description}".strip().rstrip(".")

        record = RawRecord(
            record_id=record_id,
            dataset=_DATASET,
            source_type=_SOURCE_TYPE,
            source_adapter_id=_ADAPTER_ID,
            occurred_at=occurred_at,
            ingested_at=ingested_at,
            payload=payload,
            payload_text=payload_text or None,
        )
        return pub_dt, record
