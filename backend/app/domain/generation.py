from dataclasses import dataclass
from enum import StrEnum


class GenerationType(StrEnum):
    MAIN = "main"
    DETAIL = "detail"


@dataclass(frozen=True)
class ItemSlot:
    index: int
    module: str | None = None


@dataclass(frozen=True)
class DirectionSlot:
    index: int
    items: tuple[ItemSlot, ...]


DETAIL_MODULES = ("hero", "selling_point", "detail", "scene", "closing")


def build_direction_slots(generation_type: GenerationType, count: int) -> tuple[DirectionSlot, ...]:
    if count not in {5, 10, 15}:
        raise ValueError("generation count must be one of 5, 10, 15")

    directions: list[DirectionSlot] = []
    for direction_index in range(count // 5):
        modules = DETAIL_MODULES if generation_type == GenerationType.DETAIL else (None,) * 5
        items = tuple(
            ItemSlot(index=item_index, module=module) for item_index, module in enumerate(modules)
        )
        directions.append(DirectionSlot(index=direction_index, items=items))
    return tuple(directions)
