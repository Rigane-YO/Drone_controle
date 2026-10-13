import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from apply_layout_modes_patch import apply_patch_to_source  # noqa: E402


FIXTURE = '''class Visualizer:
    def __init__(self):
        self.show_connections = True
        _height_step_for_view = max(3.2, self.planet_size * 1.7)
        self.cam_distance = max(
            35.0,
            self.radius_z * 2.2,
            _height_step_for_view * 5.0,
        )

    def _compute_3d_layout(self) -> None:
        """Répartit les planètes sur plusieurs anneaux concentriques."""
        if not self.graph or not self.simulator:
            return
        zones = list(self.graph.zones.keys())
        self.node_positions[self.simulator.start_hub] = [-self.radius_x, 0.0, 0.0]

    def _init_drones(self) -> None:
        pass

    def _draw_options_menu(self) -> None:
        speed_label = f"VITESSE DE SIMULATION : {self.step_interval:.2f}s / tour"
        pr.draw_text(speed_label, 60, 260, 20, COLOR_WHITE)
        self._draw_speed_slider(60, 302, 320)
        pr.draw_text("L : noms | K : jauges | T : traînées", 60, 340, 16, COLOR_GRAY)
        pr.draw_text(
            "F : suivre drone | R : caméra | RETOUR : annuler un tour",
            60, 365, 16, COLOR_GRAY
        )

    def _handle_keys(self) -> None:
        if self.app_state == STATE_SIMULATION:
            if True:
                if pr.is_key_pressed(pr.KEY_M):
                    self.show_minimap = not self.show_minimap

    def _draw_hud(self) -> None:
        if self.simulator:
            if True:
                pr.draw_text(f"Tour : {self.simulator.turn}", 20, 45, 22, COLOR_WHITE)
'''


class LayoutPatchTests(unittest.TestCase):
    def test_adds_both_layout_modes(self):
        patched = apply_patch_to_source(FIXTURE)
        self.assertIn('self.layout_mode = "custom"', patched)
        self.assertIn("def _compute_map_layout(self) -> None:", patched)
        self.assertIn("(float(zone.x) - center_x) * scale", patched)
        self.assertIn("(float(zone.y) - center_y) * scale", patched)
        self.assertIn("def _toggle_layout_mode(self) -> None:", patched)
        self.assertIn("pr.KEY_V", patched)
        self.assertIn('"COORDONNÉES CARTE"', patched)
        compile(patched, "fixture_visualizer.py", "exec")

    def test_patch_is_idempotent(self):
        once = apply_patch_to_source(FIXTURE)
        twice = apply_patch_to_source(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
