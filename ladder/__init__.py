"""
Ladder - CAD Import for Blender
Import STEP, IGES, and BREP files into Blender using gmsh.
"""

from __future__ import annotations

bl_info = {
    "name": "Ladder",
    "author": "Abdou Sarr",
    "description": "Import CAD files (STEP, IGES, BREP) into Blender",
    "blender": (4, 0, 0),
    "version": (1, 0, 0),
    "location": "File > Import > CAD Files or Drag-and-Drop",
    "warning": "",
    "doc_url": "https://github.com/abdousarr/ladder",
    "tracker_url": "https://github.com/abdousarr/ladder/issues",
    "category": "Import-Export"
}

import bpy
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Set, List, Tuple, Any, Dict

from bpy.props import (
    StringProperty,
    BoolProperty,
    EnumProperty,
    FloatProperty,
)
from bpy_extras.io_utils import ImportHelper, poll_file_object_drop
from bpy.app.handlers import persistent


# =============================================================================
# Logging Setup
# =============================================================================

logger = logging.getLogger("Ladder")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[Ladder] %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# =============================================================================
# Constants
# =============================================================================

SUPPORTED_EXTENSIONS: Tuple[str, ...] = (
    ".step", ".stp",      # STEP (ISO 10303)
    ".iges", ".igs",      # IGES (Initial Graphics Exchange Specification)
    ".brep", ".brp",      # BREP (OpenCASCADE boundary representation)
)

EXTENSION_FILTER: str = ";".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)

# Unit scale factors (source unit -> meters)
UNIT_SCALES: Dict[str, float] = {
    'MICROMETERS': 0.000001,
    'MILLIMETERS': 0.001,
    'CENTIMETERS': 0.01,
    'METERS': 1.0,
    'INCHES': 0.0254,
    'FEET': 0.3048,
}


# =============================================================================
# Gmsh Manager
# =============================================================================

