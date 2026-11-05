"""Package only public project files; never include local settings or credentials."""
from hashlib import sha256
from pathlib import Path
from shutil import copyfile
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist"
DOWNLOADS = ROOT / "downloads"
PUBLIC_SUFFIXES = {".py", ".md", ".pdf", ".html", ".js", ".css", ".ps1", ".json"}


def main():
    OUTPUT.mkdir(exist_ok=True)
    DOWNLOADS.mkdir(exist_ok=True)
    files = [ROOT / name for name in (".gitattributes", ".gitignore", "README.md", "pyproject.toml", "uv.lock")]
    for folder in ("arbscanner", "static", "tests", "tools", "docs", "examples"):
        files.extend(path for path in (ROOT / folder).rglob("*")
                     if path.is_file() and path.suffix in PUBLIC_SUFFIXES
                     and not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(ROOT).parts))
    source = OUTPUT / "arbitrage-finder-windows.zip"
    guides = OUTPUT / "arbitrage-finder-guides.zip"
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, Path("Arbitrage-Finder") / path.relative_to(ROOT))
    pdfs = sorted((ROOT / "docs" / "pdf").glob("*.pdf"))
    if len(pdfs) != 7:
        raise RuntimeError("Expected seven generated PDF manuals before packaging")
    with ZipFile(guides, "w", ZIP_DEFLATED) as archive:
        for path in pdfs:
            archive.write(path, path.name)
    checksums = []
    for path in (source, guides):
        with ZipFile(path) as archive:
            if archive.testzip() is not None or sum(name.endswith(".pdf") for name in archive.namelist()) != 7:
                raise RuntimeError("Archive validation failed")
        copyfile(path, DOWNLOADS / path.name)
        checksums.append(f"{sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
        print(f"Packaged {path.name}: {path.stat().st_size:,} bytes")
    for folder in (OUTPUT, DOWNLOADS):
        (folder / "SHA256SUMS.txt").write_text("".join(checksums))


if __name__ == "__main__":
    main()
