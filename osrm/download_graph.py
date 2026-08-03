#!/usr/bin/env python3
"""Install a published OSRM graph archive described by a local manifest."""
import argparse
import hashlib
import json
import tarfile
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--manifest", type=Path, required=True)
parser.add_argument("--destination", type=Path, default=Path("osrm/data"))
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
url, checksum = manifest.get("archive_url", ""), manifest.get("archive_sha256", "")
if not url or not checksum:
    raise SystemExit("graph archive is not published: supply archive_url and archive_sha256 in a copied manifest")
archive = args.destination.parent / manifest["archive_filename"]
args.destination.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(url) as response, archive.open("wb") as output:
    output.write(response.read())
actual = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
if actual != checksum:
    archive.unlink(missing_ok=True)
    raise SystemExit("graph archive checksum mismatch")
with tarfile.open(archive, "r:*") as package:
    package.extractall(args.destination, filter="data")
print(f"installed {manifest['graph_version']} into {args.destination}")
