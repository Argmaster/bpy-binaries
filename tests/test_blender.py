"""Test bpy capabilities."""
import bpy


def test_set_selection() -> None:
    """Check if selection works."""
    for o in bpy.context.scene.objects:
        o.select_set(state=True)
