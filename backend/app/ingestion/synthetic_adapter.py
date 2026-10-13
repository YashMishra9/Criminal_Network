"""Synthetic Data Adapter — DOC3 §3, B2.

Task B2: Implements SyntheticAdapter.fetch_batch() which reads the bundled
synthetic dataset (H1's output under data/synthetic/) into valid RawRecord
objects tagged dataset='synthetic_demo'.

This is the guaranteed demo path (DOC1 NFR3, Contract Invariant 7):
- Requires NO network access.
- Is fully offline-capable.
- Is idempotent: calling fetch_batch() twice yields the same record_id set
  as long as the underlying files have not changed (DOC3 §3).

Folder → source_type mapping (DOC3 §2.2):
  fir/           → "FIR"
  police_report/ → "police_report"
  cdr/           → "CDR"
  transactions/  → "transaction"
  vehicles/      → "vehicle_registry"
  surveillance/  → "surveillance"
  social_media/  → "social_media"

Each folder may contain:
  - Individual .json files (one record per file), OR
  - A single records.json with a JSON array of records.
Both formats are supported transparently.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.contracts.raw_record import AdapterDescriptor, RawRecord
from app.ingestion.adapter_base import PollResult, SourceAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADAPTER_ID = "synthetic_v1"
_DATASET = "synthetic_demo"

# Maps subdirectory name → DOC3 §2.2 source_type value.
# Only directories listed here are ingested; unknown directories are skipped.
_SOURCE_TYPE_MAP: dict[str, str] = {
    "fir": "FIR",
    "police_report": "police_report",
    "cdr": "CDR",
    "transactions": "transaction",
    "vehicles": "vehicle_registry",
    "surveillance": "surveillance",
    "social_media": "social_media",
}


def _default_base_path() -> Path:
    """Resolve <repo_root>/data/synthetic relative to this module's location.

    This file lives at backend/app/ingestion/synthetic_adapter.py.
    Repo root is 4 levels up (ingestion → app → backend → repo_root).
    """
    return Path(__file__).resolve().parents[3] / "data" / "synthetic"


# ---------------------------------------------------------------------------
# SyntheticAdapter
# ---------------------------------------------------------------------------

class SyntheticAdapter(SourceAdapter):
    """Batch-mode source adapter for the bundled synthetic demo dataset.

    Implements the SourceAdapter interface (B1) for the synthetic_demo dataset.
    All three abstract methods are implemented:

    descriptor()    — returns static metadata; always succeeds.
    fetch_batch()   — reads all H1 files and returns RawRecord[]; idempotent.
    poll()          — raises NotImplementedError (batch-only adapter).
    """

    def __init__(self, base_path: Optional[Path] = None) -> None:
        """Initialise the adapter.

        Args:
            base_path: Path to the data/synthetic/ directory. Defaults to
                       <repo_root>/data/synthetic/ resolved relative to this
                       module's location. Provide an explicit path in tests.
        """
        self._base_path: Path = Path(base_path) if base_path is not None else _default_base_path()
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
            source_type="synthetic_multi",  # covers multiple source types per folder
            dataset=_DATASET,
            mode="batch",
            enabled=True,
            poll_interval_seconds=None,
            last_run_at=self._last_run_at,
            last_run_status=self._last_run_status,  # type: ignore[arg-type]
            last_error=self._last_error,
        )

    def fetch_batch(self) -> List[RawRecord]:
        """Return all available records from the synthetic dataset.

        Idempotency (DOC3 §3): calling this method again with unchanged files
        produces the same record_id set. record_ids are assigned by H1's
        dataset files and never modified here.

        Error behavior (DOC3 §3): a broken or missing synthetic dataset is a
        build-blocking defect, not a runtime-degradation case. This method
        logs clearly and raises rather than returning a partial/empty list
        silently.

        Returns:
            List of RawRecord objects for every record in data/synthetic/.

        Raises:
            FileNotFoundError: if the base_path directory does not exist.
            ValueError: if a record file is missing a required field.
            json.JSONDecodeError: if a record file contains malformed JSON.
        """
        ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if not self._base_path.is_dir():
            msg = (
                f"Synthetic dataset base path does not exist: {self._base_path}. "
                "H1 must be completed before B2 can ingest."
            )
            logger.error(msg)
            self._last_run_status = "error"
            self._last_error = msg
            self._last_run_at = ingested_at
            raise FileNotFoundError(msg)

        records: List[RawRecord] = []

        for folder_name, source_type in _SOURCE_TYPE_MAP.items():
            folder_path = self._base_path / folder_name
            if not folder_path.is_dir():
                logger.warning(
                    "Expected source folder not found, skipping: %s", folder_path
                )
                continue

            json_files = sorted(folder_path.glob("*.json"))
            if not json_files:
                logger.warning("No JSON files found in %s, skipping.", folder_path)
                continue

            for json_file in json_files:
                file_records = self._load_file(json_file, source_type, ingested_at)
                records.extend(file_records)
                logger.debug(
                    "Loaded %d record(s) from %s", len(file_records), json_file
                )

        self._last_run_at = ingested_at
        self._last_run_status = "ok"
        self._last_error = None

        logger.info(
            "SyntheticAdapter.fetch_batch() complete: %d total records from %s",
            len(records),
            self._base_path,
        )
        return records

    def poll(self, cursor: Optional[str]) -> PollResult:
        """Not supported — this adapter is batch-only.

        Raises:
            NotImplementedError: always.
        """
        raise NotImplementedError(
            "SyntheticAdapter is batch-only (mode='batch'). "
            "Use fetch_batch() instead of poll()."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_file(
        self,
        json_file: Path,
        source_type: str,
        ingested_at: str,
    ) -> List[RawRecord]:
        """Load one JSON file and return the RawRecord(s) it contains.

        Handles both a single-record dict and an array of record dicts.

        Args:
            json_file:   Path to the .json file.
            source_type: DOC3 §2.2 source_type value for this folder.
            ingested_at: ISO-8601 timestamp set on every record (same for the
                         whole fetch_batch() call, ensuring a single ingest
                         timestamp per batch run).

        Returns:
            List of RawRecord (one item for single-record files, N items for
            array files).

        Raises:
            json.JSONDecodeError: if the file is not valid JSON.
            ValueError: if a record is missing 'record_id' or 'payload'.
        """
        with json_file.open(encoding="utf-8") as fh:
            raw = json.load(fh)

        items: list = raw if isinstance(raw, list) else [raw]

        result: List[RawRecord] = []
        for item in items:
            # Validate required source fields before constructing the model
            if "record_id" not in item:
                raise ValueError(
                    f"Record in {json_file} is missing required field 'record_id': {item}"
                )
            if "payload" not in item:
                raise ValueError(
                    f"Record '{item['record_id']}' in {json_file} is missing required "
                    f"field 'payload'."
                )

            record = RawRecord(
                record_id=item["record_id"],
                dataset=_DATASET,
                source_type=source_type,
                source_adapter_id=_ADAPTER_ID,
                occurred_at=item.get("occurred_at"),
                ingested_at=ingested_at,
                payload=item["payload"],
                payload_text=item.get("payload_text"),
            )
            result.append(record)

        return result
