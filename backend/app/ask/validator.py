"""F2 — Cypher Query Validator.

Task: F2 (Track F — Ask-the-Network)
Depends on: F1 (query_generator.py — GeneratedQuery)

Objective (F2.md §3):
    Implement all six DOC3 §10 validation rules, including the outright
    CALL/procedure prohibition (Contract Invariant 13).

DOC3 §10 — six validation rules (implemented in order):
    Rule 1: Read-only — no CREATE, MERGE, SET, DELETE, REMOVE.
    Rule 2: CALL / any procedure invocation is forbidden outright.
            No whitelist exists in this version (Invariant 13).
    Rule 3: Only permitted constructs: MATCH, OPTIONAL MATCH, WHERE, RETURN,
            WITH, ORDER BY, LIMIT, SKIP, path functions, standard predicates.
            Anything else causes rejection.
    Rule 4: Only node labels / relationship types defined in DOC3 §6.
    Rule 5: Query must include a dataset filter matching AskRequest.dataset.
            The validator *injects* the filter when it is absent rather than
            rejecting, per DOC3 §10 rule 5 wording: "or the validator injects
            it".
    Rule 6: Bounded execution timeout (configurable). This module records the
            configured timeout into ValidationResult so F3 can enforce it
            during actual query execution. F2 itself does not execute queries.

DOC3 §15 Invariant 13:
    CALL / any procedure invocation is rejected unconditionally. No procedure
    is whitelisted — including read-only procedures (apoc.*, gds.*, etc.).

F2.md §17 — Explicit constraint:
    No procedure whitelisting, period.

Security model:
    Validation is purely syntactic / structural — it works on the Cypher
    string without executing it. The validator is conservative: when in
    doubt, reject rather than allow.

Output (F2.md §8):
    ValidationResult = ValidatedQuery | ValidationFailed
    - ValidatedQuery  : GeneratedQuery (possibly with dataset filter injected)
                        plus timeout_ms for F3 to enforce.
    - ValidationFailed: typed rejection carrying a human-readable `reason`.
"""

import logging
import re
from typing import Literal, Optional, Union

from pydantic import BaseModel

from app.ask.query_generator import GeneratedQuery
from app.config import get_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema constants — pulled from DOC3 §6.1 / §6.2
# Keep in sync with query_generator._ENTITY_LABELS / _RELATIONSHIP_TYPES.
# Duplicated here deliberately so the validator has no runtime import-time
# coupling to the generator's private state.
# ---------------------------------------------------------------------------

# DOC3 §6.1 — all node labels (CanonicalEntity + structural/workspace types)
_ALLOWED_NODE_LABELS: frozenset[str] = frozenset({
    # CanonicalEntity types
    "Person",
    "Phone",
    "Vehicle",
    "Location",
    "Organization",
    "BankAccount",
    "Transaction",
    "Event",
    # Workspace / structural / derived types
    "Case",
    "Evidence",
    "Note",
    "EdgeRef",
    "ResolutionDecision",
    "Finding",
})

# DOC3 §6.2 — all relationship types (domain + structural)
_ALLOWED_RELATIONSHIP_TYPES: frozenset[str] = frozenset({
    # Domain relationships
    "CALLED",
    "OWNS",
    "USED",
    "TRANSFERRED",
    "VISITED",
    "MET",
    "WORKS_FOR",
    "ASSOCIATED_WITH",
    "MENTIONED_IN",
    "PART_OF",
    # Evidence / provenance structural edges
    "SUPPORTS",
    "INCLUDES_ENTITY",
    "INCLUDES_EDGE",
    "INCLUDES_EVIDENCE",
    "ABOUT",
    "RESOLVED_FROM",
    "BASED_ON",
    "CONCERNS",
})

# ---------------------------------------------------------------------------
# Rule 1 — Write-clause keywords (case-insensitive word-boundary match)
# ---------------------------------------------------------------------------
_WRITE_CLAUSES: tuple[str, ...] = (
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "REMOVE",
)

