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
:root{--ink:#14171a;--mid:#5c6470;--line:#e2e5ea;--card:#fff;
--teal:#1D9E75;--tealbg:#E1F5EE;--tealink:#0F6E56;
--amber:#8A5300;--amberbg:#FBF0DC;--red:#A32D2D;--redbg:#FCEBEB;
--blue:#20567F;--bluebg:#E7F0F7;}

#MainMenu, footer, header {visibility:hidden;}
.block-container{padding-top:2.2rem;padding-bottom:4rem;max-width:820px}

h1{font-weight:600;letter-spacing:-.5px;margin-bottom:.1rem}
h2,h3{font-weight:600;letter-spacing:-.2px}
.mc-sub{color:var(--mid);margin:0 0 1.4rem;font-size:1.02rem}

/* header lockup */
.mc-head{display:flex;align-items:center;gap:14px;margin-bottom:2px}
.mc-head h1{margin:0;font-size:2.1rem}
.mc-head .brand-tail{color:var(--teal)}

/* medication rows */
.mc-row{display:flex;gap:12px;align-items:baseline;padding:10px 0;
        border-bottom:1px solid var(--line);flex-wrap:wrap}
.mc-row:last-child{border-bottom:0}
.mc-name{font-weight:600;min-width:190px;color:var(--ink)}
.mc-ing{color:var(--mid);flex:1;font-size:.95rem}
.mc-src{font-family:ui-monospace,Menlo,monospace;font-size:.72rem;background:#eef1f5;
        color:var(--mid);padding:3px 9px;border-radius:4px;white-space:nowrap}
.mc-src-fda{background:var(--tealbg);color:var(--tealink)}
.mc-src-miss{background:var(--redbg);color:var(--red)}

/* finding banner */
.mc-find{border-left:4px solid;border-radius:0 8px 8px 0;padding:14px 18px;margin:20px 0 0}
.mc-find.now{border-color:var(--red);background:var(--redbg)}
.mc-find.next_visit{border-color:var(--amber);background:var(--amberbg)}
.mc-find.aware{border-color:var(--blue);background:var(--bluebg)}
.mc-find .mc-tier{font-size:.68rem;text-transform:uppercase;letter-spacing:.7px;
                  font-weight:700;margin-bottom:4px}
.mc-find.now .mc-tier{color:var(--red)}
.mc-find.next_visit .mc-tier{color:var(--amber)}
.mc-find.aware .mc-tier{color:var(--blue)}
.mc-find .mc-what{font-size:1.03rem;font-weight:600;color:var(--ink)}

/* patient text */
.mc-text{border-radius:8px;padding:16px 18px;margin:10px 0 4px;font-size:1rem;
         line-height:1.62}
.mc-pharmacist,.mc-model{background:var(--tealbg);color:#0b4a3a}
.mc-draft,.mc-none{background:#f4f6f8;color:#3f4650}
.mc-who{font-size:.68rem;text-transform:uppercase;letter-spacing:.6px;
        font-weight:700;margin-bottom:7px}
.mc-pharmacist .mc-who,.mc-model .mc-who{color:var(--tealink)}
.mc-draft .mc-who{color:var(--amber)}
.mc-none .mc-who{color:var(--mid)}

/* questions */
.mc-qh{font-size:.7rem;text-transform:uppercase;letter-spacing:.6px;
       color:var(--mid);font-weight:700;margin:20px 0 6px}

/* buttons */
div.stButton > button{border-radius:8px;border:1px solid var(--line);font-weight:500}
div.stButton > button[kind="primary"]{background:var(--teal);border-color:var(--teal)}
div.stButton > button[kind="primary"]:hover{background:var(--tealink);
                                            border-color:var(--tealink)}
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
st.markdown('<p class="mc-sub">Understand your medications in plain language. '
            'This tool does not give medical advice.</p>',
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

# The picker owns its own state under an explicit key. Example buttons write
# to that key and rerun, rather than passing `default=`, because a widget with
# a default only honours it on first render and would otherwise show stale
# selections after a button press.
if "med_picker" not in st.session_state:
    st.session_state.med_picker = EXAMPLES["Norco + Tylenol"]

cols = st.columns(len(EXAMPLES))
for col, (label, value) in zip(cols, EXAMPLES.items()):
    if col.button(label, use_container_width=True):
        st.session_state.med_picker = list(value)
        st.session_state.pop("result", None)
        st.rerun()

# Options must always contain the current selection, or Streamlit drops it.
options = sorted({*catalog_names(), *st.session_state.med_picker})

picked = st.multiselect(
    "Your medications",
    options=options,
    key="med_picker",
    accept_new_options=True,
    placeholder="Start typing a medication, or type a name we do not list",
    help="Pick from the list or type anything. Names not in the list are "
         "resolved against RxNorm the same way.")

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
    st.markdown("".join(rows), unsafe_allow_html=True)

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
