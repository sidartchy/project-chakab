import enum


class RunStatus(str, enum.Enum):
    pending = "pending"        # Job received, not yet processed
    planning = "planning"      # Intake & plan generation in progress
    executing = "executing"    # Sandbox running
    validating = "validating"  # Awaiting human review
    approved = "approved"      # Human approved, delivery in progress
    rejected = "rejected"      # Human rejected
    delivered = "delivered"    # PR opened successfully
    aborted = "aborted"        # Retry budget exhausted or out-of-scope


class IssueIntent(str, enum.Enum):
    bug_fix = "bug_fix"
    refactor = "refactor"
    type_fix = "type_fix"
    enhancement = "enhancement"
    unknown = "unknown"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"   # Auto-rejected at intake