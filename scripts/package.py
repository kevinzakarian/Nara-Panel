"""Create a source-only release. Never include databases or local credentials."""
from pathlib import Path
import hashlib
import json
import re
import tarfile

root = Path(__file__).resolve().parent.parent
release = json.loads((root / "release.json").read_text())
version, core_version = release["version"], release["core_version"]
if version != core_version and not re.fullmatch(re.escape(core_version) + r"\.[1-9][0-9]{0,5}", version):
    raise SystemExit("Panel release version must match its core, optionally followed by a positive panel revision.")
if json.loads((root / "core-release.json").read_text())["version"] != core_version:
    raise SystemExit("The panel release and compatible core manifest must specify the same core version.")
output = root / "dist"
output.mkdir(exist_ok=True)
archive = output / f"nara-panel_{version}_source.tar.gz"
included = ["core-build.json", "core-release.json", ".github", "nara", "web", "tests", "scripts", "deploy", "screenshots", "README.md", "API.md", "SECURITY_REVIEW.md", "INSTALL.fa.md", "release.json",
            "package.json", "package-lock.json", "FEATURE_REVIEW.md", "VERIFICATION.md", "LICENSE", "requirements.txt", "Dockerfile", "compose.yaml", "install.sh", "update.sh", ".dockerignore", ".gitignore"]
with tarfile.open(archive, "w:gz") as bundle:
    for name in included:
        path = root / name
        entries = sorted(path.rglob("*")) if path.is_dir() else [path]
        for entry in entries:
            if entry.is_file() and "__pycache__" not in entry.parts and entry.suffix != ".pyc":
                bundle.add(entry, arcname=str(Path("nara-panel") / entry.relative_to(root)), recursive=False)
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / "SHA256SUMS").write_text(digest + "  " + archive.name + "\n")
print(archive)
