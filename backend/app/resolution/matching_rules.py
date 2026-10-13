"""Matching rules for Entity Resolution — B7, DOC3 §5.

Each rule takes two EntityMention objects (scoped to the same entity_type
and dataset — the caller enforces this) and returns a MatchResult indicating
whether they should be merged, which field they matched on, and a score.

Rules are ordered by specificity (highest-confidence first):
  1. exact_match       — identical normalized_value (Phone, Vehicle, BankAccount)
  2. shared_attribute  — same value on a key attribute (phone on Person, account on Person/Org)
  3. fuzzy_match       — name similarity above threshold (Person, Organization, Location)

No rule crosses dataset boundaries — the resolver filters by dataset before
calling any rule (DOC3 §2.6, Contract Invariant 2).
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.contracts.mention import EntityMention
from app.resolution import thresholds


# ---------------------------------------------------------------------------
# MatchResult — returned by every rule
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    """Outcome of comparing two EntityMention objects."""

    should_merge: bool
    """True → callers should merge these mentions into one CanonicalEntity."""

    method: str
    """One of DOC3 §1.7's method values: exact_match, fuzzy_match,
    shared_attribute, embedding_similarity, manual."""

    matched_on: List[str] = field(default_factory=list)
    """Human-readable list of fields/signals that drove the decision."""

    score: Optional[float] = None
    """Similarity score 0.0–1.0, or None when not applicable."""


# ---------------------------------------------------------------------------
# Public entry point — dispatches by entity_type
# ---------------------------------------------------------------------------

def compare(m1: EntityMention, m2: EntityMention) -> MatchResult:
    """Compare two EntityMention objects of the same type and dataset.

    Dispatches to the per-entity-type rule. Always returns a MatchResult;
    never raises.

    Preconditions (caller must enforce):
      - m1.entity_type == m2.entity_type
      - m1.dataset == m2.dataset
      - m1.mention_id != m2.mention_id

    Args:
        m1: First mention.
        m2: Second mention.

    Returns:
        MatchResult indicating whether and why they should be merged.
    """
    etype = m1.entity_type

    if etype == "Person":
        return _compare_persons(m1, m2)
    if etype in ("Phone", "Vehicle", "BankAccount"):
        return _compare_exact_identifier(m1, m2)
    if etype == "Organization":
        return _compare_organizations(m1, m2)
    if etype == "Location":
        return _compare_locations(m1, m2)
    if etype == "Transaction":
        return _compare_transactions(m1, m2)
    if etype == "Event":
        return _compare_events(m1, m2)

    # Unknown type — no merge
    return MatchResult(should_merge=False, method="exact_match", matched_on=[], score=0.0)


# ---------------------------------------------------------------------------
# Per-type rules
# ---------------------------------------------------------------------------

def _compare_exact_identifier(m1: EntityMention, m2: EntityMention) -> MatchResult:
    """Phone / Vehicle / BankAccount — merge on identical normalized_value."""
    v1 = (m1.normalized_value or m1.raw_text).strip().upper()
    v2 = (m2.normalized_value or m2.raw_text).strip().upper()

    if v1 == v2 and v1:
        return MatchResult(
            should_merge=True,
            method="exact_match",
            matched_on=[f"normalized_value={v1}"],
            score=thresholds.SCORE_EXACT,
        )
    return MatchResult(should_merge=False, method="exact_match", matched_on=[], score=0.0)


def _compare_persons(m1: EntityMention, m2: EntityMention) -> MatchResult:
    """Person — cascade: shared attribute (phone/account/vehicle) → name fuzzy."""

    # 1. Shared phone (both extracted from payload fields or regex scan)
    phone1 = _get_attr(m1, "phone") or _phone_from_raw(m1.normalized_value)
    phone2 = _get_attr(m2, "phone") or _phone_from_raw(m2.normalized_value)
    if phone1 and phone2 and phone1 == phone2:
        return MatchResult(
            should_merge=True,
            method="shared_attribute",
            matched_on=[f"phone={phone1}"],
            score=thresholds.SCORE_SHARED_ATTRIBUTE,
        )

    # 2. Shared bank account
    acct1 = _get_attr(m1, "account") or _get_attr(m1, "bank_account")
    acct2 = _get_attr(m2, "account") or _get_attr(m2, "bank_account")
    if acct1 and acct2 and acct1.upper() == acct2.upper():
        return MatchResult(
            should_merge=True,
            method="shared_attribute",
            matched_on=[f"bank_account={acct1}"],
            score=thresholds.SCORE_SHARED_ATTRIBUTE,
        )

    # 3. Shared vehicle plate
    plate1 = _get_attr(m1, "vehicle") or _get_attr(m1, "plate")
    plate2 = _get_attr(m2, "vehicle") or _get_attr(m2, "plate")
    if plate1 and plate2 and _normalize_plate(plate1) == _normalize_plate(plate2):
        return MatchResult(
            should_merge=True,
            method="shared_attribute",
            matched_on=[f"vehicle={plate1}"],
            score=thresholds.SCORE_SHARED_ATTRIBUTE,
        )

    # 4. Shared PAN / DL / DOB (identity attributes)
    for attr_key in ("pan", "dl", "dob"):
        a1 = _get_attr(m1, attr_key)
        a2 = _get_attr(m2, attr_key)
        if a1 and a2 and a1.upper() == a2.upper():
            return MatchResult(
                should_merge=True,
                method="shared_attribute",
                matched_on=[f"{attr_key}={a1}"],
                score=thresholds.SCORE_SHARED_ATTRIBUTE,
            )

    # 5. Name fuzzy match
    score = _name_similarity(m1.raw_text, m2.raw_text)
    if score >= thresholds.FUZZY_NAME_MERGE:
        return MatchResult(
            should_merge=True,
            method="fuzzy_match",
            matched_on=[f"name_similarity>{thresholds.FUZZY_NAME_MERGE:.2f}"],
            score=score,
        )

    return MatchResult(should_merge=False, method="fuzzy_match", matched_on=[], score=score)


def _compare_organizations(m1: EntityMention, m2: EntityMention) -> MatchResult:
    """Organization — exact → token-prefix overlap."""

    # 1. Exact name (normalized)
    n1 = _normalize_org_name(m1.raw_text)
    n2 = _normalize_org_name(m2.raw_text)
    if n1 == n2 and n1:
        return MatchResult(
            should_merge=True,
            method="exact_match",
            matched_on=["org_name_exact"],
            score=thresholds.SCORE_EXACT,
        )

    # 2. Shared account (bank account common to two org mentions)
    acct1 = _get_attr(m1, "account") or _get_attr(m1, "bank_account")
    acct2 = _get_attr(m2, "account") or _get_attr(m2, "bank_account")
    if acct1 and acct2 and acct1.upper() == acct2.upper():
        return MatchResult(
            should_merge=True,
            method="shared_attribute",
            matched_on=[f"bank_account={acct1}"],
            score=thresholds.SCORE_SHARED_ATTRIBUTE,
        )

    # 3. Token overlap (one name is a prefix/subset of the other)
    score = _token_overlap(n1, n2)
    if score >= thresholds.ORG_PREFIX_MERGE:
        return MatchResult(
            should_merge=True,
            method="fuzzy_match",
            matched_on=[f"org_name_token_overlap>{thresholds.ORG_PREFIX_MERGE:.2f}"],
            score=score,
        )

    return MatchResult(should_merge=False, method="fuzzy_match", matched_on=[], score=score)


def _compare_locations(m1: EntityMention, m2: EntityMention) -> MatchResult:
    """Location — token overlap on significant words."""
    score = _token_overlap(
        _normalize_location(m1.raw_text),
        _normalize_location(m2.raw_text),
    )
    if score >= thresholds.LOCATION_MERGE:
        return MatchResult(
            should_merge=True,
            method="fuzzy_match",
            matched_on=[f"location_token_overlap>{thresholds.LOCATION_MERGE:.2f}"],
            score=score,
        )
    return MatchResult(should_merge=False, method="fuzzy_match", matched_on=[], score=score)


def _compare_transactions(m1: EntityMention, m2: EntityMention) -> MatchResult:
    """Transaction — merge only if record_id is identical (same raw transaction)."""
    if m1.record_id == m2.record_id and m1.normalized_value == m2.normalized_value:
        return MatchResult(
            should_merge=True,
            method="exact_match",
            matched_on=["transaction_id_exact"],
            score=thresholds.SCORE_EXACT,
        )
    return MatchResult(should_merge=False, method="exact_match", matched_on=[], score=0.0)


def _compare_events(m1: EntityMention, m2: EntityMention) -> MatchResult:
    """Event — token overlap (same approach as Location)."""
    score = _token_overlap(
        _normalize_location(m1.raw_text),
        _normalize_location(m2.raw_text),
    )
    if score >= thresholds.LOCATION_MERGE:
        return MatchResult(
            should_merge=True,
            method="fuzzy_match",
            matched_on=[f"event_token_overlap>{thresholds.LOCATION_MERGE:.2f}"],
            score=score,
        )
    return MatchResult(should_merge=False, method="fuzzy_match", matched_on=[], score=score)


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

# Tokens to ignore when comparing location/org strings
_STOP_WORDS = frozenset({
    "and", "the", "a", "an", "of", "in", "at", "on", "to", "for",
    "pvt", "ltd", "llp", "inc", "corp", "co", "fze", "llc",
    "hotel", "road", "street", "st", "avenue", "av", "lane", "ln",
    "west", "east", "north", "south", "nagar", "bandra",
})


def _tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return [
        t for t in re.sub(r"[^\w\s]", " ", text.lower()).split()
        if t and t not in _STOP_WORDS
    ]


def _normalize_org_name(name: str) -> str:
    tokens = _tokenize(name)
    return " ".join(sorted(tokens))  # order-independent canonical form


def _normalize_location(name: str) -> str:
    return " ".join(_tokenize(name))


def _normalize_plate(plate: str) -> str:
    return re.sub(r"[\s\-]", "", plate).upper()


def _phone_from_raw(val: Optional[str]) -> Optional[str]:
    """Extract normalized 10-digit number from a raw phone string."""
    if not val:
        return None
    digits = re.sub(r"\D", "", val)
    if len(digits) == 10:
        return digits
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    return None


def _get_attr(mention: EntityMention, key: str) -> Optional[str]:
    """Safely get a string attribute from mention.attributes dict."""
    attrs = mention.attributes or {}
    val = attrs.get(key)
    return str(val).strip() if val else None


def _token_overlap(s1: str, s2: str) -> float:
    """Fraction of shared significant tokens relative to the larger set."""
    t1 = set(_tokenize(s1))
    t2 = set(_tokenize(s2))
    if not t1 or not t2:
        return 0.0
    intersection = t1 & t2
    return len(intersection) / max(len(t1), len(t2))


def _name_similarity(n1: str, n2: str) -> float:
    """Compute a name similarity score handling Indian name abbreviation patterns.

    Handles: "Rahul Sharma" ≈ "R. Sharma" ≈ "SHARMA R" ≈ "Rahul S."

    Strategy (cascade, returns the highest matching score found):
      1. Exact normalized match → 1.0
      2. Token overlap score (significant tokens only)
      3. Last-name + initial match (e.g., "R. Sharma" ≈ "Rahul Sharma")
      4. Reversed-token match (e.g., "SHARMA R" ≈ "Rahul Sharma")

    Returns:
        float in [0.0, 1.0]
    """
    def normalize(s: str) -> str:
        return re.sub(r"[^\w\s]", "", s.strip().lower())

    a = normalize(n1)
    b = normalize(n2)

    if a == b:
        return 1.0

    tokens_a = a.split()
    tokens_b = b.split()

    # 1. Token overlap (order-independent)
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    overlap = len(set_a & set_b) / max(len(set_a), len(set_b)) if set_a and set_b else 0.0

    # 2. Last-name + initial match  e.g. ["r", "sharma"] ≈ ["rahul", "sharma"]
    #    → last token matches AND first token is initial of the other's first token
    #    OR first token matches AND last token is initial of the other's last token
    def _initial_match(ta: List[str], tb: List[str]) -> bool:
        if len(ta) < 2 or len(tb) < 2:
            return False
        a0, a_last = ta[0], ta[-1]
        b0, b_last = tb[0], tb[-1]
        # Case 1: last tokens match, first token is initial (R. Sharma ≈ Rahul Sharma)
        if a_last == b_last:
            if (len(a0) == 1 and b0.startswith(a0)) or (len(b0) == 1 and a0.startswith(b0)):
                return True
        # Case 2: first tokens match, last token is initial (Rahul S. ≈ Rahul Sharma)
        if a0 == b0:
            if (len(a_last) == 1 and b_last.startswith(a_last)) or (len(b_last) == 1 and a_last.startswith(b_last)):
                return True
        # Case 3: first token of one is prefix of first token of other (Dev ≈ Devendra)
        # AND last tokens match exactly
        if a_last == b_last:
            if a0.startswith(b0) or b0.startswith(a0):
                return True
        return False

    initial_match = _initial_match(tokens_a, tokens_b)
    if initial_match:
        overlap = max(overlap, 0.88)

    # 3. Reversed-token match  e.g. ["sharma", "r"] ≈ ["rahul", "sharma"]
    def _reversed_match(ta: List[str], tb: List[str]) -> bool:
        if len(ta) < 2 or len(tb) < 2:
            return False
        # Check if ta reversed ≈ tb (handles "SHARMA R" vs "Rahul Sharma")
        ta_rev = list(reversed(ta))
        return _initial_match(ta_rev, tb) or _initial_match(ta, list(reversed(tb)))

    if _reversed_match(tokens_a, tokens_b):
        overlap = max(overlap, 0.85)

    return overlap
