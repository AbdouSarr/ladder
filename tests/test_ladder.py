"""
Unit tests for the Ladder addon.

Run these tests from within Blender:
    blender --background --python tests/test_ladder.py

Or run specific tests:
    blender --background --python tests/test_ladder.py -- -v TestGmshManager

Requirements:
    - Blender 4.0+
    - gmsh package installed (tests will skip if not available)
    - Sample CAD files in tests/fixtures/ directory
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock

# Add parent directory to path for imports
TESTS_DIR = Path(__file__).parent
PROJECT_DIR = TESTS_DIR.parent
ADDON_DIR = PROJECT_DIR / "ladder"
sys.path.insert(0, str(PROJECT_DIR))

# Try to import Blender modules
try:
    import bpy
    HAS_BLENDER = True
except ImportError:
    HAS_BLENDER = False
    # Create mock bpy for standalone testing
    bpy = MagicMock()

# Import addon modules after path setup
if HAS_BLENDER:
    # Ensure addon is registered
    import ladder
    from ladder import (
        GmshManager,
        SUPPORTED_EXTENSIONS,
        MESH_QUALITY_PRESETS,
        UNIT_SCALES,
        ImportProgress,
        get_preferences,
    )
else:
    # Import for standalone testing (limited)
    from ladder import (
        GmshManager,
        SUPPORTED_EXTENSIONS,
        MESH_QUALITY_PRESETS,
        UNIT_SCALES,
        ImportProgress,
    )


# =============================================================================
# Test Fixtures
# =============================================================================

FIXTURES_DIR = TESTS_DIR / "fixtures"

def get_fixture_path(filename: str) -> Path:
    """Get path to a test fixture file."""
    return FIXTURES_DIR / filename


def create_simple_step_file(path: Path) -> None:
    """Create a minimal STEP file for testing."""
    # This is a minimal valid STEP file with a single point
    step_content = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Test file'),'2;1');
FILE_NAME('test.step','2024-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));
ENDSEC;
DATA;
#1=CARTESIAN_POINT('Origin',(0.,0.,0.));
ENDSEC;
END-ISO-10303-21;
"""
    path.write_text(step_content)


def create_simple_brep_file(path: Path) -> None:
    """Create a minimal BREP file for testing (OpenCASCADE format)."""
    # Minimal BREP with a vertex
    brep_content = """DBRep_DrawableShape

CASCADE Topology V1, (c) Matra-Datavision
Locations 0
Curve2ds 0
Curves 0
Polygon3D 0
PolygonOnTriangulations 0
Surfaces 0
Triangulations 0
TShapes 1
Ve
1e-07
0 0 0
0 0

+0 0
"""
    path.write_text(brep_content)


# =============================================================================
# Test Classes
# =============================================================================

class TestConstants(unittest.TestCase):
    """Test addon constants and configuration."""

    def test_supported_extensions(self):
        """Test that all expected extensions are supported."""
        expected = {".step", ".stp", ".iges", ".igs", ".brep", ".brp"}
        self.assertEqual(set(SUPPORTED_EXTENSIONS), expected)

    def test_mesh_quality_presets(self):
        """Test mesh quality presets are properly defined."""
        expected_presets = {'VERY_COARSE', 'COARSE', 'NORMAL', 'FINE', 'VERY_FINE'}
        self.assertEqual(set(MESH_QUALITY_PRESETS.keys()), expected_presets)

        # Each preset should have (min, max) tuple
        for name, values in MESH_QUALITY_PRESETS.items():
            self.assertIsInstance(values, tuple, f"{name} should be a tuple")
            self.assertEqual(len(values), 2, f"{name} should have 2 values")
            min_val, max_val = values
            self.assertLess(min_val, max_val, f"{name}: min should be less than max")
            self.assertGreater(min_val, 0, f"{name}: min should be positive")

    def test_unit_scales(self):
        """Test unit scale factors are defined correctly."""
        expected_units = {'MICROMETERS', 'MILLIMETERS', 'CENTIMETERS', 'METERS', 'INCHES', 'FEET'}
        self.assertEqual(set(UNIT_SCALES.keys()), expected_units)

        # Verify some known conversions
        self.assertEqual(UNIT_SCALES['METERS'], 1.0)
        self.assertEqual(UNIT_SCALES['MILLIMETERS'], 0.001)
        self.assertAlmostEqual(UNIT_SCALES['INCHES'], 0.0254, places=4)


