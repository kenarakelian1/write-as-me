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
WAM_MD = (ROOT / "commands" / "wam.md").read_text(encoding="utf-8")
WRITE_AS_ME_MD = (ROOT / "commands" / "write-as-me.md").read_text(encoding="utf-8")


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


# --- Final whole-branch review, Finding 1: /wam review cannot be invoked ---


def test_command_files_route_the_review_argument_to_review_mode():
    """Both command files previously only branched on 'no arguments' (analyze)
    vs. 'any arguments' (write), so `/wam review` supplied an argument and
    was routed to write mode -- drafting an email about the word 'review'."""
    for name, text in (("commands/wam.md", WAM_MD),
                       ("commands/write-as-me.md", WRITE_AS_ME_MD)):
        assert "review" in text.lower(), f"{name} never mentions review mode"
        assert "review mode" in text.lower(), f"{name} must route to review mode"


def test_skill_frontmatter_description_triggers_on_review():
    frontmatter = SKILL.split("---", 2)[1]
    assert "description:" in frontmatter
    description_line = [l for l in frontmatter.splitlines() if l.startswith("description:")][0]
    assert "review" in description_line.lower(), (
        "the frontmatter description must carry a review trigger so the "
        "skill is discoverable by phrases like 'review my drafts'"
    )


def test_skill_no_longer_claims_two_modes():
    intro = SKILL.split("## Before either mode", 1)[0]
    assert "two modes" not in intro.lower()


def test_skill_invocation_table_has_a_review_row():
    intro = SKILL.split("## Before either mode", 1)[0]
    assert "review" in intro.lower()
    assert "/wam review" in intro or "/write-as-me review" in intro


# --- Finding 2: set_status is dead code, so status never advances ---------


def test_skill_step6_cites_the_set_status_command():
    review_mode = SKILL.split("## Review mode", 1)[1]
    step6 = review_mode.split("### Step 6", 1)[1]
    assert "--set-status" in step6
    assert "--status matched" in step6


def test_skill_ambiguous_branch_cites_the_set_status_command():
    review_mode = SKILL.split("## Review mode", 1)[1]
    step1 = review_mode.split("### Step 1", 1)[1].split("### Step 2", 1)[0]
    ambiguous_branch = step1.split("- `ambiguous`", 1)[1].split("- `none`", 1)[0]
    assert "--set-status" in ambiguous_branch


# --- Finding 3: the draft body never reaches the matcher or the differ ----


def test_skill_step1_fetches_the_full_record_before_matching():
    review_mode = SKILL.split("## Review mode", 1)[1]
    step1 = review_mode.split("### Step 1", 1)[1].split("### Step 2", 1)[0]
    assert "--get" in step1
    assert "--draft-id" in step1


def test_skill_states_the_match_candidate_shape():
    review_mode = SKILL.split("## Review mode", 1)[1]
    step1 = review_mode.split("### Step 1", 1)[1].split("### Step 2", 1)[0]
    for key in ("subject", "body", "recipients", "date"):
        assert f'"{key}"' in step1


def test_skill_list_pending_is_documented_as_bodyless_and_get_as_the_full_record():
    """--list-pending stays compact on purpose (it feeds the non-blocking
    check and must not pull draft bodies into context); the gap this finding
    fixes is that nothing told the model to reach for --get before matching,
    so a compact record got fed straight to --match and the fuzzy fallback
    (similarity("", body)) silently always returned 0.0."""
    review_mode = SKILL.split("## Review mode", 1)[1]
    step1 = review_mode.split("### Step 1", 1)[1].split("### Step 2", 1)[0]
    assert "no `body`" in step1 or "no body" in step1.lower()
    assert "never" in step1 and "context" in step1


def test_skill_states_the_diff_draft_file_shape():
    review_mode = SKILL.split("## Review mode", 1)[1]
    step2 = review_mode.split("### Step 2", 1)[1].split("### Step 3", 1)[0]
    assert "subject" in step2 and "body" in step2


# --- Finding 4: fetched sent mail must never be written into the repo -----


def test_skill_review_mode_mandates_the_tmp_directory():
    review_mode = SKILL.split("## Review mode", 1)[1]
    assert "~/.claude/wam/tmp/" in review_mode


def test_skill_review_mode_requires_deleting_tmp_even_on_early_exit():
    review_mode = SKILL.split("## Review mode", 1)[1]
    assert "delete" in review_mode.lower()
    # Must cover the early-exit case, not just the happy path.
    assert "early" in review_mode.lower() or "stops early" in review_mode.lower()


def test_readme_privacy_claim_matches_the_tmp_dir_behavior():
    edits_section = README.split("## Learning from your edits", 1)[1].split(
        "## Privacy", 1
    )[0]
    assert "never written to disk" not in edits_section
    assert "~/.claude/wam/tmp/" in edits_section
    assert "delete" in edits_section.lower()


# --- Finding 7: README omits a testing disclosure --------------------------


def test_readme_discloses_review_mode_is_untested_end_to_end():
    edits_section = README.split("## Learning from your edits", 1)[1].split(
        "## Privacy", 1
    )[0]
    assert "not been exercised" in edits_section or "have not been" in edits_section
    assert "review" in edits_section.lower()
