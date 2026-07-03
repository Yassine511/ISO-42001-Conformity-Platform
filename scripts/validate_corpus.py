"""Deterministic consistency checks for the M1b corpus.

Validates:
  - KB: unique ids, allowed domains, no suspiciously long entries (verbatim-ISO guard);
  - gold labels: every requirement_id exists in the KB, every evidence quote is an
    exact substring (after Unicode NFC normalization) of its source document,
    verdict/document/quote consistency;
  - coverage report: verdict mix per class and per domain.

Usage:  python scripts/validate_corpus.py
Exit code 0 = all checks pass. Also run by backend/tests/test_corpus.py.
"""

import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB_PATH = ROOT / "corpus" / "kb" / "iso42001_kb.json"
GOLD_PATH = ROOT / "corpus" / "gold" / "gold_labels.json"
DOCS_DIR = ROOT / "corpus" / "documents"

ALLOWED_DOMAINS = {"4", "5", "6", "7", "8", "9", "10"} | {f"A.{i}" for i in range(2, 11)}
ALLOWED_VERDICTS = {"compliant", "partial", "non_compliant", "missing"}
MAX_REQUIREMENT_CHARS = 400  # verbatim-ISO guard: paraphrases must stay short
MAX_QUOTE_CHARS = 300


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def check_kb(kb: dict) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    ids: set[str] = set()
    for entry in kb["requirements"]:
        rid = entry["id"]
        if rid in ids:
            errors.append(f"KB: id dupliqué {rid}")
        ids.add(rid)
        if entry["domain"] not in ALLOWED_DOMAINS:
            errors.append(f"KB {rid}: domaine inconnu {entry['domain']!r}")
        if not rid.startswith(entry["domain"]) and not rid.split(".")[0] == entry["domain"]:
            errors.append(f"KB {rid}: id incohérent avec le domaine {entry['domain']}")
        if len(entry["requirement_fr"]) > MAX_REQUIREMENT_CHARS:
            errors.append(
                f"KB {rid}: paraphrase trop longue ({len(entry['requirement_fr'])} > {MAX_REQUIREMENT_CHARS} caractères) — risque de texte ISO verbatim"
            )
        if not entry.get("keywords_fr"):
            errors.append(f"KB {rid}: keywords_fr manquants")
    return errors, ids


def check_gold(gold: dict, kb_ids: set[str], docs: dict[str, str]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for item in gold["items"]:
        gid = item["id"]
        if gid in seen:
            errors.append(f"Gold {gid}: id dupliqué")
        seen.add(gid)
        if item["requirement_id"] not in kb_ids:
            errors.append(f"Gold {gid}: requirement_id {item['requirement_id']!r} absent de la KB")
        if item["verdict"] not in ALLOWED_VERDICTS:
            errors.append(f"Gold {gid}: verdict inconnu {item['verdict']!r}")
        if item.get("split") not in {"dev", "test"}:
            errors.append(f"Gold {gid}: split invalide {item.get('split')!r} (attendu dev|test)")
        if item["verdict"] == "missing":
            if item["document"] is not None or item["evidence_quote_fr"] is not None:
                errors.append(f"Gold {gid}: verdict 'missing' mais document/quote non nuls")
            continue
        doc = item["document"]
        quote = item["evidence_quote_fr"]
        if doc is None or quote is None:
            errors.append(f"Gold {gid}: verdict {item['verdict']!r} exige document et evidence_quote_fr")
            continue
        if doc not in docs:
            errors.append(f"Gold {gid}: document introuvable {doc!r}")
            continue
        if len(quote) > MAX_QUOTE_CHARS:
            errors.append(f"Gold {gid}: citation trop longue ({len(quote)} > {MAX_QUOTE_CHARS} caractères)")
        if nfc(quote) not in docs[doc]:
            errors.append(f"Gold {gid}: la citation n'est pas une sous-chaîne exacte de {doc} : {quote[:80]!r}…")
    return errors


def coverage_report(gold: dict, kb: dict) -> str:
    by_verdict = Counter(item["verdict"] for item in gold["items"])
    kb_domain = {e["id"]: e["domain"] for e in kb["requirements"]}
    by_domain: Counter[str] = Counter(
        kb_domain.get(item["requirement_id"], "?") for item in gold["items"]
    )
    lines = ["", "Couverture du gold set :", f"  items: {len(gold['items'])}"]
    lines.append("  par verdict : " + ", ".join(f"{v}={n}" for v, n in sorted(by_verdict.items())))
    lines.append("  par domaine : " + ", ".join(f"{d}={n}" for d, n in sorted(by_domain.items())))
    return "\n".join(lines)


def run() -> list[str]:
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    docs = {p.name: nfc(p.read_text(encoding="utf-8")) for p in sorted(DOCS_DIR.glob("*.md"))}

    errors, kb_ids = check_kb(kb)
    errors += check_gold(gold, kb_ids, docs)

    # Versions immuables : KB et gold doivent porter la même version de corpus
    kb_v = kb["meta"].get("corpus_version")
    gold_v = gold["meta"].get("corpus_version")
    if not kb_v or kb_v != gold_v:
        errors.append(f"corpus_version incohérente : KB={kb_v!r} vs gold={gold_v!r}")

    # Couverture : chaque exigence de la KB doit avoir au moins un cas gold
    covered = {i["requirement_id"] for i in gold["items"]}
    for rid in sorted(kb_ids - covered):
        errors.append(f"Exigence KB {rid} sans aucun cas gold")

    # Documents référencés au moins une fois
    referenced = {i["document"] for i in gold["items"] if i["document"]}
    for name in docs:
        if name not in referenced:
            errors.append(f"Document {name} jamais référencé par le gold set")

    print(f"KB : {len(kb_ids)} exigences · Documents : {len(docs)} · Gold : {len(gold['items'])} items")
    print(coverage_report(gold, kb))
    return errors


def main() -> int:
    errors = run()
    if errors:
        print(f"\n{len(errors)} erreur(s) :", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("\nToutes les vérifications passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