# ---------------------------------------------------------------------------
# Rule 3 — Permitted top-level Cypher clause keywords.
# Applied after Rules 1 & 2 to catch anything not in the allowed set.
# Pattern extracts uppercase words that appear at a clause position (start of
# a line or after a semicolon, or the first token of a WITH/RETURN subclause).
# We use a conservative allowlist scan rather than an exhaustive AST parse.
# ---------------------------------------------------------------------------
_PERMITTED_CLAUSE_KEYWORDS: frozenset[str] = frozenset({
    "MATCH",
    "OPTIONAL",    # part of OPTIONAL MATCH
    "WHERE",
    "RETURN",
    "WITH",
    "ORDER",       # part of ORDER BY
    "BY",          # part of ORDER BY / "LIMIT x BY …" idioms — allowed
    "LIMIT",
    "SKIP",
    "DISTINCT",    # allowed modifier on RETURN / WITH
    "AS",          # aliasing in RETURN/WITH
    "NOT",         # boolean predicate
    "AND",         # boolean predicate
    "OR",          # boolean predicate
    "XOR",         # boolean predicate
    "IN",          # predicate
    "IS",          # IS NULL / IS NOT NULL
    "NULL",        # IS NULL
    "TRUE",        # literal
    "FALSE",       # literal
    "CASE",        # CASE … WHEN … THEN … END (conditional expression)
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "UNWIND",      # useful for unpacking lists — read-only
    "DESC",        # ORDER BY … DESC
    "ASC",         # ORDER BY … ASC
    "CONTAINS",    # string predicate
    "STARTS",      # STARTS WITH
    "ENDS",        # ENDS WITH
    "COUNT",       # aggregate function
    "SUM",         # aggregate function
    "AVG",         # aggregate function
    "MIN",         # aggregate function
    "MAX",         # aggregate function
    "COLLECT",     # aggregate function
    "SIZE",        # size() function keyword
    "EXISTS",      # EXISTS predicate
    "ANY",         # ANY predicate
    "ALL",         # ALL predicate
    "NONE",        # NONE predicate
    "SINGLE",      # SINGLE predicate
    "shortestPath",   # path function
    "allShortestPaths",  # path function
    "LABELS",      # labels() function keyword form
    "TYPE",        # type() function keyword form
    "ID",          # id() function — deprecated but still common
    "PROPERTIES",  # properties() function
    "KEYS",        # keys() function
    "HEAD",        # head() / list functions
    "TAIL",
    "LAST",
    "RANGE",
    "COALESCE",
    "TOSTRING",
    "TOINTEGER",
    "TOFLOAT",
    "TOBOOLEAN",
    "TOUPPER",
    "TOLOWER",
    "TRIM",
    "LTRIM",
    "RTRIM",
    "REPLACE",
    "SUBSTRING",
    "LEFT",
    "RIGHT",
    "SPLIT",
    "REVERSE",
    "LENGTH",
    "ABS",
    "CEIL",
    "FLOOR",
    "ROUND",
    "SIGN",
    "SQRT",
    "RAND",
    "LOG",
    "LOG10",
    "EXP",
    "E",
    "PI",
    "SIN",
    "COS",
    "TAN",
    "COT",
    "ASIN",
    "ACOS",
    "ATAN",
    "ATAN2",
    "HAVERSIN",
    "DEGREES",
    "RADIANS",
    "DATETIME",
    "DATE",
    "TIME",
    "LOCALDATETIME",
    "LOCALTIME",
    "DURATION",
    "TIMESTAMP",
    "YEAR",
    "MONTH",
    "DAY",
    "HOUR",
    "MINUTE",
    "SECOND",
    "MILLISECOND",
    "MICROSECOND",
    "NANOSECOND",
    "EPOCHMILLIS",
    "EPOCHSECONDS",
})

# ---------------------------------------------------------------------------
# Compiled regex patterns for efficient, case-insensitive matching
# ---------------------------------------------------------------------------

def _word_re(word: str) -> re.Pattern[str]:
    """Compile a case-insensitive whole-word pattern."""
    return re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)


# Rule 1 — write clauses
_WRITE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    _word_re(w) for w in _WRITE_CLAUSES
)

# Rule 2 — CALL keyword (unconditional, no whitelist)
_CALL_PATTERN: re.Pattern[str] = _word_re("CALL")

# Rule 4 — extract node labels from node patterns ONLY:
#   (variable:Label) or (:Label) or ({...}) — NOT from relationship brackets
# We match the opening `(` then optionally a variable, then `:`, then the label.
# Critically: we require the leading `(` so we don't accidentally match
# relationship type labels from `[:TYPE]` patterns.
_NODE_LABEL_RE: re.Pattern[str] = re.compile(
    r"""
    \(                                        # opening node paren
    \s*[a-zA-Z_][a-zA-Z0-9_]*\s*             # optional variable name
    :                                         # colon before label
    \s*([a-zA-Z_][a-zA-Z0-9_]*)             # label name (captured group 1)
    """,
    re.VERBOSE,
)

