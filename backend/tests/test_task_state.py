import pytest

from app.domain.tasks import TaskState, ensure_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskState.DRAFT, TaskState.ANALYZING),
        (TaskState.ANALYZING, TaskState.AWAITING_PRODUCT_CONFIRMATION),
        (TaskState.GENERATING, TaskState.PARTIAL),
        (TaskState.GENERATING, TaskState.COMPLETED),
        (TaskState.PARTIAL, TaskState.COMPLETED),
    ],
)
def test_valid_task_transitions(current, target):
    ensure_transition(current, target)


def test_completed_task_cannot_return_to_generating():
    with pytest.raises(ValueError, match="completed"):
        ensure_transition(TaskState.COMPLETED, TaskState.GENERATING)
