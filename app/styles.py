"""All visual styling for the Streamlit app, in one place.

How it works:
1. The design tokens (colors, radius, speed) are Python constants below.
2. css_variables() turns them into CSS variables (--bg, --accent, ...).
3. BASE_CSS uses only those variables, so changing a color here changes it everywhere.
4. apply_styles() injects both into the page; app.py calls it once, at the top of main().

Note: .streamlit/config.toml repeats a few colors (TOML can't import Python). Keep them in sync.
Note: the [data-testid=...] selectors target Streamlit's internal HTML. A Streamlit upgrade
can rename them; if a style stops working after an upgrade, inspect the page and update the selector.
"""

import streamlit as st

# ---- Design tokens ----
BG = "#0A0A0B"                         # page background: near-black
SURFACE = "#111113"                    # cards, inputs, expanders: one step lighter
BORDER = "rgba(255, 255, 255, 0.08)"   # 1px borders at white / 8%
BORDER_HOVER = "rgba(255, 255, 255, 0.16)"
TEXT = "#FAFAFA"                       # main text (zinc-50)
TEXT_MUTED = "#A1A1AA"                 # secondary text (zinc-400)
ACCENT_FROM = "#6366F1"                # indigo-500
ACCENT_TO = "#8B5CF6"                  # violet-500
RADIUS = "16px"                        # rounded-2xl
TRANSITION = "200ms ease"
FONT = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


def css_variables() -> str:
    """The tokens above as CSS variables, so BASE_CSS never repeats a raw color."""
    return f"""
:root {{
  --bg: {BG};
  --surface: {SURFACE};
  --border: {BORDER};
  --border-hover: {BORDER_HOVER};
  --text: {TEXT};
  --text-muted: {TEXT_MUTED};
  --accent-gradient: linear-gradient(135deg, {ACCENT_FROM}, {ACCENT_TO});
  --radius: {RADIUS};
  --transition: {TRANSITION};
  --font: {FONT};
}}
"""
# (Inside an f-string, {{ and }} are a literal { and }. That's why only this small block is an f-string.)


# Plain CSS (not an f-string), so the braces are normal.
BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ---- Page ---- */
html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
}
[data-testid="stDecoration"] { display: none; }            /* the thin coloured bar at the top */
.block-container { max-width: 760px; padding-top: 4rem; padding-bottom: 6rem; }  /* narrow column, generous space */

/* ---- Text ---- */
h1, h2, h3 { font-family: var(--font); letter-spacing: -0.02em; color: var(--text); }
/* Section labels (st.subheader = h3): small grey caps. Streamlit's own heading rule is more specific,
   so the size and color need !important to win. */
[data-testid="stHeading"] h3, h3 {
  font-size: 0.8rem !important;
  font-weight: 600 !important;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted) !important;
  padding-top: 1.5rem !important;
}
[data-testid="stCaptionContainer"] { color: var(--text-muted); }

/* ---- Hero (title block, built in app.py) ---- */
.hero h1 { font-size: 2.5rem; font-weight: 700; margin: 0 0 0.5rem 0; padding: 0; }
.hero .accent {
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.hero p { color: var(--text-muted); font-size: 1rem; margin: 0 0 2rem 0; }

/* ---- Cards: the question form, bordered containers, expanders ---- */
[data-testid="stForm"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stExpander"] details {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color var(--transition);
}
[data-testid="stForm"]:hover,
[data-testid="stExpander"] details:hover { border-color: var(--border-hover); }
[data-testid="stForm"] { padding: 1.25rem; }
[data-testid="stExpander"] summary { color: var(--text); }
[data-testid="stExpander"] summary:hover { color: var(--text); }

/* ---- Text input ---- */
[data-testid="stTextInput"] input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text);
  transition: border-color var(--transition), box-shadow var(--transition);
}
[data-testid="stTextInput"] input:focus {
  border-color: #7C6CF6;
  box-shadow: 0 0 0 3px rgba(124, 108, 246, 0.15);
}

/* ---- The Ask button: the one place the accent gradient is used ---- */
[data-testid="stFormSubmitButton"] button {
  background: var(--accent-gradient);
  color: white;
  border: none;
  border-radius: 12px;
  padding: 0.5rem 1.25rem;
  font-weight: 600;
  transition: opacity var(--transition), transform var(--transition);
}
[data-testid="stFormSubmitButton"] button:hover { opacity: 0.9; color: white; transform: translateY(-1px); }
[data-testid="stFormSubmitButton"] button:active { transform: translateY(0); }

/* ---- Quotes inside sources ---- */
blockquote { border-left: 2px solid #7C6CF6; color: var(--text-muted); margin-left: 0; padding-left: 1rem; }

/* ---- Alerts (warning / error / info): softer, rounded ---- */
[data-testid="stAlert"] { border-radius: 12px; }

/* ---- Pipeline strip: Retrieve -> Generate -> Cite ---- */
.pipeline { display: flex; align-items: stretch; gap: 0.5rem; margin: 1.5rem 0 1rem 0; flex-wrap: wrap; }
.step {
  flex: 1;
  min-width: 150px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.75rem 1rem;
  animation: step-in 400ms ease both;           /* steps fade in one after another */
}
.step:nth-of-type(2) { animation-delay: 120ms; }
.step:nth-of-type(3) { animation-delay: 240ms; }
.step-title { font-size: 0.8rem; font-weight: 600; color: var(--text); }
.step-meta { font-size: 0.8rem; color: var(--text-muted); margin-top: 0.15rem; }
.step-arrow { align-self: center; color: var(--text-muted); }
@keyframes step-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

/* ---- Retrieved chunk cards ---- */
.chunk-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.9rem 1.1rem;
  margin-top: 0.75rem;
  opacity: 0.55;                                 /* not used in the answer: dimmed */
  transition: opacity var(--transition), border-color var(--transition);
}
.chunk-card:hover { opacity: 1; border-color: var(--border-hover); }
.chunk-card.cited { opacity: 1; border-color: rgba(124, 108, 246, 0.45); }   /* used in the answer: highlighted */
.chunk-head { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; }
.chunk-title { font-size: 0.9rem; font-weight: 500; color: var(--text); }
.badge {
  font-size: 0.65rem; font-weight: 700; letter-spacing: 0.08em;
  padding: 0.2rem 0.5rem; border-radius: 999px;
  color: white; background: var(--accent-gradient);
}
.score-row { display: flex; align-items: center; gap: 0.75rem; margin-top: 0.6rem; }
.score-track { flex: 1; height: 6px; background: rgba(255, 255, 255, 0.06); border-radius: 999px; overflow: hidden; }
.score-fill { height: 100%; background: var(--accent-gradient); border-radius: 999px; }
.score-value { font-size: 0.8rem; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.chunk-quote {
  margin-top: 0.6rem; padding-left: 0.75rem;
  border-left: 2px solid #7C6CF6;
  font-size: 0.85rem; color: var(--text-muted);
}
"""


def apply_styles() -> None:
    """Inject the CSS into the page. Call once, at the top of main()."""
    css = css_variables() + BASE_CSS
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