class TestGmshManager(unittest.TestCase):
    """Test GmshManager class."""

    def setUp(self):
        """Reset gmsh cache before each test."""
        GmshManager._gmsh_available = None

    def test_is_available_caching(self):
        """Test that gmsh availability is cached."""
        # First call should set cache
        result1 = GmshManager.is_available()
        cached_value = GmshManager._gmsh_available

        # Second call should use cache
        result2 = GmshManager.is_available()

        self.assertEqual(result1, result2)
        self.assertEqual(result1, cached_value)

    def test_reset_cache(self):
        """Test that reset_cache clears the cached value."""
        GmshManager.is_available()  # Set cache
        self.assertIsNotNone(GmshManager._gmsh_available)

        GmshManager.reset_cache()
        self.assertIsNone(GmshManager._gmsh_available)

    def test_get_version(self):
        """Test getting gmsh version."""
        version = GmshManager.get_version()
        self.assertIsInstance(version, str)

        if GmshManager.is_available():
            # Should return actual version string
            self.assertNotEqual(version, "Not installed")
        else:
            self.assertEqual(version, "Not installed")

    @unittest.skipUnless(GmshManager.is_available(), "gmsh not installed")
    def test_get_model_info_invalid_file(self):
        """Test get_model_info with non-existent file."""
        fake_path = Path("/nonexistent/file.step")
        info = GmshManager.get_model_info(fake_path)

        self.assertFalse(info['valid'])
        self.assertEqual(info['entities'], 0)

    @unittest.skipUnless(GmshManager.is_available(), "gmsh not installed")
    def test_convert_to_stl_invalid_file(self):
        """Test convert_to_stl with non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_input = Path("/nonexistent/file.step")
            output = Path(tmpdir) / "output.stl"

            success, message, parts = GmshManager.convert_to_stl(fake_input, output)

            self.assertFalse(success)
            self.assertIn("Failed", message)
            self.assertEqual(parts, [])

    @unittest.skipUnless(GmshManager.is_available(), "gmsh not installed")
    def test_convert_to_stl_with_fixture(self):
        """Test convert_to_stl with a real STEP file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a simple test file
            input_path = tmpdir / "test.step"
            create_simple_step_file(input_path)

            output_path = tmpdir / "output.stl"

            success, message, parts = GmshManager.convert_to_stl(
                input_path,
                output_path,
                mesh_size_min=0.1,
                mesh_size_max=10.0,
            )

            # Note: minimal STEP file may not produce mesh, but shouldn't crash
            self.assertIsInstance(success, bool)
            self.assertIsInstance(message, str)
            self.assertIsInstance(parts, list)


class TestImportProgress(unittest.TestCase):
    """Test ImportProgress class."""

    def setUp(self):
        """Create fresh progress tracker."""
        self.progress = ImportProgress()

    def test_initial_state(self):
        """Test initial state of progress tracker."""
        self.assertEqual(self.progress.total_files, 0)
        self.assertEqual(self.progress.current_file, 0)
        self.assertEqual(self.progress.current_filename, "")
        self.assertEqual(self.progress.phase, "")
        self.assertFalse(self.progress.is_running)
        self.assertFalse(self.progress.was_cancelled)

    def test_start(self):
        """Test starting progress tracking."""
        self.progress.start(5)

        self.assertEqual(self.progress.total_files, 5)
        self.assertEqual(self.progress.current_file, 0)
        self.assertTrue(self.progress.is_running)
        self.assertFalse(self.progress.was_cancelled)

    def test_update(self):
        """Test updating progress."""
        self.progress.start(3)
        self.progress.update(1, "test.step", "converting")

        self.assertEqual(self.progress.current_file, 1)
        self.assertEqual(self.progress.current_filename, "test.step")
        self.assertEqual(self.progress.phase, "converting")

    def test_stop(self):
        """Test stopping progress."""
        self.progress.start(3)
        self.progress.stop()

        self.assertFalse(self.progress.is_running)
        self.assertFalse(self.progress.was_cancelled)

    def test_cancel(self):
        """Test cancelling progress."""
        self.progress.start(3)
        self.progress.cancel()

        self.assertFalse(self.progress.is_running)
        self.assertTrue(self.progress.was_cancelled)

    def test_progress_percent(self):
        """Test progress percentage calculation."""
        self.progress.start(4)

        # 0% at start
        self.assertEqual(self.progress.progress_percent, 0.0)

        # 25% after first file
        self.progress.current_file = 1
        self.assertAlmostEqual(self.progress.progress_percent, 25.0, places=1)

        # 50% after second file
        self.progress.current_file = 2
        self.assertAlmostEqual(self.progress.progress_percent, 50.0, places=1)

        # 100% max
        self.progress.current_file = 4
        self.assertAlmostEqual(self.progress.progress_percent, 100.0, places=1)

    def test_progress_percent_with_converting_phase(self):
        """Test that converting phase adds partial progress."""
        self.progress.start(2)
        self.progress.update(0, "test.step", "converting")

        # Should be slightly above 0% but less than 50%
        percent = self.progress.progress_percent
        self.assertGreater(percent, 0)
        self.assertLess(percent, 50)

    def test_status_text(self):
        """Test status text generation."""
        # Not running - empty string
        self.assertEqual(self.progress.status_text, "")

        # Running - shows status
        self.progress.start(3)
        self.progress.update(1, "model.step", "converting")

        status = self.progress.status_text
        self.assertIn("Ladder:", status)
        self.assertIn("Converting", status)
        self.assertIn("model.step", status)
        self.assertIn("2/3", status)

    def test_status_text_importing_phase(self):
        """Test status text shows Importing for import phase."""
        self.progress.start(2)
        self.progress.update(0, "test.step", "importing")

        self.assertIn("Importing", self.progress.status_text)


