import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from agent import Desk, live, today
from demo import SAMPLES, demo, seed
from ledger import FIELDS, SCHEMA, approve, database, fields, minor, money, rows, validate

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
LIVE = os.getenv("TRADEFLOW_MODE", "demo").lower() == "live"
DB = os.getenv("TRADEFLOW_DB") or ROOT / "data/tradeflow.sqlite3"
VIEWS = ["Trade Assistant", "Trade Records", "Dashboard", "Workflow & Evaluation"]
st.set_page_config(page_title="TradeFlow · Trade operations", page_icon="↗", layout="wide")
st.markdown("""<style>
.block-container {max-width:1250px;padding-top:2.7rem}
h1,h2,h3 {letter-spacing:-.035em}
[data-testid="stSidebar"] {border-right:1px solid #d8e1d8}
.brand {font-size:25px;font-weight:750;letter-spacing:-1.2px;margin-bottom:1rem}
.mark {background:#006c57;color:white;border-radius:8px;padding:1px 7px;margin-right:6px}
.banner {background:#153f36;color:#edf6e9;border-radius:15px;padding:25px 30px;margin:1rem 0 1.3rem}
.banner small {color:#b7ddaa;font:600 11px monospace;letter-spacing:2px}
.banner h2 {color:white;padding:.45rem 0 .15rem;font-size:2rem}
.banner p {margin:0;color:#d8e7dd}
[data-testid="stMetric"] {background:#eef3ec;padding:12px 16px;border-radius:10px}
</style>""", unsafe_allow_html=True)
state = st.session_state
state.setdefault("pending", None)


def interpret(db, source, day):
    desk = Desk(db, source, day)
    with st.spinner("Preparing review…"):
        state.pending = live(desk) if LIVE else demo(desk)


def sample(text):
    state.ticket = text


def table(data):
    st.dataframe(pd.DataFrame(data), hide_index=True, width="stretch")


def assistant(db):
    st.markdown("""<div class="banner"><small>OPERATIONS / INTAKE</small>
    <h2>Trade Assistant</h2><p>Turn a desk message into a reviewed ledger entry.</p></div>""",
                unsafe_allow_html=True)
    if "notice" in state:
        st.success(state.pop("notice"))
    if (p := state.pending) is None:
        if not LIVE:
            st.caption("Deterministic demo · Choose a sample or follow its sentence pattern. Free-form interpretation requires live mode.")
        left, right = st.columns([1.8, 1])
        with left.container(border=True):
            st.subheader("Message intake")
            msg = st.text_area("Desk message", key="ticket", height=135, max_chars=2000,
                               placeholder=SAMPLES["New trade"])
            if st.button("Prepare proposal", type="primary", disabled=not msg.strip() or
                         (LIVE and not os.getenv("OPENAI_API_KEY"))):
                state.day = today()
                interpret(db, msg.strip(), state.day)
                st.rerun()
        with right.container(border=True):
            st.subheader("Sample tickets")
            for label, text in SAMPLES.items():
                st.button(label, on_click=sample, args=(text,), width="stretch")
        return

    st.subheader("Review ticket")
    st.text(p.source)
    st.caption("Tool activity  /  " + " → ".join(p.trace or ["No completed tool call"]))
    if "today" in p.source.lower():
        st.info(f"‘Today’ resolves to {state.day} in Asia/Bangkok. Confirm this date before approval.")
    if p.action == "clarify":
        st.warning(p.question)
        with st.form("reply", clear_on_submit=True):
            extra = st.text_input("Add the missing detail", max_chars=500)
            if st.form_submit_button("Continue with clarification") and extra.strip():
                interpret(db, p.source + "\nClarification: " + extra.strip(), state.day)
                st.rerun()
    else:
        st.markdown("**Proposed correction**" if p.before else "**Proposed new trade**")
        if p.before:
            prior = fields(p.before)
            changes = [f"{k} from {prior[k]} to {p.values[k]}" for k in FIELDS if prior[k] != p.values[k]]
            st.write(f"Update {p.before['ref'] or 'record #' + str(p.before['id'])}: " + ", ".join(changes))
        else:
            v = p.values
            st.write(f"{v['side']} {v['quantity']} shares of {v['symbol']} at {v['currency']} {v['price']} on {v['trade_date']}.")
        comparison = {"Field": list(FIELDS)}
        if p.before:
            old = fields(p.before)
            comparison[f"Current · v{p.before['version']}"] = [str(old[k] or "—") for k in FIELDS]
        comparison["Proposed"] = [str(p.values.get(k) if p.values.get(k) is not None else "—") for k in FIELDS]
        table(comparison)
        errors, warnings = validate(db, p)
        for e in errors:
            st.error(e)
        for w in warnings:
            st.warning(w)
        if not errors:
            v = p.values
            st.caption("Gross trade value  /  THB " + money(v["quantity"] * minor(v["price"])))
        accepted = not warnings or st.checkbox("I reviewed the possible duplicate.", key="ack-" + p.token)
        if not errors and not warnings:
            st.success("Python validation passed.")
        if st.button("Approve and save", type="primary", disabled=bool(errors) or not accepted):
            try:
                tid = approve(db, p, warnings if accepted else ())
                state.pending = None
                state.notice = f"Saved record #{tid}. The ledger and audit history are up to date."
                st.rerun()
            except (ValueError, sqlite3.Error) as exc:
                st.error(str(exc))
    if st.button("Discard ticket"):
        state.pending = None
        st.rerun()


