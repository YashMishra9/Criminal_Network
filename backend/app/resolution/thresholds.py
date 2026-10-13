"""Resolution thresholds — B7, DOC2 §8.

All matching thresholds are defined here as named constants.
No threshold value may be hardcoded inline elsewhere (DOC2 §8,
B7 §11). To tune a threshold, change it here only.

Threshold meanings:
  FUZZY_NAME_MERGE   — minimum similarity score to merge two name mentions.
  FUZZY_NAME_REVIEW  — score below this and above MERGE → stored as rejected
                       decision (auditable near-miss). Not currently used in
                       batch mode but reserved for the review queue.
  LOCATION_MERGE     — minimum prefix-token overlap to merge two locations.
  ORG_PREFIX_MERGE   — minimum fraction of tokens shared to merge two org names.
"""

# ---------------------------------------------------------------------------
# Name matching thresholds (0.0 – 1.0)
# ---------------------------------------------------------------------------

# Minimum similarity for two Person name mentions to be merged.
# Set to 0.70 to catch "Rahul Sharma" ≈ "R. Sharma" ≈ "SHARMA R" ≈ "Rahul S."
FUZZY_NAME_MERGE: float = 0.70

# Near-miss threshold: decisions with score in [FUZZY_NAME_REVIEW, FUZZY_NAME_MERGE)
# are stored as outcome='rejected' for audit. Not implemented in batch v1.
FUZZY_NAME_REVIEW: float = 0.55

# ---------------------------------------------------------------------------
# Organization name thresholds
# ---------------------------------------------------------------------------

# Minimum token-overlap fraction to merge two Organization name mentions.
# 0.50 → "Khanna Enterprises" (2 tokens) overlaps "Khanna Enterprises Pvt Ltd"
# (4 tokens) at overlap/max = 2/4 = 0.50. Exactly at threshold → merged.
ORG_PREFIX_MERGE: float = 0.50

# ---------------------------------------------------------------------------
# Location thresholds
# ---------------------------------------------------------------------------

# Minimum fraction of significant tokens shared to merge two Location mentions.
# "Hotel Sunrise, Andheri" ≈ "Hotel Sunrise, Link Road, Andheri West, Mumbai"
LOCATION_MERGE: float = 0.40

# ---------------------------------------------------------------------------
# Shared-attribute resolution (exact match — no threshold needed for these)
# ---------------------------------------------------------------------------
# Phone, Vehicle, BankAccount, Transaction → always exact normalized value match.
# No float threshold applies.

# ---------------------------------------------------------------------------
# Score constants for returned ResolutionDecision.score
# ---------------------------------------------------------------------------

SCORE_EXACT: float = 1.0
SCORE_SHARED_ATTRIBUTE: float = 0.95
