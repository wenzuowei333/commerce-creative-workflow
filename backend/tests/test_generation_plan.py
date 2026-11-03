import pytest

from app.domain.generation import GenerationType, build_direction_slots


@pytest.mark.parametrize(
    ("count", "expected_directions"),
    [(5, 1), (10, 2), (15, 3)],
)
def test_main_image_count_maps_to_five_variants_per_direction(count, expected_directions):
    slots = build_direction_slots(GenerationType.MAIN, count)

    assert len(slots) == expected_directions
    assert all(len(direction.items) == 5 for direction in slots)
    assert all(item.module is None for direction in slots for item in direction.items)


def test_detail_images_have_fixed_five_module_story():
    slots = build_direction_slots(GenerationType.DETAIL, 5)

    assert [item.module for item in slots[0].items] == [
        "hero",
        "selling_point",
        "detail",
        "scene",
        "closing",
    ]


def test_generation_count_rejects_unsupported_values():
    with pytest.raises(ValueError, match="5, 10, 15"):
        build_direction_slots(GenerationType.MAIN, 6)