def display_row(r):
    return {"ID": r["id"], "Reference": r["ref"], "Date": r["trade_date"], "Symbol": r["symbol"],
            "Side": r["side"], "Shares": r["quantity"], "Price (THB)": money(r["price_minor"]),
            "Gross (THB)": money(r["quantity"] * r["price_minor"]), "Version": r["version"]}


def records(db, trades):
    st.title("Trade Records")
    st.caption("Approved trades · Current version of each record")
    a, b, c = st.columns([2, 1, 1])
    query = a.text_input("Search reference, symbol or internal ID").lower().strip()
    side = b.selectbox("Side", ["All", "BUY", "SELL"])
    symbol = c.selectbox("Symbol", ["All"] + sorted({r["symbol"] for r in trades}))
    selected = [r for r in trades if (side == "All" or side == r["side"])
                and (symbol == "All" or symbol == r["symbol"])
                and (query in str(r["ref"] or "").lower() or query in r["symbol"].lower() or query == str(r["id"]))]
    if not selected:
        st.info("No matching records. Load demo data or approve a ticket to populate the ledger.")
        return
    frame = pd.DataFrame(display_row(r) for r in selected)
    table(frame)
    st.download_button("Export filtered CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                       "tradeflow-records.csv", "text/csv")
    st.subheader("Record detail")
    index = st.selectbox("Inspect a record", range(len(selected)),
                         format_func=lambda i: f"#{selected[i]['id']} · {selected[i]['ref'] or 'Unreferenced'} · {selected[i]['symbol']}")
    r = selected[index]
    st.text(r["source"])
    st.caption(f"Created {r['created_at']}  ·  Updated {r['updated_at']}  ·  Version {r['version']}")
    st.markdown("**Approval history**")
    for event in rows(db, "SELECT * FROM audit WHERE trade_id=? ORDER BY rowid DESC", (r["id"],)):
        with st.expander(f"{event['action'].title()} · {event['approved_at']}"):
            st.text(event["source"])
            after = json.loads(event["new_json"])
            before = json.loads(event["previous_json"]) if event["previous_json"] else None
            prior = fields(before) if before else dict.fromkeys(FIELDS, "—")
            table({"Field": FIELDS, "Previous": [str(prior[k]) for k in FIELDS],
                   "Approved": [str(fields(after)[k]) for k in FIELDS]})


def dashboard(db, trades):
    st.title("Dashboard")
    st.caption("Desk activity · All approved trades, using their latest corrected values")
    buys = sum(r["quantity"] * r["price_minor"] for r in trades if r["side"] == "BUY")
    sells = sum(r["quantity"] * r["price_minor"] for r in trades if r["side"] == "SELL")
    for col, label, value in zip(st.columns(4), ["Trade count", "Gross traded · THB", "Buy value · THB", "Sell value · THB"],
                                 [len(trades), money(buys+sells), money(buys), money(sells)]):
        col.metric(label, value)
    st.caption("Each approved trade counts once. Gross activity sums shares × execution price for both sides. Buy and sell values split that total by side.")
    if trades:
        daily, totals = {}, {}
        for r in trades:
            gross = r["quantity"] * r["price_minor"]
            key = (r["trade_date"], r["side"])
            daily[key] = daily.get(key, 0) + gross
            totals[r["symbol"]] = totals.get(r["symbol"], 0) + gross
        activity = pd.DataFrame([(d, s, g/100) for (d,s),g in sorted(daily.items())],
                                columns=["Date","Side","THB"])
        leaders = pd.DataFrame([(s, g/100) for s,g in sorted(totals.items(), key=lambda x:x[1])],
                               columns=["Symbol","THB"])
        charts = [("Activity over time", px.bar(activity, x="Date", y="THB", color="Side",
                       color_discrete_map={"BUY":"#147b65","SELL":"#c87946"})),
                  ("Most active symbols", px.bar(leaders, x="THB", y="Symbol", orientation="h",
                       color_discrete_sequence=["#147b65"]))]
        for col, (label, fig) in zip(st.columns(2), charts):
            with col.container(border=True):
                st.subheader(label)
                fig.update_layout(height=300, margin=dict(l=0,r=5,t=5,b=0), legend_title=None)
                st.plotly_chart(fig, width="stretch")
    else:
        st.info("The charts will appear after the first approval or demo data load.")
    st.subheader("Review queue")
    p = state.pending
    errors, warnings = validate(db, p) if p else ([], [])
    st.write(f"Awaiting review: {int(p is not None)}  ·  Unresolved flags: {len(errors) + len(warnings)}")
    st.caption("Current browser session only. Flags include clarification requests, blocking errors and reviewable warnings.")


def workflow():
    st.title("Workflow & Evaluation")
    st.subheader("From message to ledger")
    st.graphviz_chart("""digraph {rankdir=LR; graph [bgcolor="transparent"]; node [shape=box style="rounded,filled" fillcolor="#E8F2EA" fontname="Arial" color="#94B3A0"]; edge [color="#547B69"]; "Desk\\nmessage" -> "Agent\\ntools" -> "Python\\nchecks" -> "Human\\napproval" -> "SQLite\\n+ audit" -> "Desk\\nmetrics";}""")
    st.write("In live mode, the model selects lookup and proposal tools. In demo mode, an English template interpreter selects the same tools. Python checks the proposed fields, resolves Bangkok dates, and revalidates inside the approval transaction.")
    st.subheader("Evaluation runs")
    for mode in ["demo", "live"]:
        path = ROOT / f"evaluation/{mode}_results.json"
        with st.container(border=True):
            st.markdown(f"**{mode.title()} {'fixture suite' if mode == 'demo' else 'model evaluation'}**")
            if path.exists():
                result = json.loads(path.read_text(encoding="utf-8"))
                st.caption(f"{result['cases']} cases · {result['run_at']} · {result['engine']}")
                table([{"Metric": k, "Correct": v[0], "Scored": v[1],
                        "Rate": f"{v[0]/v[1]:.0%}" if v[1] else "—"} for k,v in result["metrics"].items()])
            else:
                st.caption("Not run.")
    st.caption("Action scores the predicted operation. Field extraction checks labeled fields. Clarification scores ask vs proceed on all cases. Tool selection checks the expected ordered tool sequence.")
    st.subheader("Scope")
    st.write("Four fictional equities, THB settlement, a local SQLite ledger and one pending ticket per browser session. Demo scores measure predefined English patterns. Live model quality requires a separate paid evaluation.")


with database(DB) as db:
    db.executescript(SCHEMA)
    with st.sidebar:
        st.markdown('<div class="brand"><span class="mark">↗</span> TradeFlow</div>', unsafe_allow_html=True)
        st.caption("AI TRADE LOG ASSISTANT")
        view = st.radio("Workspace", VIEWS, label_visibility="collapsed")
        st.divider()
        st.markdown("**Orchid Desk**")
        st.caption("Fictional equities · Bangkok")
        st.badge("Live AI mode" if LIVE else "Deterministic demo", color="green")
        if LIVE and not os.getenv("OPENAI_API_KEY"):
            st.warning("Set OPENAI_API_KEY to interpret messages in live mode.")
        if st.button("Load demo data", width="stretch"):
            try:
                count = seed(db)
                st.success(f"Added {count} demo trades.")
            except (ValueError, sqlite3.Error) as exc:
                st.error(f"Demo load stopped: {exc}")
    trades = rows(db, "SELECT * FROM trades ORDER BY trade_date DESC,id DESC")
    if view == VIEWS[0]:
        assistant(db)
    elif view == VIEWS[1]:
        records(db, trades)
    elif view == VIEWS[2]:
        dashboard(db, trades)
    else:
        workflow()

