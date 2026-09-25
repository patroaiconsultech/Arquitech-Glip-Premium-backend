from pathlib import Path
import re


ALEMBIC_VERSION_CAPACITY = 128


def test_all_alembic_revision_ids_fit_version_table_capacity():
    revisions = []

    for path in Path("migrations/versions").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        match = re.search(
            r'^revision\s*=\s*["\']([^"\']+)["\']',
            text,
            re.MULTILINE,
        )

        if match:
            revisions.append((path.name, match.group(1)))

    assert revisions
    violations = [
        (name, revision, len(revision))
        for name, revision in revisions
        if len(revision) > ALEMBIC_VERSION_CAPACITY
    ]

    assert not violations, violations
