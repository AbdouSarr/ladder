
<img width="100" height="90" alt="Screenshot 2025-12-02 at 11 57 29" src="https://github.com/user-attachments/assets/591c7a88-62d7-44e9-bf33-7bb0e76a7cfa" />

# ladder

**CAD Import for Blender** — Import STEP, IGES, and BREP files directly into Blender 4.0+

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Blender](https://img.shields.io/badge/Blender-4.0%2B-orange.svg)](https://www.blender.org)

<!-- TODO: Add hero image/GIF showing import in action -->
<!-- ![Ladder Demo](docs/images/demo.gif) -->


## Features

- **One-Click Setup** — Install gmsh dependency directly from Blender preferences
- **Multiple CAD Formats** — STEP (.step, .stp), IGES (.iges, .igs), BREP (.brep, .brp)
- **Batch Import** — Import multiple files at once with progress tracking
- **Drag & Drop** — Drop CAD files directly into the 3D viewport
- **Quality Presets** — From "Very Coarse" (fast) to "Very Fine" (detailed)
- **Unit Detection** — Auto-detect source units and scale appropriately
- **Part Names** — Preserve part names from CAD assemblies
- **Smart Organization** — Auto-create collections for imported files
- **Geometry Processing** — Smooth shading, normal recalculation, vertex merging
- **Import Presets** — Save and reuse your favorite import settings

## Installation

![Installation](https://github.com/user-attachments/assets/5be18bc9-b720-453f-a278-ce7143eff954)

### Method 1: Download Release (Recommended)

1. Download the latest release from [Releases](https://github.com/abdousarr/ladder/releases)
2. In Blender, go to **Edit → Preferences → Add-ons**
3. Click **Install...** and select the downloaded `.zip` file
4. Enable the "Ladder" add-on
5. Click **Install gmsh** in the add-on preferences

### Method 2: Manual Installation

1. Clone or download this repository
2. Copy the `ladder` folder to your Blender addons directory:
   - **Windows:** `%APPDATA%\Blender Foundation\Blender\4.x\scripts\addons\`
   - **macOS:** `~/Library/Application Support/Blender/4.x/scripts/addons/`
   - **Linux:** `~/.config/blender/4.x/scripts/addons/`
3. Enable the add-on in Blender preferences
4. Click **Install gmsh** in the add-on preferences

## Usage

![Menu Import](https://github.com/user-attachments/assets/59193151-12aa-464e-af95-21740772daf5)

### Import via Menu

1. Go to **File → Import → CAD Files (.step, .iges, .brep)**
2. Select one or more CAD files
3. Adjust import settings in the sidebar
4. Click **Import CAD**

### Drag & Drop

Simply drag CAD files from your file manager directly into Blender's 3D viewport.

## Import Options

### Mesh Settings

| Option | Description |
|--------|-------------|
| **Mesh Quality** | Preset quality levels from Very Coarse to Very Fine |
| **Min/Max Mesh Size** | Custom mesh element sizes (when Quality = Custom) |
| **Algorithm** | Meshing algorithm (Frontal-Delaunay recommended) |
| **Optimize Mesh** | Post-process mesh for better quality |
| **Geometry Healing** | Fix degenerated edges and small faces |

### Units & Scale

| Option | Description |
|--------|-------------|
| **Source Unit** | Unit of CAD file (Auto, mm, cm, m, inches, feet) |
| **Scale** | Additional scale factor (1x = no change) |

### Organization

| Option | Description |
|--------|-------------|
| **Import to Collection** | Create a new collection for imports |
| **Collection Name** | Custom name (empty = use filename) |
| **Use Part Names** | Preserve part names from CAD file |

### Geometry Processing

| Option | Description |
|--------|-------------|
| **Smooth Shading** | Apply smooth shading to meshes |
| **Recalculate Normals** | Ensure normals point outward |
| **Merge Distance** | Merge nearby vertices (0 = disabled) |
| **Apply Transform** | Apply scale/rotation transforms |
| **Set Origin** | Set object origin (geometry center, bounds, etc.) |

## Supported Formats

| Format | Extensions | Description |
|--------|------------|-------------|
| **STEP** | `.step`, `.stp` | ISO 10303 standard, most widely supported |
| **IGES** | `.iges`, `.igs` | Initial Graphics Exchange Specification |
| **BREP** | `.brep`, `.brp` | OpenCASCADE boundary representation |

## Requirements

- **Blender 4.0** or later
- **gmsh** Python package (installed automatically via add-on preferences)

## Troubleshooting

### "gmsh is not installed"

Click the **Install gmsh** button in the add-on preferences.

### Import is slow

- Use a coarser mesh quality preset
- Disable "Optimize Mesh" for faster (but lower quality) results
- Large assemblies with many parts take longer to process

### Model looks wrong after import

- Try different **Source Unit** settings
- Enable **Geometry Healing** to fix CAD issues
- Enable **Recalculate Normals** if faces appear inverted

### Parts are not named correctly

- Enable **Use Part Names** in import options
- Note: Not all CAD files contain part name metadata

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [gmsh](https://gmsh.info/) — The excellent open-source mesh generator that powers this add-on
- [OpenCASCADE](https://www.opencascade.com/) — The CAD kernel used by gmsh for STEP/IGES support
- The Blender / Blender add-on community for inspiration and feedback

## Changelog

### v1.0.0

- Initial public release
- STEP, IGES, and BREP import support
- Multi-file batch import with progress bar
- Mesh quality presets (Very Coarse to Very Fine)
- Auto unit detection
- Part name preservation
- Collection organization
- Geometry processing options (smooth shading, normals, merge vertices)
- Import presets system
- Drag & drop support
- One-click gmsh installation
