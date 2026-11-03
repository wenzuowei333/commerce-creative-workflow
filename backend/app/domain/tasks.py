from enum import StrEnum


class TaskState(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    AWAITING_PRODUCT_CONFIRMATION = "awaiting_product_confirmation"
    PROMPTING = "prompting"
    AWAITING_PROMPT_CONFIRMATION = "awaiting_prompt_confirmation"
    QUEUED = "queued"
    GENERATING = "generating"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.DRAFT: {TaskState.ANALYZING, TaskState.CANCELLED},
    TaskState.ANALYZING: {TaskState.AWAITING_PRODUCT_CONFIRMATION, TaskState.FAILED},
    TaskState.AWAITING_PRODUCT_CONFIRMATION: {TaskState.PROMPTING, TaskState.CANCELLED},
    TaskState.PROMPTING: {TaskState.AWAITING_PROMPT_CONFIRMATION, TaskState.FAILED},
    TaskState.AWAITING_PROMPT_CONFIRMATION: {TaskState.QUEUED, TaskState.CANCELLED},
    TaskState.QUEUED: {TaskState.GENERATING, TaskState.CANCELLED, TaskState.FAILED},
    TaskState.GENERATING: {
        TaskState.PARTIAL,
        TaskState.COMPLETED,
        TaskState.CANCELLED,
        TaskState.FAILED,
    },
    TaskState.PARTIAL: {TaskState.GENERATING, TaskState.COMPLETED, TaskState.CANCELLED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: {TaskState.QUEUED, TaskState.CANCELLED},
    TaskState.CANCELLED: set(),
}


def ensure_transition(current: TaskState, target: TaskState) -> None:
    if target not in TRANSITIONS[current]:
        raise ValueError(f"invalid task transition from {current.value} to {target.value}")