class GmshManager:
    """Manages gmsh installation and CAD conversion."""

    _gmsh_available: Optional[bool] = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if gmsh is installed and importable."""
        if cls._gmsh_available is not None:
            return cls._gmsh_available

        try:
            import gmsh
            cls._gmsh_available = True
            logger.info(f"gmsh {gmsh.GMSH_API_VERSION} is available")
            return True
        except ImportError:
            cls._gmsh_available = False
            logger.warning("gmsh is not installed")
            return False

    @classmethod
    def reset_cache(cls) -> None:
        """Reset the availability cache (after install attempt)."""
        cls._gmsh_available = None

    @classmethod
    def get_version(cls) -> str:
        """Get gmsh version string."""
        if not cls.is_available():
            return "Not installed"
        try:
            import gmsh
            return gmsh.GMSH_API_VERSION
        except Exception:
            return "Unknown"

    @classmethod
    def install(cls) -> Tuple[bool, str]:
        """Install gmsh using pip."""
        python = sys.executable
        try:
            logger.info("Installing gmsh via pip...")
            result = subprocess.run(
                [python, "-m", "pip", "install", "gmsh"],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                cls.reset_cache()
                if cls.is_available():
                    return True, "gmsh installed successfully"
                else:
                    return False, "gmsh installed but cannot be imported"
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                return False, f"pip install failed: {error_msg}"

        except subprocess.TimeoutExpired:
            return False, "Installation timed out"
        except Exception as e:
            return False, f"Installation error: {e}"

    @classmethod
    def get_model_info(cls, input_path: Path) -> Dict[str, Any]:
        """Get information about a CAD model without full conversion."""
        info: Dict[str, Any] = {
            'valid': False,
            'entities': 0,
            'volumes': 0,
            'surfaces': 0,
            'curves': 0,
            'points': 0,
            'bounding_box': None,
            'estimated_unit': 'UNKNOWN',
            'part_names': [],
        }

        if not cls.is_available():
            return info

        try:
            import gmsh

            gmsh.initialize()
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("info")

            file_ext = input_path.suffix.lower()
            try:
                if file_ext in (".step", ".stp", ".iges", ".igs", ".brep", ".brp"):
                    gmsh.model.occ.importShapes(str(input_path))
                    gmsh.model.occ.synchronize()
                else:
                    gmsh.merge(str(input_path))
            except Exception as e:
                logger.debug(f"Failed to load model info: {e}")
                gmsh.finalize()
                return info

            info['valid'] = True

            # Count entities
            entities = gmsh.model.getEntities()
            info['entities'] = len(entities)

            for dim, tag in entities:
                if dim == 0:
                    info['points'] += 1
                elif dim == 1:
                    info['curves'] += 1
                elif dim == 2:
                    info['surfaces'] += 1
                elif dim == 3:
                    info['volumes'] += 1

            # Get bounding box
            try:
                if entities:
                    xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
                    info['bounding_box'] = {
                        'min': (xmin, ymin, zmin),
                        'max': (xmax, ymax, zmax),
                        'size': (xmax - xmin, ymax - ymin, zmax - zmin),
                    }

                    # Estimate unit based on bounding box size
                    max_dim = max(xmax - xmin, ymax - ymin, zmax - zmin)
                    if max_dim > 1000:
                        info['estimated_unit'] = 'MILLIMETERS'
                    elif max_dim > 10:
                        info['estimated_unit'] = 'CENTIMETERS'
                    elif max_dim > 0.1:
                        info['estimated_unit'] = 'METERS'
                    else:
                        info['estimated_unit'] = 'MILLIMETERS'
            except Exception:
                pass

            # Try to get part names from STEP file
            try:
                for dim, tag in entities:
                    name = gmsh.model.getEntityName(dim, tag)
                    if name and name not in info['part_names']:
                        info['part_names'].append(name)
            except Exception:
                pass

            gmsh.finalize()
            return info

        except Exception as e:
            logger.debug(f"Error getting model info: {e}")
            try:
                import gmsh
                gmsh.finalize()
            except Exception:
                pass
            return info

    @classmethod
    def convert_to_stl(
        cls,
        input_path: Path,
        output_path: Path,
        mesh_size_min: float = 0.1,
        mesh_size_max: float = 10.0,
        mesh_algorithm: int = 6,
        optimize_mesh: bool = True,
        healing: bool = True,
    ) -> Tuple[bool, str, List[str]]:
        """
        Convert CAD file to STL using gmsh.

        Returns: (success, message, part_names)
        """
        if not cls.is_available():
            return False, "gmsh is not installed", []

        part_names: List[str] = []

        try:
            import gmsh

            gmsh.initialize()
            gmsh.option.setNumber("General.Terminal", 0)

            gmsh.model.add("cad_import")

            file_ext = input_path.suffix.lower()
            try:
                if file_ext in (".step", ".stp", ".iges", ".igs", ".brep", ".brp"):
                    if healing:
                        gmsh.option.setNumber("Geometry.OCCFixDegenerated", 1)
                        gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 1)
                        gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 1)
                        gmsh.option.setNumber("Geometry.OCCSewFaces", 1)

                    gmsh.model.occ.importShapes(str(input_path))
                    gmsh.model.occ.synchronize()
                else:
                    gmsh.merge(str(input_path))
            except Exception as e:
                gmsh.finalize()
                return False, f"Failed to import CAD file: {e}", []

            # Extract part names
            try:
                for dim, tag in gmsh.model.getEntities():
                    name = gmsh.model.getEntityName(dim, tag)
                    if name:
                        part_names.append(name)
            except Exception:
                pass

            # Mesh settings
            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size_min)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size_max)
            gmsh.option.setNumber("Mesh.Algorithm", mesh_algorithm)

            if optimize_mesh:
                gmsh.option.setNumber("Mesh.Optimize", 1)
                gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)

            # Generate 2D surface mesh
            try:
                gmsh.model.mesh.generate(2)
            except Exception as e:
                gmsh.finalize()
                return False, f"Failed to generate mesh: {e}", []

            # Export to STL
            try:
                gmsh.write(str(output_path))
            except Exception as e:
                gmsh.finalize()
                return False, f"Failed to write STL: {e}", []

            gmsh.finalize()
            return True, "Conversion successful", part_names

        except Exception as e:
            try:
                import gmsh
                gmsh.finalize()
            except Exception:
                pass
            return False, f"Conversion error: {e}", []


# =============================================================================
# Mesh Quality Presets
# =============================================================================

MESH_QUALITY_PRESETS: Dict[str, Tuple[float, float]] = {
    'VERY_COARSE': (1.0, 50.0),
    'COARSE': (0.5, 20.0),
    'NORMAL': (0.1, 10.0),
    'FINE': (0.05, 5.0),
    'VERY_FINE': (0.01, 1.0),
}

MESH_ALGORITHMS: List[Tuple[str, str, str, int]] = [
    ('1', "MeshAdapt", "Automatic mesh adaptation", 1),
    ('2', "Automatic", "Automatic selection", 2),
    ('5', "Delaunay", "Delaunay triangulation", 5),
    ('6', "Frontal-Delaunay", "Frontal-Delaunay (default)", 6),
    ('7', "BAMG", "Bidimensional Anisotropic Mesh Generator", 7),
    ('8', "Frontal-Delaunay Quads", "Frontal-Delaunay for quads", 8),
    ('9', "Packing of Parallelograms", "Packing of parallelograms", 9),
]


# =============================================================================
# Import Presets
# =============================================================================

class LADDER_MT_import_presets(bpy.types.Menu):
    """Ladder import presets menu."""
    bl_idname = "LADDER_MT_import_presets"
    bl_label = "Import Presets"
    preset_subdir = "ladder"
    preset_operator = "script.execute_preset"
    draw = bpy.types.Menu.draw_preset


class LADDER_OT_add_import_preset(bpy.types.Operator):
    """Add a Ladder import preset."""
    bl_idname = "ladder.add_import_preset"
    bl_label = "Add Import Preset"
    preset_menu = "LADDER_MT_import_presets"

    preset_defines = [
        "op = bpy.context.active_operator"
    ]

    preset_values = [
        "op.mesh_quality",
        "op.mesh_size_min",
        "op.mesh_size_max",
        "op.mesh_algorithm",
        "op.source_unit",
        "op.global_scale",
        "op.import_to_collection",
        "op.collection_name",
        "op.smooth_shading",
        "op.recalc_normals",
        "op.merge_distance",
        "op.apply_transform",
        "op.set_origin",
    ]

    preset_subdir = "ladder"

    # Required by AddPresetBase
    name: StringProperty(
        name="Name",
        description="Preset name",
        default=""
    )

    remove_active: BoolProperty(
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    def execute(self, context: bpy.types.Context) -> Set[str]:
        import os
        from bpy.types import OperatorFileListElement

        preset_menu_class = getattr(bpy.types, self.preset_menu)
        preset_subdir = preset_menu_class.preset_subdir

        preset_base_path = bpy.utils.user_resource('SCRIPTS', path="presets")
        preset_path = os.path.join(preset_base_path, preset_subdir)

        if not os.path.exists(preset_path):
            os.makedirs(preset_path)

        if self.remove_active:
            # Find and remove active preset
            pass
        else:
            # Add new preset
            if not self.name:
                return {'CANCELLED'}

            filename = f"{self.name}.py"
            filepath = os.path.join(preset_path, filename)

            with open(filepath, 'w') as f:
                f.write("import bpy\n")
                for define in self.preset_defines:
                    f.write(f"{define}\n")
                f.write("\n")

                op = context.active_operator
                for value in self.preset_values:
                    prop_name = value.split(".")[-1]
                    prop_value = getattr(op, prop_name, None)
                    if prop_value is not None:
                        if isinstance(prop_value, str):
                            f.write(f"{value} = '{prop_value}'\n")
                        else:
                            f.write(f"{value} = {prop_value!r}\n")

        return {'FINISHED'}

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> Set[str]:
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(self, "name")


# =============================================================================
# Preferences
# =============================================================================

def get_preferences() -> "LadderPreferences":
    """Get addon preferences."""
    return bpy.context.preferences.addons[__package__].preferences


@persistent
def reset_show_options_handler(dummy: Any) -> None:
    """Reset show_options on file load."""
    try:
        get_preferences().show_options = True
    except Exception:
        pass


class LadderPreferences(bpy.types.AddonPreferences):
    """Ladder addon preferences."""
    bl_idname = __package__

    show_options: BoolProperty(
        name="Show Options Before Import",
        description="Display options panel before each import",
        default=True,
        options={'HIDDEN'}
    )

    last_import_directory: StringProperty(
        name="Last Import Directory",
        description="Remember the last directory used for importing",
        default="",
        subtype='DIR_PATH',
        options={'HIDDEN'}
    )

    # Default mesh settings
    mesh_quality: EnumProperty(
        name="Mesh Quality",
        description="Controls mesh density. Finer = more polygons",
        items=[
            ('VERY_COARSE', "Very Coarse", "Fastest, fewest polygons"),
            ('COARSE', "Coarse", "Fast, low detail"),
            ('NORMAL', "Normal", "Balanced quality"),
            ('FINE', "Fine", "High detail"),
            ('VERY_FINE', "Very Fine", "Highest detail, slowest"),
            ('CUSTOM', "Custom", "Set custom mesh size values"),
        ],
        default='NORMAL',
    )

    mesh_size_min: FloatProperty(
        name="Min Mesh Size",
        description="Minimum mesh element size",
        default=0.1,
        min=0.001,
        max=100.0,
        step=1,
        precision=3,
    )

    mesh_size_max: FloatProperty(
        name="Max Mesh Size",
        description="Maximum mesh element size",
        default=10.0,
        min=0.01,
        max=1000.0,
        step=10,
        precision=2,
    )

    # Default import settings
    global_scale: EnumProperty(
        name="Scale",
        description="Scale factor for imported objects",
        items=[
            ("1000", "1000x (mm → m)", "Convert millimeters to meters"),
            ("100", "100x", "Scale by 100"),
            ("10", "10x", "Scale by 10"),
            ("1", "1x (No scaling)", "Keep original size"),
            ("0.1", "0.1x", "Scale by 0.1"),
            ("0.01", "0.01x", "Scale by 0.01"),
            ("0.001", "0.001x (m → mm)", "Convert meters to millimeters"),
        ],
        default="1",
    )

    import_to_collection: BoolProperty(
        name="Import to Collection",
        description="Create a new collection for imported objects",
        default=False,
    )

    smooth_shading: BoolProperty(
        name="Smooth Shading",
        description="Apply smooth shading to imported meshes",
        default=False,
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout

        # gmsh status
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Conversion Backend:", icon='PREFERENCES')

        gmsh_ok = GmshManager.is_available()

        if gmsh_ok:
            col.label(text=f"gmsh {GmshManager.get_version()} installed", icon='CHECKMARK')
        else:
            col.label(text="gmsh is not installed", icon='ERROR')
            col.operator("ladder.install_gmsh", text="Install gmsh", icon='IMPORT')

        # Default settings
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Default Import Settings:", icon='IMPORT')
        col.prop(self, "mesh_quality")
        if self.mesh_quality == 'CUSTOM':
            col.prop(self, "mesh_size_min")
            col.prop(self, "mesh_size_max")
        col.prop(self, "global_scale")
        col.separator()
        col.prop(self, "import_to_collection")
        col.prop(self, "smooth_shading")
        col.prop(self, "show_options")

        # Supported formats
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Supported Formats:", icon='FILE_3D')
        col.label(text="STEP (.step, .stp) - ISO 10303 standard")
        col.label(text="IGES (.iges, .igs) - Initial Graphics Exchange")
        col.label(text="BREP (.brep, .brp) - OpenCASCADE boundary rep")


# =============================================================================
# Import Progress State
# =============================================================================

class ImportProgress:
    """Track multi-file import progress."""

    def __init__(self):
        self.total_files: int = 0
        self.current_file: int = 0
        self.current_filename: str = ""
        self.phase: str = ""
        self.is_running: bool = False
        self.was_cancelled: bool = False

    def start(self, total: int) -> None:
        self.total_files = total
        self.current_file = 0
        self.current_filename = ""
        self.phase = ""
        self.is_running = True
        self.was_cancelled = False

    def update(self, file_index: int, filename: str, phase: str) -> None:
        self.current_file = file_index
        self.current_filename = filename
        self.phase = phase

    def stop(self) -> None:
        self.is_running = False

    def cancel(self) -> None:
        self.was_cancelled = True
        self.is_running = False

    @property
    def progress_percent(self) -> float:
        if self.total_files == 0:
            return 0.0
        base = (self.current_file / self.total_files) * 100
        if self.phase == "converting":
            base += (0.5 / self.total_files) * 100
        return min(base, 100.0)

    @property
    def status_text(self) -> str:
        if not self.is_running:
            return ""
        phase_text = "Converting" if self.phase == "converting" else "Importing"
        return f"Ladder: {phase_text} {self.current_filename} ({self.current_file + 1}/{self.total_files})"


import_progress = ImportProgress()


# =============================================================================
# Operators
# =============================================================================

class LADDER_OT_install_gmsh(bpy.types.Operator):
    """Install gmsh Python package."""
    bl_idname = "ladder.install_gmsh"
    bl_label = "Install gmsh"
    bl_description = "Install gmsh package using pip"

    def execute(self, context: bpy.types.Context) -> Set[str]:
        self.report({'INFO'}, "Installing gmsh... This may take a moment.")

        success, message = GmshManager.install()

        if success:
            self.report({'INFO'}, message)
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


class LADDER_OT_import_cad(bpy.types.Operator, ImportHelper):
    """Import CAD files (STEP, IGES, BREP)."""
    bl_idname = "import_scene.ladder_cad"
    bl_label = "Import CAD (Ladder)"
    bl_description = "Import CAD files using gmsh (supports multiple files)"
    bl_options = {'UNDO', 'PRESET'}

    filter_glob: StringProperty(
        default=EXTENSION_FILTER,
        options={'HIDDEN'},
    )

    directory: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE', 'HIDDEN'})
    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'SKIP_SAVE', 'HIDDEN'}
    )

    # Hidden property to preserve drag-and-drop paths (file browser overwrites 'files' on Import click)
    drop_paths: StringProperty(
        default="",
        options={'HIDDEN', 'SKIP_SAVE'}
    )

    # === Mesh Settings ===
    mesh_quality: EnumProperty(
        name="Mesh Quality",
        description="Controls mesh density",
        items=[
            ('VERY_COARSE', "Very Coarse", "Fastest, fewest polygons"),
            ('COARSE', "Coarse", "Fast, low detail"),
            ('NORMAL', "Normal", "Balanced quality"),
            ('FINE', "Fine", "High detail"),
            ('VERY_FINE', "Very Fine", "Highest detail, slowest"),
            ('CUSTOM', "Custom", "Set custom mesh size values"),
        ],
        default='NORMAL',
    )

    mesh_size_min: FloatProperty(
        name="Min Mesh Size",
        description="Minimum mesh element size",
        default=0.1,
        min=0.001,
        max=100.0,
    )

    mesh_size_max: FloatProperty(
        name="Max Mesh Size",
        description="Maximum mesh element size",
        default=10.0,
        min=0.01,
        max=1000.0,
    )

    mesh_algorithm: EnumProperty(
        name="Algorithm",
        description="Meshing algorithm to use",
        items=[(a[0], a[1], a[2]) for a in MESH_ALGORITHMS],
        default='2',
    )

    optimize_mesh: BoolProperty(
        name="Optimize Mesh",
        description="Optimize mesh quality after generation",
        default=False,
    )

    healing: BoolProperty(
        name="Geometry Healing",
        description="Attempt to fix geometry issues (degenerated edges, small faces)",
        default=False,
    )

    # === Unit / Scale Settings ===
    source_unit: EnumProperty(
        name="Source Unit",
        description="Unit of the CAD file (auto-detected if possible)",
        items=[
            ('AUTO', "Auto Detect", "Attempt to detect unit from file"),
            ('MICROMETERS', "Micrometers", "Source is in micrometers"),
            ('MILLIMETERS', "Millimeters", "Source is in millimeters"),
            ('CENTIMETERS', "Centimeters", "Source is in centimeters"),
            ('METERS', "Meters", "Source is in meters"),
            ('INCHES', "Inches", "Source is in inches"),
            ('FEET', "Feet", "Source is in feet"),
        ],
        default='AUTO',
    )

    global_scale: EnumProperty(
        name="Scale",
        description="Additional scale factor for imported objects",
        items=[
            ("1000", "1000x", "Scale by 1000"),
            ("100", "100x", "Scale by 100"),
            ("10", "10x", "Scale by 10"),
            ("1", "1x (No scaling)", "Keep original size"),
            ("0.1", "0.1x", "Scale by 0.1"),
            ("0.01", "0.01x", "Scale by 0.01"),
            ("0.001", "0.001x", "Scale by 0.001"),
        ],
        default="1",
    )

    # === Organization ===
    import_to_collection: BoolProperty(
        name="Import to Collection",
        description="Create a new collection for imported objects",
        default=False,
    )

    collection_name: StringProperty(
        name="Collection Name",
        description="Name for the import collection (empty = use filename)",
        default="",
    )

    use_part_names: BoolProperty(
        name="Use Part Names",
        description="Try to preserve part names from CAD file",
        default=False,
    )

    # === Geometry Processing ===
    smooth_shading: BoolProperty(
        name="Smooth Shading",
        description="Apply smooth shading to imported meshes",
        default=False,
    )

    recalc_normals: BoolProperty(
        name="Recalculate Normals",
        description="Recalculate normals to ensure they point outward",
        default=False,
    )

    merge_distance: FloatProperty(
        name="Merge Distance",
        description="Merge vertices within this distance (0 = disabled)",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=6,
    )

    apply_transform: BoolProperty(
        name="Apply Transform",
        description="Apply scale and rotation transforms after import",
        default=False,
    )

    set_origin: EnumProperty(
        name="Set Origin",
        description="Set origin point for imported objects",
        items=[
            ('NONE', "Don't Change", "Keep origin from file"),
            ('GEOMETRY', "Geometry Center", "Set origin to geometry center"),
            ('BOUNDS', "Bounds Center", "Set origin to bounding box center"),
            ('CURSOR', "3D Cursor", "Set origin to 3D cursor"),
            ('WORLD', "World Origin", "Set origin to world origin"),
        ],
        default='NONE',
    )

    # === Internal State ===
    _timer: Optional[bpy.types.Timer] = None
    _files_to_process: List[Path] = []
    _current_index: int = 0
    _temp_files: List[Path] = []
    _all_imported_objects: List[bpy.types.Object] = []
    _start_time: float = 0
    _mesh_min: float = 0.1
    _mesh_max: float = 10.0
    _target_collection: Optional[bpy.types.Collection] = None

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        # Check gmsh status
        if not GmshManager.is_available():
            box = layout.box()
            box.alert = True
            box.label(text="gmsh not installed!", icon='ERROR')
            box.operator("ladder.install_gmsh", text="Install gmsh")
            layout.separator()

        # File count info
        if self.files and len(self.files) > 1:
            box = layout.box()
            box.label(text=f"Selected: {len(self.files)} files", icon='FILE_FOLDER')

        # Presets
        row = layout.row(align=True)
        row.menu(LADDER_MT_import_presets.__name__, text="", icon='PRESET')
        row.operator(LADDER_OT_add_import_preset.bl_idname, text="", icon='ADD')

        # Mesh Settings
        header, panel = layout.panel("LADDER_mesh_settings", default_closed=False)
        header.label(text="Mesh Settings", icon='MESH_DATA')
        if panel:
            panel.prop(self, "mesh_quality")
            if self.mesh_quality == 'CUSTOM':
                panel.prop(self, "mesh_size_min")
                panel.prop(self, "mesh_size_max")
            panel.prop(self, "mesh_algorithm")
            panel.prop(self, "optimize_mesh")
            panel.prop(self, "healing")

        # Unit / Scale
        header, panel = layout.panel("LADDER_unit_settings", default_closed=False)
        header.label(text="Units & Scale", icon='DRIVER_DISTANCE')
        if panel:
            panel.prop(self, "source_unit")
            panel.prop(self, "global_scale")

        # Organization
        header, panel = layout.panel("LADDER_organization", default_closed=False)
        header.label(text="Organization", icon='OUTLINER_COLLECTION')
        if panel:
            panel.prop(self, "import_to_collection")
            if self.import_to_collection:
                panel.prop(self, "collection_name")
            panel.prop(self, "use_part_names")

        # Geometry Processing
        header, panel = layout.panel("LADDER_geometry", default_closed=True)
        header.label(text="Geometry Processing", icon='MOD_SMOOTH')
        if panel:
            panel.prop(self, "smooth_shading")
            panel.prop(self, "recalc_normals")
            panel.prop(self, "merge_distance")
            panel.prop(self, "apply_transform")
            panel.prop(self, "set_origin")

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event) -> Set[str]:
        prefs = get_preferences()
        self.mesh_quality = prefs.mesh_quality
        self.mesh_size_min = prefs.mesh_size_min
        self.mesh_size_max = prefs.mesh_size_max
        self.global_scale = prefs.global_scale
        self.import_to_collection = prefs.import_to_collection
        self.smooth_shading = prefs.smooth_shading

        if prefs.last_import_directory and os.path.isdir(prefs.last_import_directory):
            self.directory = prefs.last_import_directory

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context: bpy.types.Context) -> Set[str]:
        if not GmshManager.is_available():
            self.report({'ERROR'}, "gmsh is not installed. Click 'Install gmsh' in addon preferences.")
            return {'CANCELLED'}

        prefs = get_preferences()
        if self.directory:
            prefs.last_import_directory = self.directory

        # Gather files - prioritize drop_paths (drag-and-drop preserves full paths here
        # because file browser overwrites self.files on Import click)
        if self.drop_paths:
            self._files_to_process = [
                Path(p) for p in self.drop_paths.split(";")
                if p and Path(p).suffix.lower() in SUPPORTED_EXTENSIONS
            ]
        elif self.files and any(f.name for f in self.files):
            self._files_to_process = [
                Path(self.directory) / f.name
                for f in self.files
                if f.name and Path(self.directory, f.name).suffix.lower() in SUPPORTED_EXTENSIONS
            ]
        elif self.filepath:
            self._files_to_process = [Path(self.filepath)]
        else:
            self._files_to_process = []

        self._files_to_process = [f for f in self._files_to_process if f.exists()]

        if not self._files_to_process:
            self.report({'ERROR'}, "No valid CAD files selected")
            return {'CANCELLED'}

        # Get mesh size
        if self.mesh_quality == 'CUSTOM':
            self._mesh_min = self.mesh_size_min
            self._mesh_max = self.mesh_size_max
        else:
            self._mesh_min, self._mesh_max = MESH_QUALITY_PRESETS.get(
                self.mesh_quality,
                MESH_QUALITY_PRESETS['NORMAL']
            )

        # Create target collection if needed
        self._target_collection = None
        if self.import_to_collection:
            coll_name = self.collection_name or self._files_to_process[0].stem
            if len(self._files_to_process) > 1 and not self.collection_name:
                coll_name = "CAD Import"
            self._target_collection = bpy.data.collections.new(coll_name)
            context.scene.collection.children.link(self._target_collection)

        # Initialize
        self._current_index = 0
        self._temp_files = []
        self._all_imported_objects = []
        self._start_time = time.time()

        import_progress.start(len(self._files_to_process))

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> Set[str]:
        if event.type == 'ESC':
            return self._finish(context, cancelled=True)

        if event.type == 'TIMER':
            if self._current_index >= len(self._files_to_process):
                return self._finish(context, cancelled=False)

            result = self._process_current_file(context)
            if result == 'ERROR':
                pass

            self._current_index += 1

            progress = (self._current_index / len(self._files_to_process)) * 100
            context.window_manager.progress_update(progress)
            context.workspace.status_text_set(import_progress.status_text)

        return {'RUNNING_MODAL'}

    def _process_current_file(self, context: bpy.types.Context) -> str:
        """Process a single file."""
        input_path = self._files_to_process[self._current_index]

        import_progress.update(self._current_index, input_path.name, "converting")
        context.workspace.status_text_set(import_progress.status_text)

        # Create temp file
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".stl")
            os.close(fd)
            output_path = Path(temp_path)
            self._temp_files.append(output_path)
        except Exception as e:
            logger.error(f"Failed to create temp file: {e}")
            return 'ERROR'

        # Determine scale based on source unit
        unit_scale = 1.0
        if self.source_unit == 'AUTO':
            info = GmshManager.get_model_info(input_path)
            detected_unit = info.get('estimated_unit', 'MILLIMETERS')
            if detected_unit in UNIT_SCALES:
                unit_scale = UNIT_SCALES[detected_unit]
        elif self.source_unit in UNIT_SCALES:
            unit_scale = UNIT_SCALES[self.source_unit]

        # Convert CAD to STL
        success, message, part_names = GmshManager.convert_to_stl(
            input_path,
            output_path,
            mesh_size_min=self._mesh_min,
            mesh_size_max=self._mesh_max,
            mesh_algorithm=int(self.mesh_algorithm),
            optimize_mesh=self.optimize_mesh,
            healing=self.healing,
        )

        if not success:
            logger.error(f"Conversion failed for {input_path}: {message}")
            self.report({'WARNING'}, f"Failed to convert {input_path.name}: {message}")
            return 'ERROR'

        if not output_path.exists():
            logger.error(f"No output produced for {input_path}")
            return 'ERROR'

        # Import phase
        import_progress.update(self._current_index, input_path.name, "importing")
        context.workspace.status_text_set(import_progress.status_text)

        before_objects = set(bpy.data.objects)

        # Calculate final scale
        final_scale = float(self.global_scale) * unit_scale

        try:
            bpy.ops.wm.stl_import(
                filepath=str(output_path),
                global_scale=final_scale,
            )
        except Exception as e:
            logger.error(f"Import failed for {input_path}: {e}")
            return 'ERROR'

        new_objects = [obj for obj in bpy.data.objects if obj not in before_objects]

        if not new_objects:
            return 'ERROR'

        # Rename objects
        base_name = input_path.stem
        if self.use_part_names and part_names:
            for i, obj in enumerate(new_objects):
                if i < len(part_names):
                    # Clean part name
                    clean_name = re.sub(r'[^\w\-_]', '_', part_names[i])
                    obj.name = clean_name
                    if obj.data:
                        obj.data.name = clean_name
                else:
                    obj.name = f"{base_name}_{i:03d}"
                    if obj.data:
                        obj.data.name = f"{base_name}_{i:03d}"
        elif len(new_objects) == 1:
            new_objects[0].name = base_name
            if new_objects[0].data:
                new_objects[0].data.name = base_name
        else:
            for i, obj in enumerate(new_objects):
                obj.name = f"{base_name}_{i:03d}"
                if obj.data:
                    obj.data.name = f"{base_name}_{i:03d}"

        # Move to collection
        if self._target_collection:
            for obj in new_objects:
                for coll in obj.users_collection:
                    coll.objects.unlink(obj)
                self._target_collection.objects.link(obj)

        # Post-processing
        for obj in new_objects:
            if obj.type != 'MESH':
                continue

            # Select and make active for operations
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            # Smooth shading
            if self.smooth_shading:
                bpy.ops.object.shade_smooth()

            # Merge vertices
            if self.merge_distance > 0:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.remove_doubles(threshold=self.merge_distance)
                bpy.ops.object.mode_set(mode='OBJECT')

            # Recalculate normals
            if self.recalc_normals:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.normals_make_consistent(inside=False)
                bpy.ops.object.mode_set(mode='OBJECT')

            # Apply transforms
            if self.apply_transform:
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

            # Set origin
            if self.set_origin == 'GEOMETRY':
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')
            elif self.set_origin == 'BOUNDS':
                bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
            elif self.set_origin == 'CURSOR':
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
            elif self.set_origin == 'WORLD':
                saved_cursor = context.scene.cursor.location.copy()
                context.scene.cursor.location = (0, 0, 0)
                bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
                context.scene.cursor.location = saved_cursor

        self._all_imported_objects.extend(new_objects)
        return 'OK'

    def _finish(self, context: bpy.types.Context, cancelled: bool) -> Set[str]:
        """Clean up and finish."""
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None

        context.window_manager.progress_end()
        context.workspace.status_text_set(None)
        import_progress.stop()

        # Cleanup temp files
        for temp_path in self._temp_files:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
        self._temp_files.clear()

        if cancelled:
            import_progress.cancel()
            # Remove empty collection if cancelled
            if self._target_collection and len(self._target_collection.objects) == 0:
                bpy.data.collections.remove(self._target_collection)
            self.report({'INFO'}, "Import cancelled")
            return {'CANCELLED'}

        # Select all imported objects
        bpy.ops.object.select_all(action='DESELECT')
        for obj in self._all_imported_objects:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if self._all_imported_objects:
            context.view_layer.objects.active = self._all_imported_objects[0]

        # Frame view
        try:
            if context.space_data and hasattr(context.space_data, 'region_3d'):
                if context.space_data.region_3d.view_perspective != 'CAMERA':
                    bpy.ops.view3d.view_selected(use_all_regions=False)
        except Exception:
            pass

        elapsed = time.time() - self._start_time
        obj_count = len(self._all_imported_objects)
        file_count = len(self._files_to_process)

        if file_count == 1:
            self.report({'INFO'}, f"Imported {obj_count} object(s) in {elapsed:.2f}s")
        else:
            self.report({'INFO'}, f"Imported {obj_count} object(s) from {file_count} files in {elapsed:.2f}s")

        return {'FINISHED'}


class LADDER_FH_cad(bpy.types.FileHandler):
    """File handler for drag-and-drop CAD import."""
    bl_idname = "LADDER_FH_cad"
    bl_label = "CAD Files"
    bl_import_operator = "import_scene.ladder_cad"
    bl_file_extensions = ";".join(SUPPORTED_EXTENSIONS)

    @classmethod
    def poll_drop(cls, context: bpy.types.Context) -> bool:
        return poll_file_object_drop(context)

    def files_drop(self, context, paths):
        """Handle multi-file drag-and-drop."""
        if not paths:
            return {'CANCELLED'}

        # Filter to supported extensions
        valid_paths = [p for p in paths if Path(p).suffix.lower() in SUPPORTED_EXTENSIONS]
        if not valid_paths:
            return {'CANCELLED'}

        dir_path = os.path.dirname(valid_paths[0])
        file_names = [{"name": os.path.basename(p)} for p in valid_paths]

        # Store full paths in drop_paths - this survives the file browser
        # overwriting self.files when user clicks Import
        drop_paths_str = ";".join(valid_paths)

        return bpy.ops.import_scene.ladder_cad(
            'INVOKE_DEFAULT',
            directory=dir_path,
            files=file_names,
            drop_paths=drop_paths_str,
        )


# =============================================================================
# UI Panel for File Browser - File Info
# =============================================================================

class LADDER_PT_file_info(bpy.types.Panel):
    """Panel showing file info in file browser."""
    bl_idname = "LADDER_PT_file_info"
    bl_label = "CAD File Info"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOL_PROPS'
    bl_parent_id = "FILE_PT_operator"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        operator = context.space_data.active_operator
        return operator and operator.bl_idname == "IMPORT_SCENE_OT_ladder_cad"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        space = context.space_data
        params = space.params

        selected_file = None
        if hasattr(params, 'filename') and params.filename:
            selected_file = Path(params.directory) / params.filename

        if selected_file and selected_file.exists():
            ext = selected_file.suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                col = layout.column(align=True)

                # File info
                col.label(text=f"File: {selected_file.name}")

                try:
                    size_bytes = selected_file.stat().st_size
                    if size_bytes < 1024:
                        size_str = f"{size_bytes} B"
                    elif size_bytes < 1024 * 1024:
                        size_str = f"{size_bytes / 1024:.1f} KB"
                    else:
                        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                    col.label(text=f"Size: {size_str}")
                except Exception:
                    pass

                format_names = {
                    ".step": "STEP (ISO 10303)",
                    ".stp": "STEP (ISO 10303)",
                    ".iges": "IGES",
                    ".igs": "IGES",
                    ".brep": "BREP (OpenCASCADE)",
                    ".brp": "BREP (OpenCASCADE)",
                }
                col.label(text=f"Format: {format_names.get(ext, ext.upper())}")
        else:
            layout.label(text="Select a CAD file")


# =============================================================================
# Registration
# =============================================================================

def menu_func_import(self: Any, context: bpy.types.Context) -> None:
    self.layout.operator(
        LADDER_OT_import_cad.bl_idname,
        text="CAD Files (.step, .iges, .brep)"
    )


classes = (
    LADDER_MT_import_presets,
    LADDER_OT_add_import_preset,
    LadderPreferences,
    LADDER_OT_install_gmsh,
    LADDER_OT_import_cad,
    LADDER_FH_cad,
    LADDER_PT_file_info,
)


def register() -> None:
    if bpy.app.version < (4, 0, 0):
        logger.error("Ladder requires Blender 4.0 or later")
        return

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.app.handlers.load_post.append(reset_show_options_handler)

    # Create presets directory
    preset_path = bpy.utils.user_resource('SCRIPTS', path="presets/ladder", create=True)

    if GmshManager.is_available():
        logger.info(f"Ladder v{'.'.join(map(str, bl_info['version']))} ready with gmsh {GmshManager.get_version()}")
    else:
        logger.info(f"Ladder v{'.'.join(map(str, bl_info['version']))} loaded - gmsh needs to be installed")


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.app.handlers.load_post.remove(reset_show_options_handler)

    logger.info("Ladder addon unregistered")


if __name__ == "__main__":
    register()
