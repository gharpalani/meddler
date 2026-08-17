"""MedClear pipeline.

Governing design principle: the language model explains findings, it never
decides whether one exists. Steps 1-3 are deterministic lookups against public
references. Only step 4 is generative, and it sees nothing but retrieved text.

    1. normalize   free text  -> RxNorm concepts
    2. detect      concepts   -> shared ingredients + reference interactions
    3. retrieve    findings   -> the matching FDA label section
    4. explain     label text -> plain language (model, grounded)

No module-level network calls. Nothing here imports Streamlit, so the whole
pipeline can be tested from a plain Python shell.
"""

from __future__ import annotations

import csv
import io
import re
from functools import lru_cache

import requests

RXNAV = "https://rxnav.nlm.nih.gov/REST"
OPENFDA = "https://api.fda.gov/drug/label.json"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

TIMEOUT = 20

# RxNorm term types, most specific first. IN is a single active ingredient.
# BPCK and GPCK are combination PACKS: a pack containing amoxicillin also
# contains clarithromycin, so matching one for a query of "amoxicillin" would
# report ingredients the patient is not taking.
TTY_ORDER = ["IN", "PIN", "MIN", "SCD", "SBD", "SCDC", "SBDC", "GPCK", "BPCK"]

DOSAGE_WORDS = [
    "inhaler", "tablet", "tablets", "capsule", "capsules", "pen", "pens",
    "vial", "vials", "cream", "ointment", "solution", "injection",
    "suspension", "syrup", "patch", "spray", "drops", "gel",
]

ACTION_LABELS = {
    "now": "Do something now",
    "next_visit": "Bring up at your next visit",
    "aware": "Just be aware",
}
ACTION_RANK = {"now": 0, "next_visit": 1, "aware": 2}


# ---------------------------------------------------------------- normalize

def clean_entry(raw: str) -> list[str]:
    """Turn one free-text line into one or more candidate drug names.

    Real medication lists are messy: parentheticals, "or" alternatives,
    dosage-form suffixes, inconsistent casing. Returns a list because a single
    line can name more than one drug ("ibuprofen or tylenol").
    """
    s = (raw or "").strip().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\b\d+(\.\d+)?\s?(mg|mcg|g|ml|units?|iu)\b", " ", s)
    out = []
    for part in re.split(r"\bor\b|,|/", s):
        part = part.strip()
        for word in DOSAGE_WORDS:
            part = re.sub(rf"\b{word}\b", " ", part)
        part = re.sub(r"\s+", " ", part).strip(" -.")
        if part:
            out.append(part)
    return out


