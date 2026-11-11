"""
Copy the parts of ENSIM's operating model this project reads into
``operating_model/ensim@<commit>/``, with a provenance record.

    git clone https://github.com/semanticarchitectures/ENSIM /path/to/ensim
    python scripts/snapshot_ensim.py /path/to/ensim

The snapshot is committed, so runs never need the network or an ENSIM
checkout.  Files are copied byte for byte; nothing is edited.  To move to a
newer ENSIM commit, check it out, rerun this script, and update
``ENSIM_SNAPSHOT`` in ``src/airdrop_alpha/operating_model.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

DATA = "packages/org-doctrine-model/data"
FILES = ["roles.json", "interactions.json", "systems.json", "organizations.json"]
LICENSE_FILES = ["LICENSE", "NOTICE"]
REPO = "https://github.com/semanticarchitectures/ENSIM"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ensim_checkout", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "operating_model")
    args = parser.parse_args()

    src = args.ensim_checkout.resolve()
    commit = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(src), "status", "--porcelain", "--", DATA], check=True,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit(f"{src}/{DATA} has uncommitted changes; snapshot a clean commit")

    dest = args.out / f"ensim@{commit[:7]}"
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for name in FILES:
        shutil.copyfile(src / DATA / name, dest / name)
        files.append({"path": f"{DATA}/{name}", "sha256": hashlib.sha256((dest / name).read_bytes()).hexdigest()})
    for name in LICENSE_FILES:
        shutil.copyfile(src / name, dest / name)

    provenance = {
        "source": REPO,
        "commit": commit,
        "license": "Apache-2.0 (LICENSE and NOTICE copied alongside)",
        "copied_on": date.today().isoformat(),
        "files": files,
        "note": "Copied unchanged. Roles, links and systems this project needs that ENSIM lacks are "
                "added in operating_model/local.yaml and marked representative.",
    }
    (dest / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
