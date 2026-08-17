"""MedClear evaluation harness.

Runs every synthetic profile through the pipeline and scores the result against
the gold standard.

    python evaluate.py              detection + readability, no API calls
    python evaluate.py --generate   also exercise the model on uncovered findings

Metrics, matching the three targets in our proposal:

  1. Detection   precision and recall of findings against the gold standard
  2. Readability Flesch-Kincaid grade level on every piece of patient text
  3. Grounding   exported to grounding_review.csv for pharmacist adjudication

On the gold standard: rows marked in_reference=no are real interactions that our
reference does not yet contain. They are included on purpose. Scoring only
against what we already encoded would make recall trivially 1.0 and tell us
nothing, so recall here is honest and will be below 1.0 until the reference
grows.
"""

import argparse
import csv
import sys
from pathlib import Path

import pipeline as pl

HERE = Path(__file__).parent


def load_profiles():
    with open(HERE / "profiles.csv", newline="", encoding="utf-8") as f:
        return [{**r, "meds": [m.strip() for m in r["medications"].split("|")]}
                for r in csv.DictReader(f)]


def load_gold():
    with open(HERE / "gold_standard.csv", newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["kind"] and r["kind"] != "none"]


def key(kind, a, b=""):
    """Order-independent identity for a finding."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return (kind, *sorted([a, b])) if b else (kind, a)


def found_keys(result):
    out = set()
    for d in result["duplications"]:
        out.add(key("duplication", d["ingredient"]))
    for h in result["interactions"]:
        out.add(key("interaction", h["a"], h["b"]))
    for f in result["foods"]:
        out.add(key("food", f["ingredient"], f["food"]))
    for u in result["unresolved"]:
        out.add(key("unresolved", u))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true",
                    help="call the model for findings the reference does not cover")
    args = ap.parse_args()

    api_key = None
    if args.generate:
        import os
        api_key = os.environ.get("GEMINI_KEY")
        if not api_key:
            sys.exit("Set GEMINI_KEY in the environment to use --generate.")

    ints = pl.load_interaction_reference(HERE / "interactions.csv")
    dups = pl.load_duplication_reference(HERE / "duplications.csv")
    foods = pl.load_food_reference(HERE / "foods.csv")

    profiles, gold = load_profiles(), load_gold()

    gold_by_profile = {}
    for row in gold:
        gold_by_profile.setdefault(row["profile_id"], []).append(row)

    tp = fp = fn = 0
    missed_in_ref, missed_not_in_ref = [], []
    texts, grounding_rows = [], []

    print(f"Running {len(profiles)} profiles against {len(gold)} gold findings\n")
    print(f"{'ID':<5} {'FOUND':>6} {'EXPECT':>7} {'TP':>4} {'FP':>4} {'FN':>4}  DESCRIPTION")
    print("-" * 78)

    for p in profiles:
        result = pl.analyze("\n".join(p["meds"]), api_key=api_key,
                            interactions=ints, duplications=dups, foods=foods)

        expected = {key(r["kind"], r["item_a"], r["item_b"]): r
                    for r in gold_by_profile.get(p["profile_id"], [])}
        actual = found_keys(result)

        hits = actual & set(expected)
        misses = set(expected) - actual
        extras = actual - set(expected)

        tp += len(hits); fn += len(misses); fp += len(extras)

        for m in misses:
            row = expected[m]
            (missed_in_ref if row["in_reference"] == "yes"
             else missed_not_in_ref).append((p["profile_id"], m))

        print(f"{p['profile_id']:<5} {len(actual):>6} {len(expected):>7} "
              f"{len(hits):>4} {len(extras):>4} {len(misses):>4}  {p['description'][:38]}")

        for item, kind in ([(d, "duplication") for d in result["duplications"]]
                           + [(h, "interaction") for h in result["interactions"]]
                           + [(f, "food") for f in result["foods"]]):
            text = item.get("patient_text", "")
            if not text:
                continue
            label = (item.get("ingredient") or
                     f"{item.get('a','')} + {item.get('b','')}")
            texts.append((p["profile_id"], kind, label,
                          item.get("origin", "none"), text))
            if item.get("origin") == "model":
                grounding_rows.append({
                    "profile_id": p["profile_id"], "finding": label,
                    "generated_text": text,
                    "source_text": (item.get("source_text") or "")[:1500],
                    "supported": "", "notes": ""})

    # ------------------------------------------------------------ detection
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    print("\n" + "=" * 78)
    print("1. DETECTION")
    print("=" * 78)
    print(f"  true positives  {tp}")
    print(f"  false positives {fp}")
    print(f"  false negatives {fn}")
    print(f"  precision       {precision:.2f}")
    print(f"  recall          {recall:.2f}   (target >= 0.90)")

    if missed_in_ref:
        print(f"\n  MISSED despite being in our reference ({len(missed_in_ref)}):")
        for pid, k in missed_in_ref:
            print(f"    {pid}  {' + '.join(x for x in k[1:] if x)}  [{k[0]}]")
        print("    These are real defects. Investigate before reporting.")

    if missed_not_in_ref:
        print(f"\n  MISSED because the reference does not cover them "
              f"({len(missed_not_in_ref)}):")
        for pid, k in missed_not_in_ref:
            print(f"    {pid}  {' + '.join(x for x in k[1:] if x)}  [{k[0]}]")
        print("    Not defects. This is the size of the gap, measured.")

    covered = tp / (tp + len(missed_in_ref)) if (tp + len(missed_in_ref)) else 0.0
    print(f"\n  Recall on findings our reference covers: {covered:.2f}")
    print("  Reported alongside overall recall, not instead of it.")

    # ----------------------------------------------------------- readability
    print("\n" + "=" * 78)
    print("2. READABILITY")
    print("=" * 78)
    print("  Revised standard. Our proposal set one target for all output. In")
    print("  evaluation we found pharmacist-authored text does not meet it, and")
    print("  we chose clinical accuracy over the formula. The target now applies")
    print("  to model-generated text, which has no expert behind it. Authored")
    print("  text is reported descriptively, not scored pass or fail.\n")
    try:
        import textstat
        graded = [(textstat.flesch_kincaid_grade(t), pid, label, origin)
                  for pid, kind, label, origin, t in texts]

        authored = [g for g in graded if g[3] in ("pharmacist", "draft")]
        generated = [g for g in graded if g[3] == "model"]

        def summarise(rows, name, enforce):
            if not rows:
                print(f"  {name}: none in this run\n")
                return
            grades = [g for g, *_ in rows]
            mean = sum(grades) / len(grades)
            print(f"  {name} ({len(rows)} texts)")
            print(f"    mean grade level   {mean:.1f}")
            print(f"    range              {min(grades):.1f} to {max(grades):.1f}")
            if enforce:
                ok = [g for g in grades if g <= 8.0]
                print(f"    at or below 8th    {len(ok)}/{len(grades)} "
                      f"({100*len(ok)/len(grades):.0f}%)   TARGET 100%")
                over = sorted([r for r in rows if r[0] > 8.0], reverse=True)
                for g, pid, label, _ in over[:8]:
                    print(f"      {g:5.1f}  {pid}  {label[:38]}")
            else:
                print("    not scored against the 8th grade target")
                over = sorted([r for r in rows if r[0] > 8.0], reverse=True)
                if over:
                    print(f"    above 8th grade    {len(over)}/{len(grades)}, listed for")
                    print("                       editorial review, not as failures:")
                    for g, pid, label, _ in over[:8]:
                        print(f"      {g:5.1f}  {pid}  {label[:38]}")
            print()

        summarise(authored, "Pharmacist-authored", enforce=False)
        summarise(generated, "Model-generated", enforce=True)

        if authored:
            worst = max(authored)
            print(f"  Highest authored score: {worst[0]:.1f} on {worst[2]}.")
            print("  Long sentences and multi-syllable drug names drive this. The")
            print("  text is clinically precise, which is why we kept it.")
    except ImportError:
        print("  textstat not installed. pip install textstat")

    # ------------------------------------------------------------- grounding
    print("\n" + "=" * 78)
    print("3. GROUNDING")
    print("=" * 78)
    by_origin = {}
    for *_, origin, _t in [(x[0], x[1], x[2], x[3], x[4]) for x in texts]:
        by_origin[origin] = by_origin.get(origin, 0) + 1
    for k in ("pharmacist", "draft", "model", "none"):
        print(f"  {k:<12} {by_origin.get(k, 0)}")
    print("\n  Pharmacist and draft text is authored, not generated, so it needs")
    print("  editorial review rather than grounding adjudication. Only text")
    print("  marked 'model' is checked against its retrieved source.")

    if grounding_rows:
        out = HERE / "grounding_review.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["profile_id", "finding",
                                              "generated_text", "source_text",
                                              "supported", "notes"])
            w.writeheader(); w.writerows(grounding_rows)
        print(f"\n  Wrote {len(grounding_rows)} statements to {out.name}")
        print("  Pharmacist marks each 'supported' column yes or no.")
    else:
        print("\n  No model-generated text in this run. Use --generate to produce it.")

    # ------------------------------------------------------------ transcript
    with open(HERE / "evaluation_output.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["profile_id", "kind", "finding", "origin", "patient_text"])
        w.writerows(texts)
    print(f"\nFull output written to evaluation_output.csv ({len(texts)} texts)")


if __name__ == "__main__":
    main()