@lru_cache(maxsize=512)
def _is_ingredient(term: str) -> str | None:
    """Ask RxNorm directly whether this name IS an active ingredient.

    This is the fix for a false positive found in evaluation. Querying /drugs
    for "omeprazole" returns product concepts, including an aspirin/omeprazole
    combination, and our code attributed aspirin to a patient who was not
    taking it, producing a bleeding-risk warning that did not exist.

    Ranking candidates by term type was not enough, because /drugs did not
    return an IN concept to rank to the front. The reliable question is asked
    of a different endpoint: /rxcui with tty=IN matches only when the name is
    itself an ingredient.
    """
    try:
        r = requests.get(f"{RXNAV}/rxcui.json",
                         params={"name": term, "search": 0, "tty": "IN"},
                         timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        ids = (r.json().get("idGroup", {}) or {}).get("rxnormId") or []
        return ids[0] if ids else None
    except requests.RequestException:
        return None


@lru_cache(maxsize=512)
def _rxnorm_candidates(term: str) -> tuple:
    """Candidate RxCUIs for a name, single ingredients ranked first."""
    found = []
    try:
        r = requests.get(f"{RXNAV}/drugs.json", params={"name": term},
                         timeout=TIMEOUT)
        if r.status_code == 200:
            for group in (r.json().get("drugGroup", {}).get("conceptGroup") or []):
                tty = group.get("tty")
                for cp in (group.get("conceptProperties") or []):
                    found.append((cp.get("rxcui"), cp.get("name"), tty))
    except requests.RequestException:
        pass

    if not found:
        try:
            r = requests.get(f"{RXNAV}/approximateTerm.json",
                             params={"term": term, "maxEntries": 3},
                             timeout=TIMEOUT)
            if r.status_code == 200:
                cands = r.json().get("approximateGroup", {}).get("candidate") or []
                if cands:
                    found.append((cands[0].get("rxcui"), None, "fuzzy"))
        except requests.RequestException:
            pass

    found.sort(key=lambda c: TTY_ORDER.index(c[2]) if c[2] in TTY_ORDER else 99)
    return tuple(found)


@lru_cache(maxsize=512)
def _ingredients_via_rxnorm(term: str) -> tuple:
    """Stage 1: RxNorm, preferring an exact single-ingredient match."""
    for rxcui, cname, tty in _rxnorm_candidates(term)[:5]:
        # If the typed name IS an ingredient, stop. Walking out to products
        # from here is how a combination pack adds ingredients the patient
        # does not actually have in hand.
        if tty == "IN":
            return ((cname or term).lower(),), "RxNorm/IN"
        try:
            r = requests.get(f"{RXNAV}/rxcui/{rxcui}/related.json",
                             params={"tty": "IN"}, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            names = []
            for g in (r.json().get("relatedGroup", {}).get("conceptGroup") or []):
                for cp in (g.get("conceptProperties") or []):
                    if cp.get("name"):
                        names.append(cp["name"].lower())
            if names:
                return tuple(sorted(set(names))), f"RxNorm/{tty}"
        except requests.RequestException:
            continue
    return (), None


@lru_cache(maxsize=512)
def _ingredients_via_openfda(term: str) -> tuple:
    """Stage 2: the FDA label index, which carries OTC brand names directly."""
    for field in ("openfda.brand_name", "openfda.generic_name"):
        try:
            r = requests.get(OPENFDA,
                             params={"search": f'{field}:"{term}"', "limit": 1},
                             timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            hits = r.json().get("results", [])
            if not hits:
                continue
            subs = hits[0].get("openfda", {}).get("substance_name") or []
            subs = sorted({s.lower() for s in subs if s})
            if subs:
                return tuple(subs), f"openFDA/{field.split('.')[-1]}"
        except requests.RequestException:
            continue
    return (), None


def resolve_ingredients(term: str) -> tuple[list[str], str | None]:
    """Resolve a product name to its active ingredients.

    Order matters. Ingredient names resolve to themselves and never touch
    product lookup. Only brand and combination names go on to products.

    Returns (ingredients, source). An empty list means we could not identify
    it, which the interface must surface rather than treat as safe.
    """
    clean = (term or "").strip().lower()

    # Stage 0: is this an active ingredient in its own right? If so, stop.
    # Going on to product lookup from here is how a combination product adds
    # ingredients the patient does not actually have in hand.
    if _is_ingredient(clean):
        return [clean], "RxNorm/IN"

    ings, src = _ingredients_via_rxnorm(term)
    if not ings:
        ings, src = _ingredients_via_openfda(term)
    return list(ings), src


# ----------------------------------------------------------------- retrieve

@lru_cache(maxsize=256)
def get_label_section(term: str, section: str = "drug_interactions") -> str:
    """Fetch one section of the FDA label for a drug. Empty string if absent."""
    for field in ("openfda.generic_name", "openfda.brand_name"):
        try:
            r = requests.get(OPENFDA,
                             params={"search": f'{field}:"{term}"', "limit": 1},
                             timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            hits = r.json().get("results", [])
            if not hits:
                continue
            text = (hits[0].get(section) or [None])[0]
            if text:
                return text
        except requests.RequestException:
            continue
    return ""


# ------------------------------------------------------------------- detect

def find_duplications(resolved: list[dict],
                     reference: list[dict] | None = None) -> list[dict]:
    """Flag any active ingredient appearing in more than one product.

    This is the acetaminophen case: Norco and Tylenol look like different drugs
    to a patient but share an ingredient, and the daily total adds up.
    """
    reference = reference or []
    by_text = {r["ingredient"]: r for r in reference}

    by_ingredient: dict[str, list[str]] = {}
    for item in resolved:
        for ing in item["ingredients"]:
            by_ingredient.setdefault(ing, []).append(item["typed"])

    out = []
    for ing, products in by_ingredient.items():
        if len(set(products)) < 2:
            continue
        entry = {"ingredient": ing, "products": sorted(set(products)),
                 "action": "now", "patient_text": "", "reviewed": False,
                 "questions": []}
        hit = by_text.get(ing)
        if hit:
            entry["action"] = hit["action"]
            entry["patient_text"] = hit["patient_text"]
            entry["reviewed"] = hit["reviewed"]
            entry["questions"] = [q.replace("{PRODUCTS}",
                                            " and ".join(entry["products"]))
                                  .replace("{ING}", ing)
                                  for q in hit["questions"]]
        out.append(entry)
    return sorted(out, key=lambda d: (ACTION_RANK[d["action"]], -len(d["products"])))


def find_food_interactions(resolved: list[dict],
                           reference: list[dict]) -> list[dict]:
    """Foods and drinks to watch, based on what the patient already takes.

    We do not ask patients to list what they eat. We look up their medicines
    and surface the foods that matter for those.
    """
    if not reference:
        return []

    owner: dict[str, list[str]] = {}
    for item in resolved:
        for ing in item["ingredients"]:
            owner.setdefault(ing, []).append(item["typed"])

    out = []
    for row in reference:
        if row["ingredient"] not in owner:
            continue
        out.append({
            "ingredient": row["ingredient"],
            "food": row["food"],
            "products": sorted(set(owner[row["ingredient"]])),
            "action": row["action"],
            "patient_text": row["patient_text"],
            "reviewed": row["reviewed"],
            "questions": [q.replace("{ING}", owner[row["ingredient"]][0])
                           .replace("{FOOD}", row["food"])
                          for q in row["questions"]],
        })
    return sorted(out, key=lambda d: ACTION_RANK[d["action"]])


def _open_source(source):
    """Accept a path, a file-like object, or raw CSV text."""
    if source is None:
        return None
    try:
        if hasattr(source, "read"):
            return io.StringIO(_as_text(source.read()))
        if isinstance(source, str) and "\n" in source:
            return io.StringIO(source)
        return open(source, newline="", encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _rows(source, required: tuple[str, ...]) -> list[dict]:
    handle = _open_source(source)
    if handle is None:
        return []
    out = []
    with handle:
        for row in csv.DictReader(handle):
            values = {k: (row.get(k) or "").strip() for k in required}
            if not all(values.values()):
                continue
            action = (row.get("action") or "aware").strip().lower()
            entry = {k: v.lower() for k, v in values.items()}
            entry["action"] = action if action in ACTION_RANK else "aware"
            entry["reviewed"] = (row.get("reviewed") or "no").strip().lower() == "yes"
            entry["patient_text"] = (row.get("patient_text") or "").strip()
            entry["questions"] = [q.strip() for q in
                                  (row.get("questions") or "").split("|")
                                  if q.strip()]
            out.append(entry)
    return out


def load_interaction_reference(source) -> list[dict]:
    """Drug-drug pairs. Columns: drug_a, drug_b, action, reviewed, patient_text."""
    return _rows(source, ("drug_a", "drug_b"))


def load_duplication_reference(source) -> list[dict]:
    """Same-ingredient entries. Columns: ingredient, action, reviewed, patient_text."""
    return _rows(source, ("ingredient",))


def load_food_reference(source) -> list[dict]:
    """Drug-food entries. Columns: ingredient, food, action, reviewed, patient_text."""
    return _rows(source, ("ingredient", "food"))


def _as_text(data) -> str:
    return data.decode("utf-8") if isinstance(data, bytes) else str(data)


def find_interactions(resolved: list[dict], reference: list[dict]) -> list[dict]:
    """Check every ingredient pair against the reference. Pure lookup."""
    if not reference:
        return []

    owner: dict[str, list[str]] = {}
    for item in resolved:
        for ing in item["ingredients"]:
            owner.setdefault(ing, []).append(item["typed"])

    ingredients = sorted(owner)
    index = {(r["drug_a"], r["drug_b"]): r for r in reference}
    index.update({(r["drug_b"], r["drug_a"]): r for r in reference})

    out = []
    for i, a in enumerate(ingredients):
        for b in ingredients[i + 1:]:
            hit = index.get((a, b))
            if not hit:
                continue
            out.append({
                "a": a, "b": b,
                "products": sorted(set(owner[a] + owner[b])),
                "action": hit["action"],
                "patient_text": hit["patient_text"],
                "reviewed": hit["reviewed"],
                # Bind {A}/{B} to the reference row's own order, not the
                # alphabetical pair order, or the question comes out reversed.
                "questions": [
                    q.replace("{A}", owner.get(hit["drug_a"], [hit["drug_a"]])[0])
                     .replace("{B}", owner.get(hit["drug_b"], [hit["drug_b"]])[0])
                    for q in hit["questions"]],
            })
    return sorted(out, key=lambda d: ACTION_RANK[d["action"]])


# ------------------------------------------------------------------ explain

# House style, written by our Pharmacy team member. Generated text should be
# indistinguishable in voice from the pharmacist-authored entries in the CSVs.
SYSTEM_PROMPT = """You are a patient education assistant writing in the voice of
a community pharmacist speaking to a patient at the counter.

Rules you must follow:
1. Use ONLY the FDA label text provided. Do not use any outside knowledge.
2. If the provided text does not answer the question, say exactly:
   "The label section I was given does not cover this."
3. Never diagnose. Never tell the patient to start or stop a medication.

House style, follow it closely:
4. Open with a direct recommendation. Use phrasing like "It is not recommended
   to take X with Y" or "It is recommended to separate X and Y by at least N
   hours." State the recommendation before the reason.
5. Give the specific timing or action in numbers whenever the label supports it
   (for example "at least 2 hours", "at least 4 hours").
6. Explain the mechanism in one plain sentence. Say what each medicine does,
   not how it works biochemically.
7. Capitalize medicine names as a patient would see them on the bottle.
8. If the label describes a whole group, name the group. For example: products
   containing calcium, iron, magnesium, or aluminum.
9. Write at an 8th grade reading level. Short sentences. No medical jargon.
10. Keep the whole answer under 110 words.
11. End with exactly: "Ask your pharmacist for more information."

Example of the target voice:
"You should separate your Doxycycline and Calcium carbonate by at least 2
hours. Calcium carbonate will block the body from absorption of Doxycycline.
It is also recommended to separate taking products that include calcium,
aluminum, iron, zinc, and magnesium by at least 2 hours before and after taking
Doxycycline. Ask your pharmacist for more information." """

SYSTEM_PROMPT_ES = SYSTEM_PROMPT.replace(
    "3. Write at an 8th grade reading level. Short sentences. No medical jargon.",
    "3. Responde en espanol. Nivel de lectura de octavo grado. Frases cortas. "
    "Sin jerga medica.",
).replace(
    '   "The label section I was given does not cover this."',
    '   "La seccion de la etiqueta que recibi no cubre esto."',
)


@lru_cache(maxsize=8)
def pick_model(api_key: str) -> str | None:
    """Ask the API which models this key can call.

    Model identifiers are retired on the provider's schedule, not ours, so we
    discover rather than hardcode. A hardcoded name broke this project once
    already.
    """
    try:
        r = requests.get(f"{GEMINI_BASE}/models",
                         headers={"x-goog-api-key": api_key}, timeout=30)
        if r.status_code != 200:
            return None
        usable = [
            m["name"].replace("models/", "")
            for m in r.json().get("models", [])
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]
    except requests.RequestException:
        return None

    for want in ("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"):
        if want in usable:
            return want
    flash = [m for m in usable
             if "flash" in m and not any(x in m for x in
                                         ("image", "tts", "live", "preview"))]
    return sorted(flash)[-1] if flash else (usable[0] if usable else None)


def explain(question: str, label_text: str, api_key: str,
            language: str = "en") -> tuple[str, bool]:
    """Generate a plain-language answer grounded in label_text.

    Returns (text, ok). The model receives the label text and nothing else, so
    when it says the label does not cover something, that is literally true.
    """
    if not label_text.strip():
        return ("", False)
    model = pick_model(api_key)
    if not model:
        return ("", False)

    system = SYSTEM_PROMPT_ES if language == "es" else SYSTEM_PROMPT
    prompt = (f'FDA LABEL TEXT:\n"""\n{label_text[:6000]}\n"""\n\n'
              f"PATIENT QUESTION: {question}")
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    try:
        r = requests.post(f"{GEMINI_BASE}/models/{model}:generateContent",
                          headers={"x-goog-api-key": api_key,
                                   "Content-Type": "application/json"},
                          json=body, timeout=90)
        if r.status_code != 200:
            return ("", False)
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return (text.strip(), True)
    except (requests.RequestException, KeyError, IndexError):
        return ("", False)


# ------------------------------------------------------------------ analyze

def analyze(med_text: str, api_key: str | None = None,
            interactions: list[dict] | None = None,
            duplications: list[dict] | None = None,
            foods: list[dict] | None = None,
            language: str = "en") -> dict:
    """Run the whole pipeline over a free-text medication list.

    Precedence rule: where our pharmacist has written the patient-facing text,
    we show it verbatim. The model is only asked to write for findings she has
    not covered, and its output is labelled differently in the interface so a
    reader always knows which they are looking at.

    Returns a plain dict so any interface can render it.
    """
    interactions = interactions or []
    duplications = duplications or []
    foods = foods or []

    resolved, unresolved = [], []
    for line in (med_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for name in clean_entry(line) or [line]:
            ings, src = resolve_ingredients(name)
            resolved.append({"typed": line, "cleaned": name,
                             "ingredients": ings, "source": src})
            if not ings:
                unresolved.append(line)

    dup_found = find_duplications(resolved, duplications)
    int_found = find_interactions(resolved, interactions)
    food_found = find_food_interactions(resolved, foods)

    def fill(finding, question, label_term):
        """Pharmacist text wins. Model only fills gaps."""
        if finding.get("patient_text"):
            finding["origin"] = "pharmacist"
            finding["source_text"] = ""
            return
        if not api_key:
            finding["origin"] = "none"
            finding["source_text"] = ""
            return
        label = get_label_section(label_term)
        text, ok = explain(question, label, api_key, language)
        finding["patient_text"] = text
        finding["origin"] = "model" if ok else "none"
        finding["source_text"] = label if ok else ""

    for dup in dup_found:
        fill(dup,
             f"A patient takes {' and '.join(dup['products'])}. All of them "
             f"contain {dup['ingredient']}. Explain why taking them together "
             f"is a problem and what to do about it.",
             dup["ingredient"])

    for hit in int_found:
        fill(hit,
             f"A patient takes both {hit['a']} and {hit['b']}. Explain how "
             f"these affect each other and what the patient should do.",
             hit["a"])

    for food in food_found:
        fill(food,
             f"A patient takes {food['ingredient']}. Explain how "
             f"{food['food']} affects this medicine and what they should do.",
             food["ingredient"])

    return {
        "resolved": resolved,
        "unresolved": sorted(set(unresolved)),
        "duplications": dup_found,
        "interactions": int_found,
        "foods": food_found,
        "reference_loaded": bool(interactions),
        "reference_size": len(interactions) + len(duplications) + len(foods),
    }
