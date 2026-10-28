"""Learning from errors and feedback (ADR-011); the loop and its gate come in phase 7."""

from core.learning.errors import (
    ERROR_EVENT,
    ErrorRecord,
    budget_error,
    decision_errors,
    journal_errors,
    judge_error,
)
from core.learning.feedback import (
    FEEDBACK_EVENT,
    VERDICTS,
    FeedbackError,
    default_feedback_path,
    give_feedback,
)

__all__ = [
    "ERROR_EVENT",
    "FEEDBACK_EVENT",
    "VERDICTS",
    "ErrorRecord",
    "FeedbackError",
    "budget_error",
    "decision_errors",
    "default_feedback_path",
    "give_feedback",
    "journal_errors",
    "judge_error",
]
