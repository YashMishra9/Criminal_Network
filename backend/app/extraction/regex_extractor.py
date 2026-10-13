"""Regex-based entity/relationship extractor — B5, DOC3 §4.

Extracts well-formed identifiers from structured payload fields using
regex patterns and field-name heuristics. No NLP or ML dependencies —
runs in full offline mode without any model download.

Handles the following DOC3 §1.3 entity types:
  Phone          — 10-digit Indian mobile numbers, optionally +91 prefix
  Vehicle        — Indian vehicle registration plates (MH-01-AB-1234, DL05CD5678)
  BankAccount    — account numbers matching known patterns in the H1 dataset
  Transaction    — transaction records from the 'transaction' source type
  Organization   — company names from structured payload fields
  Person         — names from structured payload fields (fallback, no NLP)
  Location       — location strings from structured payload fields

Relationship types extracted:
  CALLED         — from CDR records (caller → callee)
  TRANSFERRED    — from transaction records (from_account → to_account)
  OWNS           — vehicle registered_owner → vehicle
  WORKS_FOR      — person → organization (from FIR/PR corporate fields)
  MENTIONED_IN   — entity → source record (general provenance edge)
"""

import hashlib
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.contracts.mention import EntityMention, RelationshipMention
from app.contracts.raw_record import RawRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Indian 10-digit mobile number (optionally with +91 / 91 prefix)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+91[\s\-]?|91[\s\-]?)?([6-9]\d{9})(?!\d)"
)

# Indian vehicle registration plate — various formats:
# MH-01-AB-1234  MH01AB1234  DL-05-CD-5678  KA01MN9999
_VEHICLE_RE = re.compile(
    r"\b([A-Z]{2})[\s\-]?(\d{2})[\s\-]?([A-Z]{1,3})[\s\-]?(\d{1,4})\b"
)

# Bank account identifiers used in H1 dataset (format: BANK-TYPE-NNNN)
_BANK_ACCOUNT_RE = re.compile(
    r"\b([A-Z]{2,10}-[A-Z]{2,8}-\d{4})\b"
)

# PAN number (Indian permanent account number)
_PAN_RE = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b")


def _make_mention_id(record_id: str, entity_type: str, raw_value: str, idx: int = 0) -> str:
    """Generate a stable, globally-unique mention_id."""
    digest = hashlib.sha256(
        f"{record_id}|{entity_type}|{raw_value}|{idx}".encode()
    ).hexdigest()[:12]
    return f"m_{entity_type[:3].lower()}_{digest}"


def _make_rel_id(record_id: str, rel_type: str, from_id: str, to_id: str) -> str:
    digest = hashlib.sha256(
        f"{record_id}|{rel_type}|{from_id}|{to_id}".encode()
    ).hexdigest()[:12]
    return f"rm_{rel_type.lower()[:6]}_{digest}"


# ---------------------------------------------------------------------------
# RegexExtractor
# ---------------------------------------------------------------------------

