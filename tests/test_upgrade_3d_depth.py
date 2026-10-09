import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "upgrade_3d_depth.py"
SPEC = importlib.util.spec_from_file_location("upgrade_3d_depth", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
UPGRADE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADE_MODULE)
UpgradeError = UPGRADE_MODULE.UpgradeError
transform = UPGRADE_MODULE.transform


FIXTURE = '''
import math

class FakeVisualizer:
    def _setup(self):
        self.cam_distance = max(35.0, self.radius_z * 2.2)

    def _compute_3d_layout(self):
        internal_zones = ["a", "b", "c"]
        for i, zone_name in enumerate(internal_zones):
            ring_idx = i % 2
            radius_x = 1.0
            radius_z = 2.0
            angle = 0.0
            x = radius_x * math.cos(angle)
            z = radius_z * math.sin(angle)
            y = math.sin(i * 1.5) * 1.0
            self.node_positions[zone_name] = [x, y, z]

    def draw(self):
        while True:
            if self.show_connections and self.graph:
                for conn in self.graph.connections_list:
                    p1 = self.node_positions.get(conn.zone1)
                    p2 = self.node_positions.get(conn.zone2)
                    if p1 and p2:
                        waiting = self._pending_link_load(conn.zone1, conn.zone2)
                        capacity = max(1, conn.max_link_capacity)
                        line_color = self._connection_color(waiting / capacity)
                        pr.draw_line_3d(p1, p2, line_color)
'''


class Upgrade3DDepthTests(unittest.TestCase):
    def test_adds_tubes_and_height_layers(self):
        upgraded = transform(FIXTURE)
        self.assertIn("pr.draw_cylinder_ex(", upgraded)
        self.assertIn("_height_step", upgraded)
        self.assertIn("_height_step_for_view", upgraded)
        self.assertIn("_central_degree_threshold", upgraded)
        self.assertNotIn("pr.draw_line_3d(p1, p2, line_color)", upgraded)

    def test_transform_is_idempotent(self):
        upgraded = transform(FIXTURE)
        self.assertEqual(transform(upgraded), upgraded)

    def test_refuses_partial_upgrade(self):
        partial = FIXTURE.replace(
            "y = math.sin(i * 1.5) * 1.0",
            "# VISUAL DEPTH UPGRADE: stable height layers\ny = 0.0",
        )
        with self.assertRaises(UpgradeError):
            transform(partial)

    def test_refuses_unknown_anchors(self):
        with self.assertRaises(UpgradeError):
            transform(FIXTURE.replace("pr.draw_line_3d(p1, p2, line_color)", "pass"))


if __name__ == "__main__":
    unittest.main()