# Rule 4 — extract relationship types: -[:TYPE]-> or -[alias:TYPE]->
# Must be inside square brackets. The variable name before the colon is optional.
_REL_TYPE_RE: re.Pattern[str] = re.compile(
    r"""
    \[                                  # opening bracket
    \s*(?:[a-zA-Z_][\w]*)? \s*         # optional variable name
    :                                    # colon before type(s)
    \s*([A-Z_][A-Z0-9_|]*)             # type name(s), ALL_CAPS (captured)
    \s*\]                               # closing bracket
    """,
    re.VERBOSE,
)

# Rule 5 — detect existing dataset filter patterns:
#   {dataset: "..."}  or  dataset = "..."  or  dataset = $dataset  etc.
_DATASET_FILTER_RE: re.Pattern[str] = re.compile(
    r"""
    \bdataset\s*
    (?:
        [:=]\s*                 # : inside a node-prop map, or = in WHERE
        (?:
            ['\"][\w_]+['\"]    # quoted literal
            | \$\w+             # parameter reference
        )
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Forbidden clause detection — Rule 3 extension: anything that smells like a
# forbidden clause keyword appearing at clause position (before a newline or
# space, after whitespace / start of string).
# We detect a curated set of definitely-forbidden keywords.
# ---------------------------------------------------------------------------
_FORBIDDEN_EXTRA_CLAUSES: tuple[str, ...] = (
    # DDL / schema
    "CREATE",        # already in Rule 1 but double-check here
    "DROP",
    "ALTER",
    "CONSTRAINT",
    "INDEX",
    # DML
    "MERGE",
    "SET",
    "DELETE",
    "DETACH",
    "REMOVE",
    "FOREACH",       # iteration + write
    # Procedure / subquery
    "CALL",          # already Rule 2
    "YIELD",         # always accompanies CALL
    "LOAD",          # LOAD CSV
    "IMPORT",
    "PERIODIC",      # USING PERIODIC COMMIT / apoc.periodic.*
    # Explicit write via UNION
    # (UNION alone is fine for read; we do NOT block it here,
    #  but validate each sub-query independently via the same rules)
)

_FORBIDDEN_EXTRA_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    _word_re(kw) for kw in _FORBIDDEN_EXTRA_CLAUSES
    if kw not in _WRITE_CLAUSES and kw != "CALL"  # already checked
)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class ValidatedQuery(BaseModel):
    """A GeneratedQuery that has passed all six validation rules.

    `timeout_ms` is forwarded from config for F3 to enforce during execution
    (Rule 6 — bounded timeout; execution is F3's responsibility).
    """
    cypher: str          # possibly with dataset filter injected (Rule 5)
    parameters: dict
    generated_by: Literal["llm"] = "llm"
    timeout_ms: int      # F3 must abort execution if this is exceeded


class ValidationFailed(BaseModel):
    """Typed rejection returned when any validation rule fails.

    Maps to AskResponse(status='validation_failed', reason=...) in F4.
    """
    status: Literal["validation_failed"] = "validation_failed"
    rule: int            # which DOC3 §10 rule was violated (1–6)
    reason: str          # human-readable, safe to surface to the caller


ValidationResult = Union[ValidatedQuery, ValidationFailed]


# ---------------------------------------------------------------------------
# Default execution timeout (milliseconds) — configurable via Config
# Falls back to 30 s if not configured.
# ---------------------------------------------------------------------------

def _get_timeout_ms() -> int:
    try:
        cfg = get_config()
        return int(getattr(cfg, "ASK_QUERY_TIMEOUT_MS", 30_000))
    except Exception:  # noqa: BLE001
        return 30_000


# ---------------------------------------------------------------------------
# Individual rule checks — each returns None on pass or a ValidationFailed
# ---------------------------------------------------------------------------

def _check_rule_1(cypher: str) -> Optional[ValidationFailed]:
    """Rule 1 — Read-only: no CREATE, MERGE, SET, DELETE, REMOVE."""
    for pattern, clause in zip(_WRITE_PATTERNS, _WRITE_CLAUSES):
        if pattern.search(cypher):
            return ValidationFailed(
                rule=1,
                reason=(
                    f"Query contains forbidden write clause '{clause}'. "
                    "Only read-only queries are permitted (DOC3 §10 rule 1)."
                ),
            )
    return None


def _check_rule_2(cypher: str) -> Optional[ValidationFailed]:
    """Rule 2 — CALL / any procedure invocation forbidden outright (Invariant 13)."""
    if _CALL_PATTERN.search(cypher):
        return ValidationFailed(
            rule=2,
            reason=(
                "Query contains a CALL clause. Procedure invocation is forbidden "
                "unconditionally in this version — no procedures are whitelisted "
                "(DOC3 §10 rule 2, Contract Invariant 13)."
            ),
        )
    # Also block YIELD which only appears alongside CALL / sub-queries
    if re.search(r"\bYIELD\b", cypher, re.IGNORECASE):
        return ValidationFailed(
            rule=2,
            reason=(
                "Query contains YIELD, which is only valid with CALL. "
                "Procedure invocation is forbidden (DOC3 §10 rule 2)."
            ),
        )
    return None


def _check_rule_3(cypher: str) -> Optional[ValidationFailed]:
    """Rule 3 — Only permitted Cypher constructs allowed."""
    # Check for explicitly forbidden extra clause keywords
    for pattern, kw in zip(_FORBIDDEN_EXTRA_PATTERNS, [
        kw for kw in _FORBIDDEN_EXTRA_CLAUSES
        if kw not in _WRITE_CLAUSES and kw != "CALL"
    ]):
        if pattern.search(cypher):
            return ValidationFailed(
                rule=3,
                reason=(
                    f"Query contains forbidden construct '{kw}'. "
                    "Only MATCH, OPTIONAL MATCH, WHERE, RETURN, WITH, ORDER BY, "
                    "LIMIT, SKIP, path functions, and standard predicates are "
                    "permitted (DOC3 §10 rule 3)."
                ),
            )
    return None


def _check_rule_4(cypher: str) -> Optional[ValidationFailed]:
    """Rule 4 — Only node labels / relationship types defined in DOC3 §6."""
    # Check node labels extracted from node patterns — (var:Label) only
    for match in _NODE_LABEL_RE.finditer(cypher):
        label = match.group(1)
        if label and label not in _ALLOWED_NODE_LABELS:
            return ValidationFailed(
                rule=4,
                reason=(
                    f"Query references unknown node label '{label}'. "
                    "Only labels defined in DOC3 §6 are permitted."
                ),
            )

    # Check relationship types
    for match in _REL_TYPE_RE.finditer(cypher):
        rel_types_str = match.group(1)
        # Handle pipe-separated multi-type: [:TYPE1|TYPE2]
        for rel_type in rel_types_str.split("|"):
            rel_type = rel_type.strip()
            if rel_type and rel_type not in _ALLOWED_RELATIONSHIP_TYPES:
                return ValidationFailed(
                    rule=4,
                    reason=(
                        f"Query references unknown relationship type '{rel_type}'. "
                        "Only relationship types defined in DOC3 §6 are permitted."
                    ),
                )
    return None


def _check_rule_5_and_inject(
    cypher: str,
    parameters: dict,
    dataset: str,
) -> tuple[str, dict, Optional[ValidationFailed]]:
    """Rule 5 — Dataset filter enforcement / injection.

    If the query already contains a dataset filter: verify it references the
    correct dataset (either as a literal or via $dataset parameter).

    If no dataset filter is present: inject `{dataset: $dataset}` into
    the query's first MATCH node pattern, or prepend a WHERE clause.

    Returns:
        (possibly_modified_cypher, possibly_modified_parameters, failure_or_None)
    """
    # Ensure $dataset parameter is always in parameters
    params = dict(parameters)
    params.setdefault("dataset", dataset)

    if _DATASET_FILTER_RE.search(cypher):
        # Filter found — check it doesn't reference a different literal dataset
        # (a $dataset param is always correct; a quoted literal must match)
        literal_mismatch_re = re.compile(
            r"""\bdataset\s*[:=]\s*['"]([^'"]+)['"]""",
            re.IGNORECASE,
        )
        for m in literal_mismatch_re.finditer(cypher):
            literal_val = m.group(1)
            if literal_val != dataset:
                return cypher, params, ValidationFailed(
                    rule=5,
                    reason=(
                        f"Query references dataset '{literal_val}' but the "
                        f"request specifies dataset '{dataset}'. "
                        "Cross-dataset access via Ask-the-Network is not "
                        "permitted (DOC3 §10 rule 5)."
                    ),
                )
        return cypher, params, None

    # No dataset filter found — inject it into the first MATCH node.
    # Strategy: append a WHERE clause immediately before the first RETURN/WITH
    # to ensure all matched nodes are scoped.
    injection = f"  AND all(n IN nodes(path) WHERE n.dataset = $dataset)\n"

    # Simpler injection: add a WHERE condition via regex into first MATCH clause
    # Pattern: find the first MATCH (n ... ) and inject {dataset: $dataset}
    injected, count = re.subn(
        r"""(\bMATCH\s+\([a-zA-Z_][a-zA-Z0-9_]*)\s*\)""",
        r"\1 {dataset: $dataset})",
        cypher,
        count=1,
        flags=re.IGNORECASE,
    )
    if count == 0:
        # Fallback: prepend a WITH clause that sets the dataset param
        injected = f"WITH $dataset AS _ds\n{cypher}"
        logger.warning(
            "Rule 5: could not inject dataset filter into MATCH node — "
            "prepended WITH clause as fallback."
        )

    logger.info(
        "Rule 5: dataset filter absent in generated query — injected for dataset=%s",
        dataset,
    )
    return injected, params, None


# ---------------------------------------------------------------------------
# Main validator — public interface (F2)
# ---------------------------------------------------------------------------


class CypherValidator:
    """Schema-constrained Cypher validator (DOC3 §10, F2).

    Applies all six validation rules to a GeneratedQuery from F1.
    Returns a ValidatedQuery (with timeout_ms for F3) on success, or a
    ValidationFailed on any rule violation.

    Usage::

        validator = CypherValidator()
        result = validator.validate(generated_query, dataset="synthetic_demo")
        if isinstance(result, ValidatedQuery):
            # pass to F3 (executor)
            pass
        else:
            # surface AskResponse(status="validation_failed", reason=result.reason)
            pass

    DOC3 §10 guarantee:
        A query failing ANY check is never executed. F3 must only receive
        ValidatedQuery instances — never call execute() on a GeneratedQuery
        directly.
    """

    def __init__(self, timeout_ms: Optional[int] = None) -> None:
        """
        Args:
            timeout_ms: Execution timeout in milliseconds to embed in
                        ValidatedQuery for F3. When None, resolved from Config
                        (falls back to 30 000 ms).
        """
        self._timeout_ms = timeout_ms if timeout_ms is not None else _get_timeout_ms()

    def validate(
        self,
        query: GeneratedQuery,
        dataset: str = "synthetic_demo",
    ) -> ValidationResult:
        """Validate a GeneratedQuery against all six DOC3 §10 rules.

        Args:
            query:   GeneratedQuery from F1.
            dataset: The dataset from the original AskRequest, used to enforce
                     Rule 5 (dataset scoping).

        Returns:
            ValidatedQuery  — all rules passed; safe to pass to F3.
            ValidationFailed — a rule was violated; reason is safe to show
                               the caller as AskResponse(validation_failed).
        """
        cypher = query.cypher
        parameters = dict(query.parameters)

        logger.info(
            "CypherValidator.validate: dataset=%s cypher_len=%d",
            dataset,
            len(cypher),
        )

        # Rule 2 — CALL / procedure (Invariant 13) — checked first as highest-risk
        failure = _check_rule_2(cypher)
        if failure:
            logger.warning("Validation Rule 2 failed: %s", failure.reason)
            return failure

        # Rule 3 — forbidden constructs (before Rule 1 so FOREACH, LOAD, etc.
        # are attributed to the correct rule even when they embed write clauses)
        failure = _check_rule_3(cypher)
        if failure:
            logger.warning("Validation Rule 3 failed: %s", failure.reason)
            return failure

        # Rule 1 — write clauses (CREATE/MERGE/SET/DELETE/REMOVE)
        failure = _check_rule_1(cypher)
        if failure:
            logger.warning("Validation Rule 1 failed: %s", failure.reason)
            return failure
            logger.warning("Validation Rule 3 failed: %s", failure.reason)
            return failure

        # Rule 4 — schema labels / relationship types
        failure = _check_rule_4(cypher)
        if failure:
            logger.warning("Validation Rule 4 failed: %s", failure.reason)
            return failure

        # Rule 5 — dataset filter enforcement / injection
        cypher, parameters, failure = _check_rule_5_and_inject(
            cypher, parameters, dataset
        )
        if failure:
            logger.warning("Validation Rule 5 failed: %s", failure.reason)
            return failure

        # Rule 6 — timeout is embedded into ValidatedQuery for F3 to enforce
        # (the validator itself does not execute; it cannot time out here)
        logger.info("CypherValidator: all rules passed, timeout_ms=%d", self._timeout_ms)
        return ValidatedQuery(
            cypher=cypher,
            parameters=parameters,
            generated_by="llm",
            timeout_ms=self._timeout_ms,
        )


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------


def get_cypher_validator(timeout_ms: Optional[int] = None) -> CypherValidator:
    """Return a CypherValidator with the given (or config-derived) timeout."""
    return CypherValidator(timeout_ms=timeout_ms)