class RegexExtractor:
    """Extract structured identifiers and typed entities via regex and field heuristics.

    Stateless per record (DOC3 §4): no access to other records or the graph.
    Every mention carries record_id, dataset, and extraction_method='regex'
    as required by DOC3 §4.
    """

    def extract(
        self, record: RawRecord
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """Extract entities and relationships from one RawRecord.

        Dispatches to source-type-specific handlers, then also scans
        payload_text for additional identifiers (phone, vehicle, account).

        Args:
            record: one RawRecord; processed statelessly.

        Returns:
            (entities, relationships) — may be empty lists.
        """
        entities: List[EntityMention] = []
        relationships: List[RelationshipMention] = []

        source = record.source_type
        payload = record.payload or {}

        # Source-type-specific structured extraction
        if source == "CDR":
            e, r = self._extract_cdr(record, payload)
        elif source == "transaction":
            e, r = self._extract_transaction(record, payload)
        elif source == "vehicle_registry":
            e, r = self._extract_vehicle(record, payload)
        elif source in ("FIR", "police_report"):
            e, r = self._extract_fir_or_pr(record, payload)
        elif source == "surveillance":
            e, r = self._extract_surveillance(record, payload)
        elif source == "social_media":
            e, r = self._extract_social_media(record, payload)
        elif source == "rss":
            e, r = self._extract_rss(record, payload)
        else:
            e, r = [], []

        entities.extend(e)
        relationships.extend(r)

        # Always scan payload_text for additional phone/vehicle/account numbers
        # not already captured by structured extraction
        known_values = {m.raw_text for m in entities}
        extra_entities = self._scan_text(
            record, record.payload_text or "", known_values
        )
        entities.extend(extra_entities)

        return entities, relationships

    # ------------------------------------------------------------------
    # Source-type handlers
    # ------------------------------------------------------------------

    def _extract_cdr(
        self, record: RawRecord, payload: Dict[str, Any]
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """CDR → two Phone mentions + one CALLED relationship."""
        entities: List[EntityMention] = []
        relationships: List[RelationshipMention] = []

        caller_raw = str(payload.get("caller", "")).strip()
        callee_raw = str(payload.get("callee", "")).strip()

        if not caller_raw or not callee_raw:
            return entities, relationships

        m_caller = self._make_phone_mention(record, caller_raw, 0)
        m_callee = self._make_phone_mention(record, callee_raw, 1)
        entities.extend([m_caller, m_callee])

        attrs: Dict[str, Any] = {}
        if "duration_seconds" in payload:
            attrs["duration_seconds"] = payload["duration_seconds"]
        if "call_type" in payload:
            attrs["call_type"] = payload["call_type"]

        rel = RelationshipMention(
            relationship_mention_id=_make_rel_id(
                record.record_id, "CALLED", m_caller.mention_id, m_callee.mention_id
            ),
            record_id=record.record_id,
            dataset=record.dataset,
            relationship_type="CALLED",
            from_mention_id=m_caller.mention_id,
            to_mention_id=m_callee.mention_id,
            occurred_at=record.occurred_at,
            attributes=attrs,
            extraction_method="regex",
        )
        relationships.append(rel)
        return entities, relationships

    def _extract_transaction(
        self, record: RawRecord, payload: Dict[str, Any]
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """Transaction record → BankAccount/Person mentions + TRANSFERRED relationship."""
        entities: List[EntityMention] = []
        relationships: List[RelationshipMention] = []

        from_acct = str(payload.get("from_account", "")).strip()
        to_acct = str(payload.get("to_account", "")).strip()
        from_holder = str(payload.get("from_account_holder", "")).strip()
        to_holder = str(payload.get("to_account_holder", "")).strip()
        amount = payload.get("amount")
        currency = payload.get("currency", "INR")
        txn_type = payload.get("transaction_type", "")

        # Transaction entity (the record itself is a Transaction)
        txn_mention = EntityMention(
            mention_id=_make_mention_id(record.record_id, "Transaction", record.record_id),
            record_id=record.record_id,
            dataset=record.dataset,
            entity_type="Transaction",
            raw_text=record.record_id,
            normalized_value=record.record_id,
            attributes={
                "amount": amount,
                "currency": currency,
                "transaction_type": txn_type,
                "from_account": from_acct,
                "to_account": to_acct,
            },
            extraction_method="regex",
            confidence=1.0,
        )
        entities.append(txn_mention)

        # From-account bank account mention
        m_from: Optional[EntityMention] = None
        if from_acct and _BANK_ACCOUNT_RE.match(from_acct):
            m_from = EntityMention(
                mention_id=_make_mention_id(record.record_id, "BankAccount", from_acct, 0),
                record_id=record.record_id,
                dataset=record.dataset,
                entity_type="BankAccount",
                raw_text=from_acct,
                normalized_value=from_acct,
                attributes={"holder_name": from_holder},
                extraction_method="regex",
                confidence=0.95,
            )
            entities.append(m_from)

        # To-account bank account mention
        m_to: Optional[EntityMention] = None
        if to_acct and _BANK_ACCOUNT_RE.match(to_acct):
            m_to = EntityMention(
                mention_id=_make_mention_id(record.record_id, "BankAccount", to_acct, 1),
                record_id=record.record_id,
                dataset=record.dataset,
                entity_type="BankAccount",
                raw_text=to_acct,
                normalized_value=to_acct,
                attributes={"holder_name": to_holder},
                extraction_method="regex",
                confidence=0.95,
            )
            entities.append(m_to)

        # TRANSFERRED relationship between accounts
        if m_from and m_to:
            rel = RelationshipMention(
                relationship_mention_id=_make_rel_id(
                    record.record_id, "TRANSFERRED", m_from.mention_id, m_to.mention_id
                ),
                record_id=record.record_id,
                dataset=record.dataset,
                relationship_type="TRANSFERRED",
                from_mention_id=m_from.mention_id,
                to_mention_id=m_to.mention_id,
                occurred_at=record.occurred_at,
                attributes={"amount": amount, "currency": currency, "transaction_type": txn_type},
                extraction_method="regex",
            )
            relationships.append(rel)

        return entities, relationships

    def _extract_vehicle(
        self, record: RawRecord, payload: Dict[str, Any]
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """Vehicle registry → Vehicle mention + optional OWNS relationship."""
        entities: List[EntityMention] = []
        relationships: List[RelationshipMention] = []

        plate = str(payload.get("registration_number", "")).strip()
        owner_name = str(payload.get("registered_owner", "")).strip()
        make = payload.get("make", "")
        model_ = payload.get("model", "")
        color = payload.get("color", "")

        if not plate:
            return entities, relationships

        # Normalize plate: remove spaces/hyphens
        normalized_plate = re.sub(r"[\s\-]", "", plate).upper()

        m_vehicle = EntityMention(
            mention_id=_make_mention_id(record.record_id, "Vehicle", plate),
            record_id=record.record_id,
            dataset=record.dataset,
            entity_type="Vehicle",
            raw_text=plate,
            normalized_value=normalized_plate,
            attributes={
                "make": make,
                "model": model_,
                "color": color,
                "registered_owner_raw": owner_name,
            },
            extraction_method="regex",
            confidence=0.98,
        )
        entities.append(m_vehicle)

        if owner_name:
            m_owner = EntityMention(
                mention_id=_make_mention_id(record.record_id, "Person", owner_name),
                record_id=record.record_id,
                dataset=record.dataset,
                entity_type="Person",
                raw_text=owner_name,
                normalized_value=None,
                attributes={},
                extraction_method="regex",
                confidence=0.7,
            )
            entities.append(m_owner)

            rel = RelationshipMention(
                relationship_mention_id=_make_rel_id(
                    record.record_id, "OWNS", m_owner.mention_id, m_vehicle.mention_id
                ),
                record_id=record.record_id,
                dataset=record.dataset,
                relationship_type="OWNS",
                from_mention_id=m_owner.mention_id,
                to_mention_id=m_vehicle.mention_id,
                occurred_at=record.occurred_at,
                attributes={},
                extraction_method="regex",
            )
            relationships.append(rel)

        return entities, relationships

    def _extract_fir_or_pr(
        self, record: RawRecord, payload: Dict[str, Any]
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """FIR / police_report → Person + Organization mentions + WORKS_FOR."""
        entities: List[EntityMention] = []
        relationships: List[RelationshipMention] = []

        # Extract persons from accused/known_associates/suspect lists
        person_fields = ["accused", "suspects", "known_associates", "complainant_name"]
        persons: List[EntityMention] = []
        for field in person_fields:
            val = payload.get(field)
            if isinstance(val, list):
                for i, name in enumerate(val):
                    name_str = (name.get("name", "") if isinstance(name, dict) else str(name)).strip()
                    if name_str:
                        alias = (name.get("alias") if isinstance(name, dict) else None)
                        m = EntityMention(
                            mention_id=_make_mention_id(record.record_id, "Person", name_str, i),
                            record_id=record.record_id,
                            dataset=record.dataset,
                            entity_type="Person",
                            raw_text=name_str,
                            normalized_value=None,
                            attributes={"alias": alias} if alias else {},
                            extraction_method="regex",
                            confidence=0.8,
                        )
                        persons.append(m)
            elif isinstance(val, str) and val.strip():
                m = EntityMention(
                    mention_id=_make_mention_id(record.record_id, "Person", val.strip()),
                    record_id=record.record_id,
                    dataset=record.dataset,
                    entity_type="Person",
                    raw_text=val.strip(),
                    normalized_value=None,
                    attributes={},
                    extraction_method="regex",
                    confidence=0.8,
                )
                persons.append(m)

        entities.extend(persons)

        # Extract organizations
        org_fields = ["organizations_involved", "company_name", "organization"]
        orgs: List[EntityMention] = []
        for field in org_fields:
            val = payload.get(field)
            names = val if isinstance(val, list) else ([val] if isinstance(val, str) and val.strip() else [])
            for i, name in enumerate(names):
                name_str = (str(name)).strip() if name else ""
                if name_str:
                    m = EntityMention(
                        mention_id=_make_mention_id(record.record_id, "Organization", name_str, i),
                        record_id=record.record_id,
                        dataset=record.dataset,
                        entity_type="Organization",
                        raw_text=name_str,
                        normalized_value=None,
                        attributes={},
                        extraction_method="regex",
                        confidence=0.85,
                    )
                    orgs.append(m)
        entities.extend(orgs)

        # WORKS_FOR: each person who appears alongside an organization
        if persons and orgs:
            org = orgs[0]  # relate to the first (most prominent) org
            for person in persons:
                rel = RelationshipMention(
                    relationship_mention_id=_make_rel_id(
                        record.record_id, "WORKS_FOR", person.mention_id, org.mention_id
                    ),
                    record_id=record.record_id,
                    dataset=record.dataset,
                    relationship_type="WORKS_FOR",
                    from_mention_id=person.mention_id,
                    to_mention_id=org.mention_id,
                    occurred_at=record.occurred_at,
                    attributes={},
                    extraction_method="regex",
                )
                relationships.append(rel)

        return entities, relationships

    def _extract_surveillance(
        self, record: RawRecord, payload: Dict[str, Any]
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """Surveillance → Person + Location mentions + MET/VISITED relationship."""
        entities: List[EntityMention] = []
        relationships: List[RelationshipMention] = []

        persons_raw = payload.get("persons_observed", [])
        location_raw = str(payload.get("location", "")).strip()

        persons: List[EntityMention] = []
        for i, p in enumerate(persons_raw if isinstance(persons_raw, list) else []):
            name = (p.get("name", "") if isinstance(p, dict) else str(p)).strip()
            if name:
                m = EntityMention(
                    mention_id=_make_mention_id(record.record_id, "Person", name, i),
                    record_id=record.record_id,
                    dataset=record.dataset,
                    entity_type="Person",
                    raw_text=name,
                    normalized_value=None,
                    attributes={},
                    extraction_method="regex",
                    confidence=0.75,
                )
                persons.append(m)
        entities.extend(persons)

        m_loc: Optional[EntityMention] = None
        if location_raw:
            m_loc = EntityMention(
                mention_id=_make_mention_id(record.record_id, "Location", location_raw),
                record_id=record.record_id,
                dataset=record.dataset,
                entity_type="Location",
                raw_text=location_raw,
                normalized_value=None,
                attributes={},
                extraction_method="regex",
                confidence=0.8,
            )
            entities.append(m_loc)

        # Each person VISITED the location
        if m_loc:
            for person in persons:
                rel = RelationshipMention(
                    relationship_mention_id=_make_rel_id(
                        record.record_id, "VISITED", person.mention_id, m_loc.mention_id
                    ),
                    record_id=record.record_id,
                    dataset=record.dataset,
                    relationship_type="VISITED",
                    from_mention_id=person.mention_id,
                    to_mention_id=m_loc.mention_id,
                    occurred_at=record.occurred_at,
                    attributes={},
                    extraction_method="regex",
                )
                relationships.append(rel)

        # If ≥ 2 persons together, they MET
        if len(persons) >= 2:
            for i in range(len(persons)):
                for j in range(i + 1, len(persons)):
                    rel = RelationshipMention(
                        relationship_mention_id=_make_rel_id(
                            record.record_id, "MET",
                            persons[i].mention_id, persons[j].mention_id
                        ),
                        record_id=record.record_id,
                        dataset=record.dataset,
                        relationship_type="MET",
                        from_mention_id=persons[i].mention_id,
                        to_mention_id=persons[j].mention_id,
                        occurred_at=record.occurred_at,
                        attributes={},
                        extraction_method="regex",
                    )
                    relationships.append(rel)

        return entities, relationships

    def _extract_social_media(
        self, record: RawRecord, payload: Dict[str, Any]
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """Social media → Person/Organization mention."""
        entities: List[EntityMention] = []

        display_name = str(payload.get("display_name", "")).strip()
        account_name = str(payload.get("account_name", "")).strip()
        platform = payload.get("platform", "")
        raw_name = display_name or account_name

        if raw_name:
            # Heuristic: company/org indicators → Organization, else Person
            org_indicators = ["Ltd", "Pvt", "Inc", "Corp", "Co.", "Enterprise", "FZE", "LLC"]
            is_org = any(ind.lower() in raw_name.lower() for ind in org_indicators)
            etype = "Organization" if is_org else "Person"

            m = EntityMention(
                mention_id=_make_mention_id(record.record_id, etype, raw_name),
                record_id=record.record_id,
                dataset=record.dataset,
                entity_type=etype,  # type: ignore[arg-type]
                raw_text=raw_name,
                normalized_value=None,
                attributes={"platform": platform, "account_name": account_name},
                extraction_method="regex",
                confidence=0.7,
            )
            entities.append(m)

        return entities, []

    def _extract_rss(
        self, record: RawRecord, payload: Dict[str, Any]
    ) -> Tuple[List[EntityMention], List[RelationshipMention]]:
        """RSS — structured fields are minimal; rely on text scan."""
        return [], []

    # ------------------------------------------------------------------
    # Cross-source text scan
    # ------------------------------------------------------------------

    def _scan_text(
        self, record: RawRecord, text: str, known_values: set
    ) -> List[EntityMention]:
        """Scan free text for phones, vehicle plates, and bank accounts."""
        extra: List[EntityMention] = []

        # Phones
        for m in _PHONE_RE.finditer(text):
            raw = m.group(0).strip()
            normalized = m.group(1)
            if normalized not in known_values and raw not in known_values:
                em = self._make_phone_mention(record, normalized, len(extra))
                known_values.add(normalized)
                extra.append(em)

        # Vehicle plates
        for m in _VEHICLE_RE.finditer(text):
            raw = m.group(0).strip()
            normalized = re.sub(r"[\s\-]", "", raw).upper()
            if normalized not in known_values and raw not in known_values:
                em = EntityMention(
                    mention_id=_make_mention_id(record.record_id, "Vehicle", raw, len(extra)),
                    record_id=record.record_id,
                    dataset=record.dataset,
                    entity_type="Vehicle",
                    raw_text=raw,
                    normalized_value=normalized,
                    attributes={},
                    extraction_method="regex",
                    confidence=0.85,
                )
                known_values.add(normalized)
                extra.append(em)

        # Bank account numbers
        for m in _BANK_ACCOUNT_RE.finditer(text):
            raw = m.group(1).strip()
            if raw not in known_values:
                em = EntityMention(
                    mention_id=_make_mention_id(record.record_id, "BankAccount", raw, len(extra)),
                    record_id=record.record_id,
                    dataset=record.dataset,
                    entity_type="BankAccount",
                    raw_text=raw,
                    normalized_value=raw,
                    attributes={},
                    extraction_method="regex",
                    confidence=0.9,
                )
                known_values.add(raw)
                extra.append(em)

        return extra

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_phone_mention(
        self, record: RawRecord, raw: str, idx: int
    ) -> EntityMention:
        normalized = re.sub(r"[\s\-\+]", "", raw)
        if normalized.startswith("91") and len(normalized) == 12:
            normalized = normalized[2:]
        return EntityMention(
            mention_id=_make_mention_id(record.record_id, "Phone", raw, idx),
            record_id=record.record_id,
            dataset=record.dataset,
            entity_type="Phone",
            raw_text=raw,
            normalized_value=normalized,
            attributes={},
            extraction_method="regex",
            confidence=0.95,
        )
