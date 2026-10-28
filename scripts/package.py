"""Create a source/evidence archive without runtime caches or local secrets."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {"README.md", "requirements.txt", ".env.example", ".gitignore"}
TOP_DIRS = {"src", "tests", "data", "examples", "docs", "scripts"}


def package(destination: Path):
    paths = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if not path.is_file() or "__pycache__" in rel.parts:
            continue
        if rel.parts[0] not in TOP_DIRS and str(rel) not in TOP_FILES:
            continue
        if path.suffix in {".pyc", ".pyo", ".sqlite3", ".zip"} or path.name.startswith(".env") and path.name != ".env.example":
            continue
        paths.append(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, (Path(ROOT.name) / path.relative_to(ROOT)).as_posix())
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{checksum}  {destination.name}\n", encoding="utf-8")
    print(f"Packaged {len(paths)} files: {destination.name}")
    return len(paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT.parent / "material-scheduler.zip")
    package(parser.parse_args().out)
