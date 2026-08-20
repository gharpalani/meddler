"""MedClear - Streamlit interface.

Run locally:   streamlit run app.py
Deploy free:   share.streamlit.io, pointed at this repo

The API key comes from Streamlit secrets, never from the code. See README.md.
"""

import csv
import os
from pathlib import Path

import streamlit as st

import pipeline as pl

HERE = Path(__file__).parent

st.set_page_config(page_title="MedClear", page_icon="💊", layout="centered")

st.markdown("""
<style>
:root{--ink:#14171a;--mid:#5c6470;--soft:#8b929c;--line:#e4e7ec;--card:#fff;
--wash:#f6f7f9;--teal:#1D9E75;--tealbg:#E4F5EF;--tealink:#0F6E56;
--amber:#8A5300;--amberbg:#FCF1DE;--red:#A32D2D;--redbg:#FDEDED;
--blue:#20567F;--bluebg:#EAF1F7;}

.stApp{background:var(--wash)}
#MainMenu, footer, header {visibility:hidden;}
.block-container{padding-top:2.6rem;padding-bottom:5rem;max-width:840px}

/* ---------- header ---------- */
.mc-head{display:flex;align-items:center;gap:15px;margin-bottom:2px}
.mc-head h1{margin:0;font-size:2.2rem;font-weight:650;letter-spacing:-.9px}
.mc-head .brand-tail{color:var(--teal)}
.mc-sub{color:var(--mid);margin:.15rem 0 1.7rem;font-size:1.04rem}

h2{font-size:1.28rem;font-weight:650;letter-spacing:-.3px;
   margin:2.4rem 0 .5rem;color:var(--ink)}

/* ---------- input panel ---------- */
div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stMultiSelect"]){
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:4px 20px 18px;box-shadow:0 1px 2px rgba(20,23,26,.04)}

div[data-testid="stMultiSelect"] label{font-weight:600;font-size:.86rem;
  color:var(--mid);letter-spacing:.01em}
div[data-testid="stMultiSelect"] div[data-baseweb="select"] > div{
  background:#fbfcfd;border:1px solid var(--line);border-radius:10px;
  min-height:48px}
div[data-testid="stMultiSelect"] div[data-baseweb="select"] > div:focus-within{
  border-color:var(--teal);box-shadow:0 0 0 3px rgba(29,158,117,.13)}
span[data-baseweb="tag"]{background:var(--teal) !important;border-radius:7px !important;
  font-weight:500}

/* ---------- buttons ---------- */
div.stButton > button{border-radius:9px;border:1px solid var(--line);
  background:var(--card);font-weight:500;color:var(--ink);
  transition:all .12s ease;box-shadow:0 1px 2px rgba(20,23,26,.04)}
div.stButton > button:hover{border-color:var(--teal);color:var(--tealink);
  background:var(--tealbg);transform:translateY(-1px)}
div.stButton > button[kind="primary"]{background:var(--teal);border-color:var(--teal);
  color:#fff;font-weight:600;padding:.55rem 1.4rem}
div.stButton > button[kind="primary"]:hover{background:var(--tealink);
  border-color:var(--tealink);color:#fff}

/* ---------- medication rows ---------- */
.mc-list{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:6px 20px;box-shadow:0 1px 2px rgba(20,23,26,.04)}
.mc-row{display:flex;gap:14px;align-items:baseline;padding:13px 0;
  border-bottom:1px solid #f0f2f5;flex-wrap:wrap}
.mc-row:last-child{border-bottom:0}
.mc-name{font-weight:600;min-width:190px;color:var(--ink)}
.mc-ing{color:var(--mid);flex:1;font-size:.94rem}
.mc-src{font-family:ui-monospace,Menlo,monospace;font-size:.68rem;background:#f0f2f5;
  color:var(--soft);padding:3px 9px;border-radius:5px;white-space:nowrap;
  letter-spacing:.02em}
.mc-src-fda{background:var(--tealbg);color:var(--tealink)}
.mc-src-miss{background:var(--redbg);color:var(--red)}

/* ---------- findings ---------- */
.mc-find{border-left:3px solid;border-radius:0 10px 10px 0;padding:15px 20px;
  margin:22px 0 0}
.mc-find.now{border-color:var(--red);background:var(--redbg)}
.mc-find.next_visit{border-color:var(--amber);background:var(--amberbg)}
.mc-find.aware{border-color:var(--blue);background:var(--bluebg)}
.mc-find .mc-tier{font-size:.64rem;text-transform:uppercase;letter-spacing:.09em;
  font-weight:700;margin-bottom:5px}
.mc-find.now .mc-tier{color:var(--red)}
.mc-find.next_visit .mc-tier{color:var(--amber)}
.mc-find.aware .mc-tier{color:var(--blue)}
.mc-find .mc-what{font-size:1.05rem;font-weight:600;color:var(--ink);
  line-height:1.45}

.mc-text{border-radius:10px;padding:17px 20px;margin:9px 0 4px;font-size:1rem;
  line-height:1.66}
.mc-pharmacist,.mc-model{background:var(--tealbg);color:#0b4a3a}
.mc-draft,.mc-none{background:var(--card);color:#3f4650;border:1px solid var(--line)}
.mc-who{font-size:.64rem;text-transform:uppercase;letter-spacing:.09em;
  font-weight:700;margin-bottom:8px}
.mc-pharmacist .mc-who,.mc-model .mc-who{color:var(--tealink)}
.mc-draft .mc-who{color:var(--amber)}
.mc-none .mc-who{color:var(--soft)}

/* ---------- questions ---------- */
.mc-qh{font-size:.66rem;text-transform:uppercase;letter-spacing:.09em;
  color:var(--soft);font-weight:700;margin:22px 0 8px}

/* ---------- misc ---------- */
div[data-testid="stExpander"]{border:1px solid var(--line);border-radius:12px;
  background:var(--card)}
hr{border-color:var(--line)}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ loading

def api_key() -> str | None:
    """Streamlit secrets first, then environment. Never hardcoded."""
    try:
        key = st.secrets.get("GEMINI_KEY")
        if key:
            return str(key).strip()
    except Exception:
        pass
    return (os.environ.get("GEMINI_KEY") or "").strip() or None


@st.cache_data(show_spinner=False)
def _load(name: str, mtime: float) -> list[dict]:
    loader = {"interactions.csv": pl.load_interaction_reference,
              "duplications.csv": pl.load_duplication_reference,
              "foods.csv": pl.load_food_reference}[name]
    return loader(HERE / name)


def reference(name: str) -> list[dict]:
    path = HERE / name
    return _load(name, path.stat().st_mtime) if path.exists() else []


@st.cache_data(show_spinner=False)
def catalog(mtime: float) -> list[str]:
    """Names offered in the picker. Not a limit: the picker accepts free text,
    and anything typed is resolved against RxNorm live."""
    path = HERE / "catalog.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [f"{r['name']} — {r['description']}" if r.get("description")
                else r["name"] for r in csv.DictReader(f)]


def catalog_names() -> list[str]:
    path = HERE / "catalog.csv"
    return catalog(path.stat().st_mtime) if path.exists() else []


@st.cache_data(show_spinner=False, ttl=3600)
def run(meds: tuple[str, ...], key: str | None, sig: int, lang: str) -> dict:
    return pl.analyze("\n".join(meds), api_key=key,
                      interactions=reference("interactions.csv"),
                      duplications=reference("duplications.csv"),
                      foods=reference("foods.csv"), language=lang)


WHO = {"pharmacist": "Written by our pharmacist",
       "draft": "Draft — awaiting pharmacist review",
       "model": "Generated from the FDA label",
       "none": "No reviewed wording and no label text"}


def finding(item, headline: str):
    """Render one finding. Its origin is always visible to the reader."""
    tier = item["action"]
    st.markdown(
        f'<div class="mc-find {tier}"><div class="mc-tier">'
        f'{pl.ACTION_LABELS[tier]}</div>'
        f'<div class="mc-what">{headline}</div></div>',
        unsafe_allow_html=True)

    origin = item.get("origin", "none")
    body = item.get("patient_text") or (
        "We have no reviewed wording and no label text for this, so we are not "
        "explaining it rather than guessing. Ask your pharmacist.")
    st.markdown(
        f'<div class="mc-text mc-{origin}"><div class="mc-who">{WHO[origin]}</div>'
        f'{body}</div>', unsafe_allow_html=True)
    if item.get("source_text"):
        with st.expander("Show the FDA label text this came from"):
            st.text(item["source_text"][:2500])


# --------------------------------------------------------------------- page

LOGO = """<svg width="52" height="27" viewBox="0 0 170 80">
<rect x="2" y="2" width="166" height="76" rx="38" fill="none" stroke="#14171a" stroke-width="4"/>
<g stroke="#8b929c" stroke-width="2.5">
<line x1="20" y1="18" x2="72" y2="18"/><line x1="20" y1="28" x2="72" y2="28"/>
<line x1="20" y1="38" x2="72" y2="38"/><line x1="20" y1="48" x2="72" y2="48"/>
<line x1="20" y1="58" x2="72" y2="58"/></g>
<line x1="85" y1="3" x2="85" y2="77" stroke="#14171a" stroke-width="4"/>
<g stroke="#1D9E75" stroke-width="7" stroke-linecap="round">
<line x1="100" y1="26" x2="150" y2="26"/><line x1="100" y1="42" x2="150" y2="42"/>
<line x1="100" y1="58" x2="134" y2="58"/></g></svg>"""

st.markdown(f'<div class="mc-head">{LOGO}<h1>Med<span class="brand-tail">Clear</span></h1></div>',
            unsafe_allow_html=True)
st.markdown('<p class="mc-sub">Understand your medications in plain language.</p>',
            unsafe_allow_html=True)

key = api_key()
ints = reference("interactions.csv")
dups = reference("duplications.csv")
foods = reference("foods.csv")
sig = len(ints) + len(dups) + len(foods)

with st.sidebar:
    st.subheader("Status")
    st.write("**Drug lookup** ✅ live")
    st.caption("RxNorm and openFDA. Public APIs, no key required.")
    st.write(f"**Plain language** {'✅ ready' if key else '⚠️ no API key'}")
    if not key:
        st.caption("Add GEMINI_KEY to Streamlit secrets to let the model write "
                   "for findings the pharmacist has not covered. Detection and "
                   "all pharmacist-written text work without it.")
    st.write(f"**Pharmacist reference** {sig} entries"
             if sig else "**Pharmacist reference** ⚠️ not loaded")
    pending = sum(1 for r in ints + dups + foods if not r["reviewed"])
    if sig:
        st.caption(f"{sig - pending} approved · {pending} awaiting review. "
                   f"Unreviewed entries are labelled in the results.")
    language = st.radio("Language", ["English", "Español"], index=0)
    st.divider()
    st.caption("Course prototype. Synthetic data only. No patient information "
               "is collected or stored.")

lang = "es" if language.startswith("Esp") else "en"

EXAMPLES = {
    "Norco + Tylenol": ["Norco", "Tylenol Extra Strength", "lisinopril"],
    "Thyroid + Tums": ["Synthroid", "Tums", "omeprazole"],
    "Warfarin + ibuprofen": ["warfarin", "ibuprofen", "metformin"],
    "Statin + grapefruit": ["atorvastatin", "doxycycline", "calcium carbonate"],
}

# We hold the list ourselves and give the widget a version-stamped key. A
# keyed widget ignores later writes to its own state, and an unkeyed widget
# ignores a changed `default`. Changing the key sidesteps both: Streamlit
# builds a new widget and honours the default we hand it.
if "meds_list" not in st.session_state:
    st.session_state.meds_list = list(EXAMPLES["Norco + Tylenol"])
if "picker_version" not in st.session_state:
    st.session_state.picker_version = 0

cols = st.columns(len(EXAMPLES))
for col, (label, value) in zip(cols, EXAMPLES.items()):
    if col.button(label, use_container_width=True):
        st.session_state.meds_list = list(value)
        st.session_state.picker_version += 1
        st.session_state.pop("result", None)
        st.rerun()

# Options must always contain the current selection, or Streamlit drops it.
options = sorted({*catalog_names(), *st.session_state.meds_list})

# ---- add from a photo ------------------------------------------------------
with st.expander("📷  Add from a photo of your medications"):
    if not key:
        st.info("Reading photos needs an API key. Add GEMINI_KEY to Streamlit "
                "secrets to turn this on. Typing names works without it.")
    else:
        st.caption("Photograph your bottles or a printed list. We read the names "
                   "and show them to you to confirm — nothing is checked until "
                   "you approve the list.")
        photo = st.file_uploader("Photo", type=["jpg", "jpeg", "png"],
                                 label_visibility="collapsed")

        if photo is not None and st.button("Read this photo"):
            with st.spinner("Reading the label…"):
                names, err = pl.extract_medications_from_image(
                    photo.getvalue(), photo.type, key)
            if err:
                st.error(err)
            elif not names:
                st.warning("We could not read any medication names in that photo. "
                           "Try better lighting, or type the names instead.")
            else:
                resolved = []
                for raw in names:
                    unclear = "(UNCLEAR)" in raw
                    clean = raw.replace("(UNCLEAR)", "").strip()
                    ings, source = pl.resolve_ingredients(clean)
                    resolved.append({"typed": clean, "ings": ings,
                                     "source": source, "unclear": unclear})
                st.session_state.photo_read = resolved

        found = st.session_state.get("photo_read")
        if found:
            st.markdown("**We read these. Check them before adding.**")
            for item in found:
                if item["ings"]:
                    note = " · image text was unclear" if item["unclear"] else ""
                    st.markdown(
                        f"- **{item['typed']}** — contains "
                        f"{', '.join(item['ings'])}{note}")
                else:
                    st.markdown(
                        f"- **{item['typed']}** — we could not identify this one. "
                        f"It is shown rather than dropped. Check it with your "
                        f"pharmacist.")

            usable = [i["typed"] for i in found if i["ings"]]
            c1, c2 = st.columns([1, 1])
            # Bumping picker_version gives the multiselect a new key, which
            # forces Streamlit to build a fresh widget that honours the new
            # default. Writing to an existing keyed widget's state does not
            # refresh it, which is why an earlier version reported "added"
            # while the list below stayed unchanged.
            if c1.button("Add these to my list", type="primary",
                         disabled=not usable):
                merged = list(st.session_state.meds_list)
                for name in usable:
                    if name not in merged:
                        merged.append(name)
                st.session_state.meds_list = merged
                st.session_state.picker_version += 1
                st.session_state.pop("photo_read", None)
                st.session_state.pop("result", None)
                st.rerun()
            if c2.button("Discard"):
                st.session_state.pop("photo_read", None)
                st.rerun()

picked = st.multiselect(
    "Your medications",
    options=options,
    default=st.session_state.meds_list,
    key=f"picker_{st.session_state.picker_version}",
    accept_new_options=True,
    placeholder="Start typing a medication, or type a name we do not list",
    help="Pick from the list or type anything. Names not in the list are "
         "resolved against RxNorm the same way.")

# keep our copy in step with manual edits, without bumping the version
if list(picked) != list(st.session_state.meds_list):
    st.session_state.meds_list = list(picked)

# strip the " — description" suffix the picker shows
meds = [p.split(" — ")[0].strip() for p in picked if p.strip()]

if st.button("Check my medications", type="primary", disabled=not meds):
    with st.spinner("Resolving medications and running all three checks…"):
        st.session_state.result = run(tuple(meds), key, sig, lang)

result = st.session_state.get("result")

if result:
    st.subheader("Your medications")
    rows = []
    for item in result["resolved"]:
        if item["ingredients"]:
            detail = "contains " + ", ".join(item["ingredients"])
            cls = ("mc-src mc-src-fda" if str(item["source"]).startswith("openFDA")
                   else "mc-src")
        else:
            detail, cls = "could not identify this one", "mc-src mc-src-miss"
        rows.append(f'<div class="mc-row"><span class="mc-name">{item["typed"]}</span>'
                    f'<span class="mc-ing">{detail}</span>'
                    f'<span class="{cls}">{item["source"] or "unresolved"}</span></div>')
    st.markdown('<div class="mc-list">' + "".join(rows) + "</div>",
                unsafe_allow_html=True)

    questions = []

    st.subheader("What to do")
    anything = False

    for dup in result["duplications"]:
        anything = True
        finding(dup, f"{', '.join(dup['products'])} all contain "
                     f"<b>{dup['ingredient']}</b>")
        if dup.get("questions"):
            questions.append((" and ".join(dup["products"]), dup["questions"]))

    for hit in result["interactions"]:
        anything = True
        finding(hit, f"{hit['a'].title()} and {hit['b'].title()}")
        if hit.get("questions"):
            questions.append((f"{hit['a']} and {hit['b']}", hit["questions"]))

    if not anything:
        st.write("No shared ingredients or known interactions found in this list.")

    if not ints:
        st.warning(
            "**Drug-drug interactions are not checked yet.** This build finds "
            "medicines that share an ingredient. Checking whether two different "
            "drugs work against each other needs the pharmacist-reviewed "
            "reference our team is still building. We show you the gap rather "
            "than reporting your list as clear.")

    if result["unresolved"]:
        names = ", ".join(result["unresolved"])
        st.warning(
            f"**We could not identify:** {names}. A medicine we cannot identify "
            f"may still contain an ingredient you are already taking, so we "
            f"surface it rather than assume it is safe. Bring these to your "
            f"pharmacist by name.")
        questions.append((names, [
            f"Does {n} contain anything that is already in my other medicines?"
            for n in result["unresolved"]]))

    if result.get("foods"):
        st.subheader("Food and drink to watch")
        for food in result["foods"]:
            finding(food, f"{food['food'].title()} with your "
                          f"{food['ingredient'].title()}")
            if food.get("questions"):
                questions.append((f"{food['ingredient']} and {food['food']}",
                                  food["questions"]))

    st.subheader("Ask your pharmacist")
    if questions:
        for about, items in questions:
            st.markdown(f'<div class="mc-qh">About your {about}</div>',
                        unsafe_allow_html=True)
            for q in items:
                st.markdown(f"- “{q}”")
        st.download_button(
            "Download these questions",
            data="Questions for my pharmacist\n\n" + "\n\n".join(
                f"About my {about}\n" + "\n".join(f"  - {q}" for q in items)
                for about, items in questions),
            file_name="questions_for_my_pharmacist.txt", mime="text/plain")
    else:
        st.markdown("- “Is anything on this list working against anything else?”")
        st.markdown("- “Which side effects should make me call you?”")

    with st.expander("How this answer was produced"):
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown("**1. Normalize**\n\nRxNorm resolves what you typed\n\n`deterministic`")
        c2.markdown("**2. Detect**\n\nDuplicates, interactions, foods\n\n`deterministic`")
        c3.markdown("**3. Retrieve**\n\nPull the matching FDA label section\n\n`deterministic`")
        c4.markdown("**4. Explain**\n\nPharmacist text first, model fills gaps\n\n`generative`")
        st.caption(
            "The model never decides whether a risk exists — steps 1 and 2 do, "
            "by lookup. Where our pharmacist has written the wording we show it "
            "verbatim rather than having a model paraphrase her. The questions "
            "come from the findings themselves, so a patient arrives at the "
            "counter with something specific to ask.")

st.divider()
st.caption("MedClear does not diagnose and does not tell you to start or stop "
           "any medication. Every result routes you to a pharmacist.")
