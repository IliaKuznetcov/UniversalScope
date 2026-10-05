"""Collect installed license texts for review; this is not a compliance audit.

Run using the virtual environment used to build the Windows executable.
Only the Python standard library is used. No packages are imported or downloaded.
The output inventories installed packages, not the contents of an executable.
"""

import hashlib
import importlib.metadata as metadata
import json
import platform
import re
import sys
from pathlib import Path, PurePosixPath


def is_notice_file(relative_path):
    path = PurePosixPath(str(relative_path).replace("\\", "/"))
    name = path.name.lower()
    return (
        name.startswith(("license", "licence", "copying", "notice", "copyright"))
        or name.endswith((".license", ".licence"))
        or any(part.lower() in {"licenses", "licences"} for part in path.parts[:-1])
    ) and path.suffix.lower() not in {".py", ".pyc", ".pyd", ".dll", ".so", ".exe"}


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip(".") or "unnamed"


def copy_notice(source, destination):
    data = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def collect_distribution(dist, output):
    info = dist.metadata
    name = info.get("Name", "unknown")
    version = dist.version
    package_dir = output / "packages" / safe_name(f"{name}-{version}")
    record = {
        "name": name,
        "version": version,
        "license_expression": info.get("License-Expression", ""),
        "license_metadata": info.get("License", ""),
        "license_classifiers": [
            item for item in info.get_all("Classifier", [])
            if item.startswith("License ::")
        ],
        "declared_license_files": info.get_all("License-File", []),
        "project_urls": info.get_all("Project-URL", []),
        "home_page": info.get("Home-page", ""),
        "copied_files": [],
        "review_notes": [],
    }
    files = dist.files
    if files is None:
        record["review_notes"].append("Installed file list unavailable.")
        files = []

    for relative in files:
        if not is_notice_file(relative):
            continue
        source = Path(dist.locate_file(relative))
        if not source.is_file():
            record["review_notes"].append(f"Listed notice missing: {relative}")
            continue
        filename = f"{len(record['copied_files']) + 1:03d}_{safe_name(source.name)}"
        destination = package_dir / filename
        try:
            digest = copy_notice(source, destination)
        except OSError as error:
            record["review_notes"].append(
                f"Unable to read notice {relative}: {type(error).__name__}"
            )
            continue
        record["copied_files"].append({
            "installed_relative_path": str(relative),
            "saved_path": destination.relative_to(output).as_posix(),
            "sha256": digest,
        })

    if not record["copied_files"]:
        record["review_notes"].append(
            "No standalone license files found. Review package metadata and upstream notices."
        )
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "PACKAGE_METADATA.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return record


def main():
    output = Path(__file__).resolve().parent / "third_party_licenses"
    if output.exists():
        raise SystemExit(
            "third_party_licenses already exists. Rename that folder before collecting again."
        )
    output.mkdir()
    packages = []
    errors = []
    distributions = sorted(
        metadata.distributions(),
        key=lambda dist: dist.metadata.get("Name", "").lower(),
    )
    for dist in distributions:
        name = dist.metadata.get("Name", "unknown")
        try:
            packages.append(collect_distribution(dist, output))
        except Exception as error:
            errors.append({"package": name, "error_type": type(error).__name__})

    python_license = None
    for filename in ("LICENSE.txt", "LICENSE", "LICENSE.md"):
        candidate = Path(sys.base_prefix) / filename
        if candidate.is_file():
            destination = output / "Python" / filename
            try:
                digest = copy_notice(candidate, destination)
                python_license = {
                    "saved_path": destination.relative_to(output).as_posix(),
                    "sha256": digest,
                }
            except OSError as error:
                errors.append({"package": "Python", "error_type": type(error).__name__})
            break

    report = {
        "scope": "Installed environment inventory; not an executable component inventory.",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python_license_file": python_license,
        "packages": packages,
        "errors": errors,
        "outstanding_review": [
            "Compare this inventory against files actually bundled by PyInstaller.",
            "Check notices for bundled native libraries, fonts, and Python runtime components.",
            "Provide required corresponding library source or a valid source-access mechanism.",
            "Confirm users can replace or relink LGPL libraries and run the resulting application.",
            "Make notices accessible in the application and in the release download.",
        ],
    }
    (output / "LICENSE_INVENTORY.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    rows = [
        "# Installed dependency license inventory",
        "",
        "Collected from the build environment. This inventory includes installed packages",
        "that may not be bundled in the executable, including development tools.",
        "It is a collection for review, not a determination of licensing compliance.",
        "",
        f"Python: {platform.python_version()}",
        "",
        "| Package | Version | Notice files copied |",
        "|---|---|---|",
    ]
    for package in packages:
        rows.append(
            f"| {package['name']} | {package['version']} | {len(package['copied_files'])} |"
        )
    rows.extend(["", "## Outstanding review", ""])
    rows.extend(f"- {item}" for item in report["outstanding_review"])
    rows.extend(["", "See LICENSE_INVENTORY.json for metadata, project URLs, and review notes.", ""])
    (output / "INVENTORY.md").write_text("\n".join(rows), encoding="utf-8")

    pending = [package for package in packages if package["review_notes"]]
    print(f"Collected license information for {len(packages)} installed packages.")
    print(f"Packages with review notes: {len(pending)}")
    for package in pending:
        print(f"  {package['name']} {package['version']}: {'; '.join(package['review_notes'])}")
    if python_license is None:
        print("Python installation license file was not found; review required.")
    if errors:
        print(f"Collection errors: {len(errors)}; see LICENSE_INVENTORY.json.")
    print("Created third_party_licenses. Review it before adding notices to a release.")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

