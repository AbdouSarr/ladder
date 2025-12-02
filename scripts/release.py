#!/usr/bin/env python3
"""
Ladder Release Script

This script automates the release process for the Ladder addon:
- Updates version numbers
- Updates changelog
- Runs tests
- Creates release zip file
- Optionally creates git tag

Usage:
    python scripts/release.py 1.1.0 --changelog "Added new feature X"
    python scripts/release.py 1.1.0 --changelog "Bug fixes" --tag
    python scripts/release.py --check  # Dry run, show what would change
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
ADDON_DIR = PROJECT_DIR / "ladder"
INIT_FILE = ADDON_DIR / "__init__.py"
README_FILE = PROJECT_DIR / "README.md"
DIST_DIR = PROJECT_DIR / "dist"
TESTS_DIR = PROJECT_DIR / "tests"


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """Parse version string into tuple."""
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)$', version_str)
    if not match:
        raise ValueError(f"Invalid version format: {version_str}. Expected X.Y.Z")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def get_current_version() -> str:
    """Get current version from __init__.py."""
    content = INIT_FILE.read_text()
    match = re.search(r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)', content)
    if match:
        return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"
    raise ValueError("Could not find version in __init__.py")


def update_version_in_init(new_version: str) -> None:
    """Update version in __init__.py."""
    major, minor, patch = parse_version(new_version)

    content = INIT_FILE.read_text()

    # Update version tuple
    content = re.sub(
        r'"version":\s*\(\d+,\s*\d+,\s*\d+\)',
        f'"version": ({major}, {minor}, {patch})',
        content
    )

    INIT_FILE.write_text(content)
    print(f"  Updated __init__.py version to {new_version}")


def update_changelog_in_readme(version: str, changelog: str) -> None:
    """Add changelog entry to README.md."""
    content = README_FILE.read_text()

    # Find the Changelog section
    changelog_marker = "## Changelog"
    if changelog_marker not in content:
        print("  Warning: No Changelog section found in README.md")
        return

    # Format the new changelog entry
    date_str = datetime.now().strftime("%Y-%m-%d")
    new_entry = f"\n### v{version} ({date_str})\n\n{changelog}\n"

    # Insert after the Changelog header
    parts = content.split(changelog_marker)
    if len(parts) == 2:
        # Find the first ### after Changelog and insert before it
        rest = parts[1]
        match = re.search(r'\n(### v\d+)', rest)
        if match:
            insert_pos = match.start()
            new_rest = rest[:insert_pos] + new_entry + rest[insert_pos:]
        else:
            new_rest = new_entry + rest

        content = parts[0] + changelog_marker + new_rest
        README_FILE.write_text(content)
        print(f"  Added changelog entry for v{version}")
    else:
        print("  Warning: Could not parse Changelog section")


def run_tests(blender_path: Optional[str] = None) -> bool:
    """Run the test suite."""
    print("\nRunning tests...")

    test_file = TESTS_DIR / "test_ladder.py"
    if not test_file.exists():
        print("  Warning: Test file not found, skipping tests")
        return True

    if blender_path:
        # Run with Blender
        cmd = [blender_path, "--background", "--python", str(test_file)]
    else:
        # Try to find Blender in PATH
        blender_cmd = shutil.which("blender")
        if blender_cmd:
            cmd = [blender_cmd, "--background", "--python", str(test_file)]
        else:
            # Run standalone (limited tests)
            cmd = [sys.executable, str(test_file)]
            print("  Note: Running standalone tests (Blender not found)")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        print(result.stdout)
        if result.stderr:
            print(result.stderr)

        if result.returncode == 0:
            print("  Tests passed!")
            return True
        else:
            print("  Tests failed!")
            return False
    except subprocess.TimeoutExpired:
        print("  Tests timed out!")
        return False
    except FileNotFoundError:
        print("  Could not run tests (Blender/Python not found)")
        return True  # Don't block release


def create_release_zip(version: str) -> Path:
    """Create release zip file."""
    print("\nCreating release zip...")

    # Create dist directory
    DIST_DIR.mkdir(exist_ok=True)

    # Zip filename
    zip_name = f"ladder-v{version}.zip"
    zip_path = DIST_DIR / zip_name

    # Remove old zip if exists
    if zip_path.exists():
        zip_path.unlink()

    # Files/dirs to exclude from release
    exclude_patterns = {
        '__pycache__',
        '*.pyc',
        '.DS_Store',
    }

    def should_exclude(path: Path) -> bool:
        """Check if path should be excluded."""
        for pattern in exclude_patterns:
            if pattern.startswith('*'):
                if path.name.endswith(pattern[1:]):
                    return True
            elif pattern in path.parts:
                return True
        return False

    # Create zip - package only the ladder/ addon directory
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in ADDON_DIR.rglob('*'):
            if file_path.is_file() and not should_exclude(file_path):
                # Archive path preserves ladder/ directory structure
                arcname = Path('ladder') / file_path.relative_to(ADDON_DIR)
                zf.write(file_path, arcname)
                print(f"  Added: {arcname}")

        # Also include LICENSE and README at root level of zip for reference
        license_file = PROJECT_DIR / "LICENSE"
        readme_file = PROJECT_DIR / "README.md"
        if license_file.exists():
            zf.write(license_file, Path('ladder') / 'LICENSE')
            print(f"  Added: ladder/LICENSE")
        if readme_file.exists():
            zf.write(readme_file, Path('ladder') / 'README.md')
            print(f"  Added: ladder/README.md")

    print(f"\n  Created: {zip_path}")
    print(f"  Size: {zip_path.stat().st_size / 1024:.1f} KB")

    return zip_path


def create_git_tag(version: str, message: str) -> bool:
    """Create and push git tag."""
    print("\nCreating git tag...")

    tag_name = f"v{version}"

    try:
        # Check if tag already exists
        result = subprocess.run(
            ["git", "tag", "-l", tag_name],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR
        )
        if tag_name in result.stdout:
            print(f"  Warning: Tag {tag_name} already exists")
            return False

        # Create annotated tag
        subprocess.run(
            ["git", "tag", "-a", tag_name, "-m", message],
            check=True,
            cwd=PROJECT_DIR
        )
        print(f"  Created tag: {tag_name}")

        # Optionally push tag
        print(f"  To push tag, run: git push origin {tag_name}")

        return True

    except subprocess.CalledProcessError as e:
        print(f"  Error creating tag: {e}")
        return False
    except FileNotFoundError:
        print("  Git not found, skipping tag creation")
        return False


def show_status() -> None:
    """Show current release status."""
    print("\n=== Ladder Release Status ===\n")

    # Current version
    try:
        current = get_current_version()
        print(f"Current version: {current}")
    except Exception as e:
        print(f"Could not read version: {e}")

    # File status
    print(f"\nFiles:")
    print(f"  ladder/__init__.py: {'✓' if INIT_FILE.exists() else '✗'}")
    print(f"  README.md: {'✓' if README_FILE.exists() else '✗'}")
    print(f"  LICENSE: {'✓' if (PROJECT_DIR / 'LICENSE').exists() else '✗'}")
    print(f"  tests/: {'✓' if TESTS_DIR.exists() else '✗'}")

    # Existing releases
    if DIST_DIR.exists():
        releases = list(DIST_DIR.glob("*.zip"))
        if releases:
            print(f"\nExisting releases:")
            for rel in sorted(releases):
                print(f"  {rel.name}")

    # Git status
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR
        )
        if result.stdout.strip():
            print("\nWarning: Uncommitted changes detected")
    except FileNotFoundError:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Ladder Release Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 1.1.0 --changelog "- Added new feature\\n- Fixed bug"
  %(prog)s 1.2.0 --changelog "Major update" --tag
  %(prog)s --check
        """
    )

    parser.add_argument(
        "version",
        nargs="?",
        help="New version number (X.Y.Z format)"
    )

    parser.add_argument(
        "--changelog", "-c",
        help="Changelog entry for this version"
    )

    parser.add_argument(
        "--tag", "-t",
        action="store_true",
        help="Create git tag for release"
    )

    parser.add_argument(
        "--no-tests",
        action="store_true",
        help="Skip running tests"
    )

    parser.add_argument(
        "--blender",
        help="Path to Blender executable for running tests"
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Show current status without making changes"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )

    args = parser.parse_args()

    # Show status and exit
    if args.check:
        show_status()
        return 0

    # Version is required for release
    if not args.version:
        parser.error("Version number is required (or use --check)")

    # Validate version
    try:
        parse_version(args.version)
    except ValueError as e:
        parser.error(str(e))

    current = get_current_version()
    print(f"\n=== Ladder Release: v{current} → v{args.version} ===\n")

    if args.dry_run:
        print("[DRY RUN - No changes will be made]\n")

    # 1. Update version
    print("1. Updating version...")
    if not args.dry_run:
        update_version_in_init(args.version)
    else:
        print(f"  Would update version to {args.version}")

    # 2. Update changelog
    if args.changelog:
        print("\n2. Updating changelog...")
        if not args.dry_run:
            update_changelog_in_readme(args.version, args.changelog)
        else:
            print(f"  Would add changelog: {args.changelog[:50]}...")
    else:
        print("\n2. Skipping changelog (not provided)")

    # 3. Run tests
    if not args.no_tests:
        print("\n3. Running tests...")
        if not args.dry_run:
            tests_passed = run_tests(args.blender)
            if not tests_passed:
                print("\nRelease aborted due to test failures.")
                print("Use --no-tests to skip tests.")
                return 1
        else:
            print("  Would run tests")
    else:
        print("\n3. Skipping tests (--no-tests)")

    # 4. Create zip
    print("\n4. Creating release zip...")
    if not args.dry_run:
        zip_path = create_release_zip(args.version)
    else:
        print(f"  Would create ladder-v{args.version}.zip")

    # 5. Create git tag
    if args.tag:
        print("\n5. Creating git tag...")
        if not args.dry_run:
            tag_msg = f"Release v{args.version}"
            if args.changelog:
                tag_msg += f"\n\n{args.changelog}"
            create_git_tag(args.version, tag_msg)
        else:
            print(f"  Would create tag v{args.version}")
    else:
        print("\n5. Skipping git tag (use --tag to create)")

    # Summary
    print("\n" + "=" * 40)
    print("Release complete!" if not args.dry_run else "Dry run complete!")
    print("=" * 40)

    if not args.dry_run:
        print(f"\nRelease zip: {DIST_DIR / f'ladder-v{args.version}.zip'}")
        print("\nNext steps:")
        print("  1. Test the zip file in Blender")
        print("  2. Commit changes: git add -A && git commit -m 'Release v{}'".format(args.version))
        if args.tag:
            print(f"  3. Push with tag: git push origin main --tags")
        else:
            print("  3. Push changes: git push origin main")
        print("  4. Create GitHub release and upload zip")

    return 0


if __name__ == "__main__":
    sys.exit(main())
