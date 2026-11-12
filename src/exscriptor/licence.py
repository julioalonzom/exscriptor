"""The licence of Schola Thomistica's own transcriptions and translations.

What this pipeline makes is CC BY 4.0: anyone may reuse it, commercially too,
if they credit Schola Thomistica. A third party's text keeps its own licence.

A source staged under an own basis must carry this licence and the credit.
The builders check it early; ``exscriptor.submit`` checks every batch, however
it was built. A CC0 slip is permanent (a dedication cannot be taken back), so
both refuse rather than fix it up. A source under an own basis whose text is
not ours (a third party's public-domain translation, a digital text taken as
is) says why in ``metadata.schola_license_exempt``.
"""
from __future__ import annotations

CODE = "CC-BY-4.0"
URL = "https://creativecommons.org/licenses/by/4.0/"
CREDIT = "ScholaThomistica (scholathomistica.com)"
# A text under these bases is ours to license: made here from public-domain
# material, or our own translation.
OWN_BASES = {"public_domain_edition", "public_domain_life_70", "own_contribution"}


def problems(source: dict) -> list[str]:
    if source.get("rights_basis") not in OWN_BASES:
        return []
    if (source.get("metadata") or {}).get("schola_license_exempt"):
        return []
    name = f"source {source.get('source_key')} ({source.get('rights_basis')})"
    found = []
    if source.get("license_code") != CODE or source.get("license_url") != URL:
        found.append(
            f"{name}: if we made this text it is {CODE}; set license_code "
            f"{CODE!r} and license_url {URL!r} (a live source keeps its terms: "
            "declare a new source_key)"
        )
    if CREDIT not in (source.get("attribution_text") or ""):
        found.append(f"{name}: if we made this text, attribution_text must credit {CREDIT!r}")
    if found:
        found.append(
            f"{name}: if it is a third party's text (a public-domain translation "
            "or edition), it keeps its own licence: say so in "
            "metadata.schola_license_exempt"
        )
    return found


def manifest_problems(manifest: dict) -> list[str]:
    """Every source a batch declares for new text, checked as above. An edit
    batch is not: a correction keeps the licence of the text it corrects."""
    if all(w.get("import_mode") == "edit" for w in manifest.get("works") or []):
        return []
    return [p for source in manifest.get("sources") or [] for p in problems(source)]
