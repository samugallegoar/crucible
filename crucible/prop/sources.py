"""The evidence self-check: every attribution resolves to the bytes it cites (ADR-0107 section 7).

A ruleset is only as good as its citations, and a citation is a claim about BYTES: a saved page
whose sha256 is declared, a quotation that appears in that page, or an image whose sha256 is
declared and whose printed values were transcribed by a named person on a named date. This module
is the check, so that "the quotes verify" is code that raises and not a paragraph in a review.

The saved snapshots live OUTSIDE the repository (a private research folder, one directory per
firm), so ``root`` is an argument: ``crucible prop validate <file> --snapshots-root DIR`` passes it.
Nothing here reaches the network: a citation is verified against the bytes already on disk, and a
hash that names no file is a failure, never a warning.

What is checked, for every attribution of every rule (the value's own source and each supporting
one), every promotion, both sides of every conflict, every ``not_modeled`` entry and the
commissions block:

1. ``snapshot_sha256`` must be the sha256 of a file under ``root`` (the saved page).
2. ``quote`` must appear in that file's text, normalised the same way on both sides (UTF-8, HTML
   entities unescaped, whitespace collapsed; second pass with the tags stripped, because a value
   inside a table cell only matches that way).
3. An image attribution (``evidence: official_image_transcription``) must ALSO resolve its
   ``image_path`` under ``root`` to a file whose sha256 is ``image_snapshot_sha256``. Its
   ``transcription`` is never compared with page text: the values are printed only in the image,
   which is the whole reason the type exists. The transcription is required to be non-empty and
   the image block is validated by the schema (all-or-nothing, relative path, dated).

A ``synthetic: true`` attribution is skipped by design (it names invented test data and can never
verify), and is reported in the count so a real-firm pass can show there are none.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from pathlib import Path

from crucible.core.errors import DataQualityError
from crucible.prop.rules_schema import Attribution
from crucible.prop.ruleset import PropRuleset

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class SourceProblem:
    """One citation that does not resolve, named by where it sits and what failed."""

    where: str
    problem: str


@dataclass(frozen=True)
class SourceCheck:
    """The result of the self-check over one ruleset: counts, and every problem found."""

    root: str
    attributions: int
    images: int
    synthetic: int
    snapshots: int
    problems: tuple[SourceProblem, ...]

    @property
    def ok(self) -> bool:
        """Whether every citation resolved."""
        return not self.problems

    def summary(self) -> str:
        """One line a CLI or a report can print."""
        head = (
            f"{self.attributions} attribution(s), {self.images} image(s), "
            f"{self.synthetic} synthetic, {self.snapshots} snapshot file(s) under {self.root}: "
        )
        if self.ok:
            return head + "every quote and every hash verified"
        return (
            head
            + f"{len(self.problems)} problem(s): "
            + "; ".join(f"{item.where}: {item.problem}" for item in self.problems)
        )


def file_hashes(root: str | Path) -> dict[str, list[str]]:
    """``sha256 -> [relative paths]`` for every file under ``root`` (recursively, sorted)."""
    base = Path(root)
    if not base.is_dir():
        msg = (
            f"snapshots root {str(base)!r} is not a directory: the self-check verifies citations "
            "against saved bytes, so pass the folder that holds them (--snapshots-root)"
        )
        raise DataQualityError(msg)
    found: dict[str, list[str]] = {}
    for path in sorted(item for item in base.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        found.setdefault(digest, []).append(path.relative_to(base).as_posix())
    return found


def normalise(text: str) -> str:
    """Collapse a page or a quote to comparable text: entities unescaped, whitespace collapsed."""
    return _SPACE.sub(" ", html.unescape(text)).strip()


def page_text(data: bytes) -> tuple[str, str]:
    """The two normalised forms a quote may match: the raw text and the text without tags."""
    decoded = data.decode("utf-8", errors="ignore")
    plain = normalise(decoded)
    return plain, normalise(_TAG.sub(" ", decoded))


def _attributions(ruleset: PropRuleset) -> list[tuple[str, Attribution]]:
    """Every attribution of the ruleset, in report order, with where it sits."""
    found: list[tuple[str, Attribution]] = [("commissions", ruleset.commissions.source)]
    for phase in ruleset.phases:
        for rule in (*phase.rules, *phase.pass_conditions, *phase.fees):
            where = f"{phase.phase_id}.{rule.rule_id}"
            found.append((where, rule.source))
            found.extend(
                (f"{where} (supporting {index})", source)
                for index, source in enumerate(rule.supporting_sources, start=1)
            )
            found.extend(
                (f"{where} (promotion {promotion.id})", promotion.source)
                for promotion in rule.promotions
                if promotion.source is not None
            )
    for conflict in ruleset.conflicts:
        where = f"conflict {conflict.conflict_id}"
        found.append((where, conflict.selected_source))
        found.extend(
            (f"{where} (alternative {index})", alternative.source)
            for index, alternative in enumerate(conflict.alternatives, start=1)
        )
    found.extend((f"not_modeled {entry.rule}", entry.source) for entry in ruleset.not_modeled)
    return found


def check_sources(ruleset: PropRuleset, root: str | Path) -> SourceCheck:
    """Check every citation of ``ruleset`` against the saved bytes under ``root``.

    Never raises for a bad citation: returns it. ``verify_sources`` is the refusing wrapper.
    """
    hashes = file_hashes(root)
    base = Path(root).resolve()
    problems: list[SourceProblem] = []
    checked = images = synthetic = 0
    texts: dict[str, tuple[str, str] | None] = {}
    for where, source in _attributions(ruleset):
        if source.synthetic:
            synthetic += 1
            continue
        checked += 1
        if source.has_image:
            images += 1
        paths = hashes.get(source.snapshot_sha256, [])
        if not paths:
            problems.append(
                SourceProblem(
                    where,
                    f"snapshot_sha256 {source.snapshot_sha256} names no file under {str(base)!r}: "
                    "the page the quote comes from is not saved, or the hash is wrong",
                )
            )
        else:
            if source.snapshot_sha256 not in texts:
                texts[source.snapshot_sha256] = page_text((base / paths[0]).read_bytes())
            forms = texts[source.snapshot_sha256]
            quoted = normalise(source.quote)
            if forms is not None and not any(quoted in form for form in forms):
                problems.append(
                    SourceProblem(
                        where,
                        f"quote not found in {paths[0]} (sha256 {source.snapshot_sha256}): "
                        f"{source.quote[:120]!r}",
                    )
                )
        if not source.has_image:
            continue
        assert source.image_path is not None
        assert source.image_snapshot_sha256 is not None
        image = (base / source.image_path).resolve()
        try:
            image.relative_to(base)
        except ValueError:
            problems.append(
                SourceProblem(
                    where,
                    f"image_path {source.image_path!r} escapes the snapshots root {str(base)!r}",
                )
            )
            continue
        if not image.is_file():
            problems.append(
                SourceProblem(where, f"image_path {source.image_path!r} is not a file under {base}")
            )
            continue
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != source.image_snapshot_sha256:
            problems.append(
                SourceProblem(
                    where,
                    f"image {source.image_path!r} hashes to {digest}, not to the declared "
                    f"image_snapshot_sha256 {source.image_snapshot_sha256}: the transcribed file "
                    "changed, so the transcription may no longer describe it",
                )
            )
        if not (source.transcription or "").strip():
            problems.append(
                SourceProblem(
                    where,
                    "image attribution has an empty transcription: the printed values are the "
                    "evidence, so a value only in the image must be transcribed",
                )
            )
    return SourceCheck(
        root=str(base),
        attributions=checked,
        images=images,
        synthetic=synthetic,
        snapshots=len(hashes),
        problems=tuple(problems),
    )


def verify_sources(ruleset: PropRuleset, root: str | Path) -> SourceCheck:
    """``check_sources`` that REFUSES: a citation that does not resolve raises.

    ``DataQualityError`` names the ruleset, the count and every problem, because a run that cites
    bytes it cannot show is a run whose evidence cannot be reviewed.
    """
    result = check_sources(ruleset, root)
    if not result.ok:
        msg = (
            f"ruleset {ruleset.ruleset_id} v{ruleset.version} evidence self-check failed: "
            f"{result.summary()}"
        )
        raise DataQualityError(msg)
    return result
