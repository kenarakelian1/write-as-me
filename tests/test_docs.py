# tests/test_docs.py
"""Content checks for docs findings that have no executable code path of
their own (Findings 2 and 4 of the final whole-branch review). These assert
on the literal text of SKILL.md / README.md / .gitignore so a future edit
can't silently regress the fix."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = (ROOT / "skills" / "write-as-me" / "SKILL.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")


# --- Finding 2: lexicon is never redacted by redact.py, only exemplars ----


def test_skill_step4_explicitly_checks_the_lexicon():
    """Step 4 must instruct the same per-entry redaction check for the
    lexicon that it already applies to exemplars, since redact.py never
    processes fingerprint.json and Step 5 tells the model to quote lexicon
    entries verbatim into the durable profile."""
    step4 = SKILL.split("### Step 4", 1)[1].split("### Step 5", 1)[0]
    assert "lexicon" in step4.lower()
    # Not just a passing mention: it must ask for the same per-entry rigor.
    assert "per-entry" in step4 or "entry by entry" in step4 or "each of the top entries" in step4.lower()


def test_readme_does_not_call_fingerprint_json_already_redacted():
    """fingerprint.json is never passed through redact.py — only
    exemplars.json is. The README must not claim otherwise."""
    assert "already-redacted `fingerprint.json`" not in README
    assert "already-redacted" not in README.split("Privacy", 1)[1].split(
        "## Evaluating", 1
    )[0].replace("already-redacted `exemplars.redacted.json`", "")


def test_readme_states_redact_only_covers_exemplars():
    privacy = README.split("## Privacy", 1)[1].split("## Evaluating", 1)[0]
    assert "redact.py" in privacy
    assert "exemplars.json" in privacy


# --- Finding 4: eval procedure must not write real mail into the repo -----


def test_readme_eval_procedure_uses_wam_home_dir_not_repo_cwd():
    eval_section = README.split("## Evaluating", 1)[1].split("## Development", 1)[0]
    for fname in ("holdout.json", "drafts.json", "control.json"):
        assert f"~/.claude/wam/{fname}" in eval_section, (
            f"{fname} must be pointed at ~/.claude/wam/, not the repo working directory"
        )


def test_gitignore_covers_eval_artifacts():
    for fname in ("holdout.json", "drafts.json", "control.json"):
        assert fname in GITIGNORE, f"{fname} must be gitignored as a backstop"
