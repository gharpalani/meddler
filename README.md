# MedClear

Understand your medications in plain language.

A patient enters their medication list. MedClear resolves each entry to its
active ingredients, flags medicines that share an ingredient, checks pairs
against a pharmacist-reviewed reference, and rewrites the relevant FDA label
text at an 8th grade reading level.

**Design principle: the model explains findings, it never decides whether one
exists.** Detection is a deterministic lookup. Only explanation is generative,
and the model sees nothing but retrieved label text.

---

## Files

| File | What it is |
|---|---|
| `pipeline.py` | All the logic. No Streamlit import, so it runs from a plain shell. |
| `app.py` | The Streamlit interface. |
| `duplications.csv` | Same-ingredient reference. Pharmacist-owned. |
| `interactions.csv` | Drug-drug reference. Pharmacist-owned. |
| `foods.csv` | Drug-food reference. Pharmacist-owned. |
| `catalog.csv` | Names offered in the picker. Not a limit — see below. |
| `requirements.txt` | Dependencies. |

| `requirements.txt` | Dependencies. |

---

## Run it locally

```bash
pip install -r requirements.txt
export GEMINI_KEY="your-key-here"
streamlit run app.py
```

Opens at `http://localhost:8501`.

Without a key the app still runs — drug resolution and duplicate-ingredient
detection work, since those use free public APIs with no authentication. Only
the plain-language rewriting needs the key.

---

## Deploy free, get a public URL

1. Push this folder to a GitHub repository. **Do not commit an API key.**
2. Go to `share.streamlit.io` and sign in with GitHub.
3. Click **New app**, pick the repo, set the main file to `app.py`.
4. Open **Advanced settings → Secrets** and paste:

   ```toml
   GEMINI_KEY = "your-key-here"
   ```

5. Deploy. You get a public URL that works on a phone.

Secrets live in Streamlit's settings, never in the repository. If a key is ever
committed by accident, revoke it in Google AI Studio and issue a new one —
rotating is the fix, deleting the commit is not.

---

## The interaction reference

Three files, all owned by our Pharmacy team member. The app loads them at
startup; no code changes are needed when they grow.

| File | Catches | Columns |
|---|---|---|
| `duplications.csv` | Same ingredient in two products | ingredient, action, reviewed, patient_text |
| `interactions.csv` | Two different drugs that clash | drug_a, drug_b, action, reviewed, patient_text |
| `foods.csv` | Food or drink to watch | ingredient, food, action, reviewed, patient_text |

**Precedence rule.** Where `patient_text` is filled in, the app shows that text
verbatim and labels it "Written by our pharmacist." The model is only asked to
write for findings the pharmacist has not covered, and that output is labelled
"Generated from the FDA label" so a reader always knows which they are looking
at. We do not have a language model paraphrase a pharmacist.

**Columns.**

- **Drug names** — active ingredient, lowercase, generic not brand. Match
  RxNorm ingredient names (`warfarin`, not `Coumadin`). Brand names still work
  as *input* because RxNorm resolves them; the reference file is keyed on
  ingredients so `Tums` and `calcium carbonate` both match the same row.
- **action** — `now`, `next_visit`, or `aware`. This is urgency for the
  patient, not abstract severity. A "major" interaction the prescriber already
  monitors is `next_visit`; a moderate one needing a call today is `now`.
- **reviewed** — `yes` once a pharmacist has approved the wording. Anything
  marked `no` is displayed as "Draft — awaiting pharmacist review."
- **patient_text** — what the patient reads, verbatim. Write it the way you
  would say it at the counter. Leave blank to let the model generate from the
  FDA label instead.

If a file is missing or empty, the app says plainly that the check is not
active rather than implying a list is clear.


### Questions

Each row carries a `questions` column: pipe-separated questions for the patient
to ask, with placeholders filled in from their own list.

- `{PRODUCTS}` — the patient's products sharing that ingredient
- `{A}` / `{B}` — the patient's product names for `drug_a` and `drug_b`
- `{ING}` / `{FOOD}` — the ingredient and the food

So `"If I take my {A} at 7 in the morning, when is the earliest I can take my
{B}?"` becomes `"If I take my Synthroid at 7 in the morning, when is the
earliest I can take my Tums?"` — the patient's own brand names, not ours.

This is arguably the highest-value column. A patient who reaches the counter
asking "when exactly can I take my Tums?" gets a far better five minutes than
one asking "is this okay?"

---

## The medication picker

`catalog.csv` supplies the names offered in the dropdown. **It is not a limit.**
The picker accepts free text, and anything typed is resolved against RxNorm the
same way — the catalog only makes common medications faster to select and shows
a description so patients recognise them.

---

## Known limitations

These are real and should stay visible in the interface.

- **openFDA does not carry every label section.** In our audit of 27 common
  medications, all 27 resolved to ingredients but only 19 had a usable
  interactions section. Where text is missing, the app declines to explain
  rather than generating an answer without a source.
- **Some products do not resolve.** OTC combination brands are the weak spot.
  Unresolved entries are surfaced to the user, never treated as safe.
- **The reference is a curated subset, not exhaustive.** Absence of a flag is
  not evidence of safety, and the interface should never imply otherwise.
- **Spanish output cannot be reviewed to the same standard** unless a
  Spanish-reading pharmacist reviews it.

---

## Testing the pipeline without the UI

```python
import pipeline as pl

ref = pl.load_interaction_reference("interactions.csv")
result = pl.analyze("Norco\nTylenol Extra Strength\nwarfarin\nibuprofen",
                    api_key=None, reference=ref)

print(result["duplications"])
print(result["interactions"])
print(result["unresolved"])
```

Passing `api_key=None` skips generation, so detection can be tested offline and
without spending quota.

---

Course prototype. Synthetic profiles only. No patient data is collected or
stored. MedClear does not diagnose and does not tell anyone to start or stop a
medication.