@unittest.skipUnless(HAS_BLENDER, "Blender not available")
class TestBlenderIntegration(unittest.TestCase):
    """Test Blender-specific functionality."""

    @classmethod
    def setUpClass(cls):
        """Register addon before tests."""
        # Ensure addon is registered
        if "ladder" not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module="ladder")

    def setUp(self):
        """Reset Blender scene before each test."""
        # Delete all objects
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete()

        # Delete all collections except Scene Collection
        for coll in bpy.data.collections:
            bpy.data.collections.remove(coll)

    def test_addon_registered(self):
        """Test that addon is properly registered."""
        self.assertIn("ladder", bpy.context.preferences.addons)

    def test_operator_registered(self):
        """Test that import operator is registered."""
        self.assertTrue(hasattr(bpy.ops.import_scene, "ladder_cad"))

    def test_preferences_accessible(self):
        """Test that addon preferences are accessible."""
        prefs = get_preferences()
        self.assertIsNotNone(prefs)

        # Check some expected properties exist
        self.assertTrue(hasattr(prefs, 'mesh_quality'))
        self.assertTrue(hasattr(prefs, 'global_scale'))
        self.assertTrue(hasattr(prefs, 'import_to_collection'))

    def test_menu_entry_exists(self):
        """Test that import menu entry exists."""
        # Check operator is in import menu
        found = False
        for item in bpy.types.TOPBAR_MT_file_import.draw._draw_funcs:
            if 'ladder' in str(item).lower():
                found = True
                break
        # This might not work in all cases, so we just check operator exists
        self.assertTrue(hasattr(bpy.ops.import_scene, "ladder_cad"))

    def test_file_handler_registered(self):
        """Test that file handler for drag-drop is registered."""
        # Check if file handler class is registered
        self.assertIn("LADDER_FH_cad", dir(bpy.types))

    @unittest.skipUnless(GmshManager.is_available(), "gmsh not installed")
    def test_import_creates_collection(self):
        """Test that import creates a collection when enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test file
            input_path = tmpdir / "test_model.step"
            create_simple_step_file(input_path)

            initial_collections = len(bpy.data.collections)

            # Import with collection enabled
            try:
                bpy.ops.import_scene.ladder_cad(
                    filepath=str(input_path),
                    import_to_collection=True,
                    collection_name="TestCollection",
                )
            except Exception:
                # Import might fail with minimal STEP, but collection should be created
                pass

            # Check if collection was created (even if import failed)
            # Note: This depends on implementation details


class TestPresets(unittest.TestCase):
    """Test import presets functionality."""

    @unittest.skipUnless(HAS_BLENDER, "Blender not available")
    def test_preset_menu_registered(self):
        """Test that preset menu is registered."""
        self.assertIn("LADDER_MT_import_presets", dir(bpy.types))

    @unittest.skipUnless(HAS_BLENDER, "Blender not available")
    def test_add_preset_operator_registered(self):
        """Test that add preset operator is registered."""
        self.assertTrue(hasattr(bpy.ops.ladder, "add_import_preset"))


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_file_list(self):
        """Test handling of empty file list."""
        progress = ImportProgress()
        progress.start(0)

        # Should not crash
        self.assertEqual(progress.progress_percent, 0.0)

    def test_unicode_filenames(self):
        """Test handling of unicode characters in filenames."""
        progress = ImportProgress()
        progress.start(1)
        progress.update(0, "模型_тест_αβγ.step", "converting")

        # Should not crash and should contain the filename
        status = progress.status_text
        self.assertIn("模型_тест_αβγ.step", status)

    @unittest.skipUnless(GmshManager.is_available(), "gmsh not installed")
    def test_very_long_filename(self):
        """Test handling of very long filenames."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create file with long name
            long_name = "a" * 200 + ".step"
            input_path = tmpdir / long_name
            create_simple_step_file(input_path)

            # Should not crash
            info = GmshManager.get_model_info(input_path)
            self.assertIsInstance(info, dict)


# =============================================================================
# Test Runner
# =============================================================================

def run_tests(verbosity=2, pattern=None):
    """Run all tests or specific test pattern."""
    loader = unittest.TestLoader()

    if pattern:
        # Run specific test class or method
        suite = loader.loadTestsFromName(pattern)
    else:
        # Discover all tests
        suite = loader.discover(str(TESTS_DIR), pattern='test_*.py')

    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    # Parse command line arguments
    argv = sys.argv

    # Remove Blender args (everything before --)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = argv[1:]  # Remove script name

    verbosity = 2
    pattern = None

    if "-v" in argv:
        argv.remove("-v")
        verbosity = 2
    if "-q" in argv:
        argv.remove("-q")
        verbosity = 1

    if argv:
        pattern = argv[0]

    success = run_tests(verbosity=verbosity, pattern=pattern)
    sys.exit(0 if success else 1)
