"""Create a source-only release. Never include databases or local credentials."""
from pathlib import Path
import hashlib
import tarfile

root = Path(__file__).resolve().parent.parent
output = root / "dist"
output.mkdir(exist_ok=True)
archive = output / "nara-panel_0.1.1_source.tar.gz"
included = ["nara", "web", "tests", "scripts", "deploy", "screenshots", "README.md", "INSTALL.fa.md",
            "VERIFICATION.md", "LICENSE", "requirements.txt", "Dockerfile", "compose.yaml", "install.sh", ".dockerignore", ".gitignore"]
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
