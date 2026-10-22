"""Whether a job's output name is already taken by a finished release.

The worker refuses to finalize into ``completed/<output_name>`` when that
directory holds a different release (``_finalize``: only a byte-identical
mux, or a legacy schema 1 record of the same job, may reuse it).  Before
3.11.2 this was only discovered after the encode, hours later; the selection
is now checked when it is validated and approved.

Any non-empty directory counts as taken, except a legacy record naming this
job.  The owner record deliberately carries no job id (completed releases are
public), so a re-finalized identical mux is the only case this refuses that
finalizing would allow; the operator then renames or moves the old release.
No replacement name is invented: a numbered suffix is not a valid release
name, so the operator picks one (usually by adding the release tag).
"""

from __future__ import annotations

import json
from pathlib import Path

OWNER_RECORD = ".bdencode-owner.json"
OUTPUT_NAME_TAKEN = "output_name_taken"


def output_name_taken(completed_root: Path, output_name: str, job_id: str) -> bool:
    """True when finalizing ``output_name`` would meet another release."""

    directory = completed_root / output_name
    try:
        if not directory.is_dir() or not any(directory.iterdir()):
            return False
        owner = json.loads((directory / OWNER_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no or unreadable owner record: not ours
        return True
    legacy_own = (
        isinstance(owner, dict)
        and owner.get("schema_version") == 1
        and owner.get("job_id") == job_id
    )
    return not legacy_own


__all__ = ["OUTPUT_NAME_TAKEN", "OWNER_RECORD", "output_name_taken"]
