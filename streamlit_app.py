"""
streamlit_app.py
================

HaasPlan XAI — argumentation-based explanations for collaborative planning.

Two modes share one engine.

  Explore      pick a domain, inspect the framework, hold a dialogue with the
               system. This is the demonstration mode.
  User study   the six-stage participant flow, ending in a questionnaire.

ARCHITECTURE
------------
The dialogue is driven by explanation_dialogue.py, which is the same file as
Module 10b of the notebook. Nothing about the protocol is reimplemented here.
The interface renders whatever legal_moves() returns and routes clicks through
play(), so an illegal move cannot be produced by clicking.

The framework is not recomputed at run time. The app loads the JSON artefacts
written by the notebook, which were produced for BOTH domains by one extraction
implementation (Module 3b). Adding a domain is an entry in domains.py plus four
files in data/.
"""

import json
import random
import string
import time
from pathlib import Path

import streamlit as st

import domains as dm
import study_config as cfg
from explanation_dialogue import (CQ_META, ExplanationDialogue, IllegalMove,
                                  Locution, check_faithfulness)
from storage import build_record, get_store, to_csv

CONSENT_VERSION = "2026-09-v1"

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
LOGO = APP_DIR / "assets" / "uoh_logo_web.png"

STUDY_STAGES = ["information", "consent", "choose", "briefing", "dialogue",
                "questionnaire", "debrief"]

INK = "#0B2D8F"          # University of Huddersfield blue
MUTED = "#5B6472"
LINE = "#DCE1EA"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_domain(key: str):
    """Load one domain's artefacts. Returns (steps, s8, cq, labels, names)."""
    def read(suffix, required=True):
        path = DATA_DIR / f"{key}_{suffix}.json"
        if not path.exists():
            if required:
                raise FileNotFoundError(path.name)
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    return (read("plan"), read("S8_PSA"), read("CQ_results"),
            read("AF_labels"), read("display_names", required=False) or {})


def available_domains():
    """Only domains whose artefacts are actually present."""
    out = []
    for domain in dm.REGISTRY:
        if (DATA_DIR / f"{domain.key}_plan.json").exists():
            out.append(domain)
    return out


def build_dialogue(key: str) -> ExplanationDialogue:
    steps, s8, cq, labels, names = load_domain(key)
    for step in steps:
        step.setdefault("display_name",
                        names.get(step["action_name"], step["action_name"]))
    return ExplanationDialogue(steps, s8, cq, labels, CQ_META)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def new_code() -> str:
    return "P-" + "".join(random.choices(string.ascii_uppercase + string.digits,
                                         k=8))


def init_state():
    ss = st.session_state
    ss.setdefault("mode", None)
    ss.setdefault("stage", "information")
    ss.setdefault("participant_code", new_code())
    ss.setdefault("domain_key", dm.default_key())
    ss.setdefault("log", [])
    ss.setdefault("started_at", None)
    ss.setdefault("submitted", False)
    ss.setdefault("domain_choice", "assigned")   # or self_selected
    ss.setdefault("familiarity", None)
    if "dialogue" not in ss:
        ss.dialogue = build_dialogue(ss.domain_key)


def switch_domain(key: str):
    ss = st.session_state
    if key == ss.domain_key and "dialogue" in ss:
        return
    ss.domain_key = key
    ss.dialogue = build_dialogue(key)
    ss.log = []
    ss.started_at = None


def goto(stage: str):
    st.session_state.stage = stage
    st.rerun()


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------

def header():
    left, right = st.columns([1, 2], vertical_alignment="center")
    with left:
        if LOGO.exists():
            st.image(str(LOGO), width=240)
        else:
            st.markdown("**University of Huddersfield**")
    with right:
        st.markdown(
            f"<div style='text-align:right;'>"
            f"<div style='font-size:16px;font-weight:700;color:{INK};'>"
            f"HaasPlan XAI</div>"
            f"<div style='font-size:12px;color:{MUTED};line-height:1.5;'>"
            f"Argumentation-Based Explanations for Collaborative Planning<br>"
            f"School of Computing and Engineering &nbsp;&middot;&nbsp; "
            f"{cfg.PROJECT_CODE}</div></div>",
            unsafe_allow_html=True)
    st.markdown(f"<hr style='margin:10px 0 18px;border:none;"
                f"border-top:2px solid {INK};'>", unsafe_allow_html=True)


def domain_badge(domain):
    st.markdown(
        f"<span style='display:inline-block;background:#EAF0FA;color:{INK};"
        f"padding:3px 10px;border-radius:12px;font-size:12px;"
        f"font-weight:600;'>{domain.short}</span>",
        unsafe_allow_html=True)


def domain_selector(label="Domain", key="dsel"):
    """The selector. One control, shared by both modes."""
    options = available_domains()
    if len(options) < 2:
        return options[0] if options else None
    keys = [d.key for d in options]
    current = st.session_state.domain_key
    index = keys.index(current) if current in keys else 0
    chosen = st.selectbox(
        label, keys, index=index,
        format_func=lambda k: dm.get(k).name, key=key)
    if chosen != current:
        switch_domain(chosen)
        st.rerun()
    return dm.get(chosen)


# ---------------------------------------------------------------------------
# Shared panels
# ---------------------------------------------------------------------------

def verdict_panel(dialogue, domain):
    verdict = dialogue.verdict
    with st.container(border=True):
        st.markdown(f"**Is this {domain.subject} plan valid?**")
        if verdict == "ACCEPTED":
            st.success("The system's verdict is that the plan is VALID.",
                       icon=":material/check_circle:")
        else:
            st.error("The system's verdict is that the plan is NOT valid.",
                     icon=":material/cancel:")
        with st.expander("What the system checked"):
            for i, premise in enumerate(dialogue.s8_result.get("premises", [])):
                mark = ":material/check:" if premise.get("holds") else ":material/close:"
                st.markdown(f":material/{'check' if premise.get('holds') else 'close'}: "
                            f"**P{i + 1}.** {premise.get('label', '')}")


def plan_table(dialogue, domain):
    rows = []
    for step in dialogue.steps:
        rows.append({
            "#": step.get("step_index", step.get("action_index")),
            "Action": step.get("display_name", step.get("action_name")),
            "Start": step.get("start"),
            "End": step.get("end"),
            domain.columns.get("resource", "Resource"): step.get("resource", "-"),
        })
    st.dataframe(rows, hide_index=True, width="stretch")


SPEAKER = {
    Locution.ASSERT: "The system states",
    Locution.JUSTIFY: "The system answers",
    Locution.CONCEDE: "The system concedes",
    Locution.DECLARE_NA: "The system replies",
    Locution.GROUND: "The system explains",
    Locution.REFORMULATE: "The system rephrases",
    Locution.CLOSE: "The system closes",
}


def render_log():
    if not st.session_state.log:
        st.caption("The conversation will appear here.")
        return
    for speaker, title, text in st.session_state.log:
        role = "user" if speaker == "U" else "assistant"
        avatar = ":material/person:" if speaker == "U" else ":material/smart_toy:"
        with st.chat_message(role, avatar=avatar):
            if title:
                st.markdown(f"**{title}**")
            st.markdown(text.replace("\n", "  \n"))


def play_move(move):
    dialogue = st.session_state.dialogue
    try:
        replies = dialogue.play(move)
    except IllegalMove as exc:
        st.warning(str(exc))
        return
    if st.session_state.started_at is None:
        st.session_state.started_at = time.time()
    st.session_state.log.append(("U", "You ask", move.text))
    for reply in replies:
        st.session_state.log.append(
            ("E", SPEAKER.get(reply.locution, "The system"), reply.text))
    st.rerun()


def move_buttons(dialogue, columns=3):
    """Render exactly the legal moves.

    Grouping is presentational only. The protocol decides what exists here;
    this function decides where it sits on screen. A move that legal_moves()
    does not return cannot be rendered, so an illegal move cannot be clicked.
    """
    moves = dialogue.legal_moves()
    if not moves:
        return
    names = {s.get("step_index", s.get("action_index")):
             s.get("display_name", s.get("action_name")) for s in dialogue.steps}

    focus_moves = [m for m in moves if m.locution in
                   (Locution.WHY, Locution.UNDERSTAND, Locution.NOT_UNDERSTAND,
                    Locution.OPEN)]
    challenges = [m for m in moves if m.locution is Locution.CHALLENGE]
    closing = [m for m in moves if m.locution is Locution.CLOSE]

    # Whatever is in focus comes first, because it is the live thread.
    if focus_moves:
        cols = st.columns(min(columns, len(focus_moves)))
        for i, move in enumerate(focus_moves):
            kind = "primary" if move.locution in (Locution.OPEN,
                                                  Locution.UNDERSTAND) else "secondary"
            with cols[i % len(cols)]:
                if st.button(move.label()[:46], key=f"f_{i}", help=move.text,
                             type=kind, width="stretch"):
                    play_move(move)

    # Challenges grouped by the action they concern, so the button count per
    # screen stays readable on a domain with 90 legal challenges.
    if challenges:
        grouped = {}
        for move in challenges:
            grouped.setdefault(move.content["action"], []).append(move)
        st.markdown(f"<div style='font-size:13px;color:{MUTED};margin:10px 0 2px;'>"
                    f"Questions you can put to the system, by step</div>",
                    unsafe_allow_html=True)
        for action_index in sorted(grouped):
            group = grouped[action_index]
            title = f"Step {action_index} · {names.get(action_index, '')}"
            with st.expander(f"{title}  ({len(group)})",
                             expanded=(action_index == min(grouped))):
                cols = st.columns(columns)
                for i, move in enumerate(group):
                    with cols[i % columns]:
                        if st.button(move.content["cq"],
                                     key=f"c_{action_index}_{i}",
                                     help=move.text, width="stretch"):
                            play_move(move)
                st.caption(group[0].text[:150] if len(group) == 1 else
                           "Hover a button to see the question it asks.")

    if closing:
        st.markdown("")
        if st.button("End dialogue", key="close_btn", type="secondary"):
            play_move(closing[0])


def dialogue_hint(dialogue):
    state = dialogue.state
    if state.pending_reformulation is not None:
        return ("You said you did not follow. The system has rephrased, and "
                "under rule R6 it may not simply repeat itself.")
    if state.focus is not None:
        return ("Question any premise of the answer (rule R4), or move on to "
                "another critical question.")
    if not state.opened:
        return "Open the dialogue to receive the plan summary argument (rule R1)."
    return "Choose a critical question to put to the system (rule R2)."


def dialogue_status(dialogue):
    o = dialogue.outcome()
    st.markdown(
        f"<div style='font-size:12px;color:{MUTED};border-top:1px solid {LINE};"
        f"padding-top:8px;margin-top:4px;'>"
        f"Critical questions raised {o['cqs_challenged']} of {o['cqs_available']}"
        f" &nbsp;·&nbsp; premises grounded {o['premises_grounded']}"
        f" &nbsp;·&nbsp; your moves {o['explainee_moves']} of a bound of "
        f"{o['move_bound']}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------

def stage_landing():
    st.markdown(
        f"<div style='font-size:19px;font-weight:600;color:{INK};'>"
        f"Explaining automated plans through argumentation</div>"
        f"<div style='color:{MUTED};font-size:14px;margin:6px 0 18px;'>"
        f"This system checks whether a scheduled plan is valid, then explains "
        f"its verdict through a dialogue you can interrogate. Every answer it "
        f"gives is drawn from a formal argumentation framework computed in "
        f"advance, so it can say exactly which requirement a plan fails."
        f"</div>", unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**Explore the system**")
            st.caption("Pick a domain, inspect the framework, and question the "
                       "system freely. No consent form, nothing recorded.")
            if st.button("Open explorer", type="primary", width="stretch"):
                st.session_state.mode = "explore"
                st.rerun()
    with right:
        with st.container(border=True):
            st.markdown("**Run the user study**")
            st.caption("The participant flow: information, consent, task, "
                       "dialogue, questionnaire.")
            if st.button("Start the study", width="stretch"):
                st.session_state.mode = "study"
                st.session_state.stage = "information"
                st.rerun()

    with st.container(border=True):
        st.markdown("**Domains available**")
        for domain in available_domains():
            steps, s8, cq, labels, _ = load_domain(domain.key)
            verdict = "valid" if labels.get("PSA_P") == "IN" else "not valid"
            st.markdown(
                f"<div style='margin:6px 0;'><b>{domain.name}</b>"
                f"<div style='color:{MUTED};font-size:13px;'>{domain.blurb}</div>"
                f"<div style='color:{MUTED};font-size:12px;margin-top:2px;'>"
                f"{len(steps)} actions &nbsp;·&nbsp; {len(cq)} critical question "
                f"instances &nbsp;·&nbsp; verdict: plan is {verdict}</div></div>",
                unsafe_allow_html=True)
        st.caption("Both frameworks are produced by one extraction "
                   "implementation, which reads conditions and effects from the "
                   "planning model rather than matching on action names.")


# ---------------------------------------------------------------------------
# Explore mode
# ---------------------------------------------------------------------------

def stage_explore():
    top = st.columns([3, 1], vertical_alignment="bottom")
    with top[0]:
        domain = domain_selector("Domain", key="explore_domain")
    with top[1]:
        if st.button("Back", width="stretch"):
            st.session_state.mode = None
            st.rerun()
    if domain is None:
        st.error("No domain artefacts found in data/.")
        return

    st.caption(domain.blurb)
    dialogue = st.session_state.dialogue

    tab_dialogue, tab_plan, tab_framework = st.tabs(
        ["Dialogue", domain.plan_caption, "Framework"])

    with tab_dialogue:
        verdict_panel(dialogue, domain)
        with st.container(border=True, height=360):
            render_log()
        if dialogue.state.closed:
            st.info("Dialogue closed. " + dialogue._closing_summary())
            if st.button("Start a new dialogue"):
                switch_domain(domain.key)
                st.session_state.dialogue.reset()
                st.session_state.log = []
                st.rerun()
        else:
            st.caption(dialogue_hint(dialogue))
            move_buttons(dialogue)
        dialogue_status(dialogue)

    with tab_plan:
        plan_table(dialogue, domain)
        st.caption("The framework explains this plan. It does not re-solve it.")

    with tab_framework:
        steps, s8, cq, labels, _ = load_domain(domain.key)
        counts = {}
        for row in cq:
            counts.setdefault(row["CQ"], {}).setdefault(row["Outcome"], 0)
            counts[row["CQ"]][row["Outcome"]] += 1
        st.markdown("**Critical question coverage**")
        st.dataframe(
            [{"Critical question": cqid,
              "Instances": sum(v.values()),
              "Defeated": v.get("defeated", 0),
              "Succeeds": v.get("succeeds", 0),
              "Not applicable": v.get("n/a", 0)}
             for cqid, v in sorted(counts.items())],
            hide_index=True, width="stretch")
        succeeding = [r for r in cq if r["Outcome"] == "succeeds"]
        if succeeding:
            st.markdown("**Critical questions that succeed**")
            st.caption("Each of these is an unanswered attack on the plan.")
            for row in succeeding:
                st.markdown(f"- `{row['CQ']}` on {row['Action(s)']} — "
                            f"{row['Detail'][:120]}")
        else:
            st.success("Every applicable critical question is defeated.",
                       icon=":material/verified:")


# ---------------------------------------------------------------------------
# Study mode
# ---------------------------------------------------------------------------

def study_progress():
    index = STUDY_STAGES.index(st.session_state.stage)
    st.progress((index + 1) / len(STUDY_STAGES),
                text=f"Step {index + 1} of {len(STUDY_STAGES)}")


def stage_information():
    st.subheader("Participant information sheet")
    st.caption(f"Your participant code for this session is "
               f"**{st.session_state.participant_code}**.")
    for heading, body in cfg.PARTICIPANT_INFORMATION:
        with st.container(border=True):
            st.markdown(f"**{heading}**")
            st.markdown(body)
    st.info(cfg.RETENTION_STATEMENT, icon=":material/schedule:")
    st.caption(f"*{cfg.PIS_CLOSING}*")
    st.divider()
    if st.button("Continue to consent", type="primary"):
        goto("consent")


def stage_consent():
    st.subheader("Consent form")
    st.markdown(cfg.CONSENT_PREAMBLE)
    with st.container(border=True):
        ticks = [st.checkbox(f"**{i + 1}.**  {item}", key=f"consent_{i}")
                 for i, item in enumerate(cfg.CONSENT_ITEMS)]
    st.caption(f"*{cfg.CONSENT_NOTE}*")
    st.caption(cfg.CONSENT_TIMESTAMP_NOTE)
    st.divider()
    left, right = st.columns(2)
    with left:
        if st.button("I consent, begin the study", type="primary",
                     disabled=not all(ticks)):
            goto("choose")
    with right:
        if st.button("I do not wish to take part"):
            st.session_state.stage = "declined"
            st.rerun()


def stage_declined():
    st.subheader("Thank you")
    st.write("You have chosen not to take part. Nothing has been recorded. "
             "You may close this window.")


def stage_choose():
    """Domain selection by the participant, framed as familiarity.

    Asking which domain is closer to work the participant has done, rather
    than which they would prefer, does two things. It steers each person to
    the plan they can actually reason about, which is what the contestability
    items depend on. And it records professional proximity as a variable
    instead of leaving it to be inferred.

    Because participants choose, domain is not independent of background. That
    is recorded in the data as domain_choice="self_selected" so the two groups
    can be reported separately rather than compared as if randomised.
    """
    options = available_domains()
    st.subheader("Which plan would you like to work with?")
    st.markdown(
        "Please choose the one **closer to work you have done**. There is no "
        "right answer, and either choice is equally useful to the research.")

    for domain in options:
        with st.container(border=True):
            st.markdown(f"**{domain.name}**")
            st.caption(domain.blurb)
            steps, _s8, cq, labels, _n = load_domain(domain.key)
            st.caption(f"{len(steps)} steps in the plan.")
            if st.button(f"Work with this plan", key=f"pick_{domain.key}",
                         type="primary", width="stretch"):
                switch_domain(domain.key)
                st.session_state.domain_choice = "self_selected"
                st.session_state.familiarity = domain.key
                goto("briefing")

    st.caption("Neither is closer to your work? Either choice is still fine, "
               "pick whichever looks more interesting.")


def stage_briefing():
    domain = dm.get(st.session_state.domain_key)
    st.subheader("Your task")
    domain_badge(domain)
    st.markdown(cfg.TASK_INTRODUCTION)
    st.markdown(f"**{domain.plan_caption}**")
    st.caption(domain.blurb)
    plan_table(st.session_state.dialogue, domain)
    st.divider()
    if st.button("Start the dialogue", type="primary"):
        st.session_state.started_at = time.time()
        goto("dialogue")


def stage_dialogue():
    domain = dm.get(st.session_state.domain_key)
    dialogue = st.session_state.dialogue
    domain_badge(domain)
    verdict_panel(dialogue, domain)
    st.markdown("**Your conversation**")
    with st.container(border=True, height=340):
        render_log()
    if dialogue.state.closed:
        st.success("You have ended the dialogue.")
        if st.button("Continue to the questionnaire", type="primary"):
            goto("questionnaire")
        return
    st.caption(dialogue_hint(dialogue))
    move_buttons(dialogue)
    dialogue_status(dialogue)


def stage_questionnaire():
    dialogue = st.session_state.dialogue
    domain = dm.get(st.session_state.domain_key)
    verdict = dialogue.verdict
    sections = cfg.sections_for(verdict)
    items = cfg.all_items(verdict)

    st.subheader("User study questionnaire")
    st.markdown(cfg.QUESTIONNAIRE_PREAMBLE)

    # The two header fields on the printed form are recorded automatically,
    # since the app already knows which scenario was shown and what the
    # system's verdict was.
    with st.container(border=True):
        left, right = st.columns(2)
        with left:
            st.markdown("**Scenario explored**")
            st.markdown(domain.name)
        with right:
            st.markdown("**Plan verdict**")
            st.markdown(f"`{verdict}`")
        st.caption("Recorded automatically from your session.")

    answers = {}
    for label, section_items in sections:
        with st.container(border=True):
            st.markdown(f"**{label}**")
            if label.startswith("F "):
                st.caption(cfg.SECTION_F_NOTE)
            for item_id, text in section_items:
                answers[item_id] = st.radio(
                    f"**{item_id}.**  {text}", cfg.LIKERT_SCALE,
                    key=f"q_{item_id}", index=None, horizontal=True)

    # Section G also carries a free numeric item. The true count is recorded
    # separately from the transcript, so the two can be compared.
    count_id, count_text = cfg.COUNT_ITEM
    with st.container(border=True):
        st.markdown("**G — Dialogue engagement, your own count**")
        reported = st.number_input(f"**{count_id}.**  {count_text}",
                                   min_value=0, max_value=500, step=1,
                                   value=None, key=f"q_{count_id}")

    open_answers = {}
    with st.container(border=True):
        st.markdown("**H — Open feedback**")
        for item_id, text in cfg.OPEN_QUESTIONS:
            open_answers[item_id] = st.text_area(f"**{item_id}.**  {text}",
                                                 key=f"open_{item_id}",
                                                 height=80)

    missing = [k for k, v in answers.items() if v is None]
    if reported is None:
        missing.append(count_id)
    st.divider()
    if missing:
        st.caption(f"{len(missing)} item(s) not yet answered: "
                   f"{', '.join(missing)}")
    if st.button("Submit my responses", type="primary", disabled=bool(missing)):
        submit(answers, int(reported), open_answers)
    st.caption(f"*{cfg.QUESTIONNAIRE_CLOSING}*")


def submit(likert, reported_count, open_answers):
    dialogue = st.session_state.dialogue
    elapsed = (time.time() - st.session_state.started_at
               if st.session_state.started_at else None)
    record = build_record(
        participant_code=st.session_state.participant_code,
        domain=st.session_state.domain_key,
        domain_choice=st.session_state.domain_choice,
        familiarity=st.session_state.familiarity,
        verdict=dialogue.verdict,
        outcome=dialogue.outcome(),
        transcript=dialogue.transcript(),
        likert=likert,
        reported_count=reported_count,
        open_responses=open_answers,
        seconds_on_dialogue=elapsed,
        consent_version=CONSENT_VERSION,
    )
    store = get_store(getattr(st, "secrets", None))
    saved, note = store.save(record)
    if not saved:
        st.error(f"Your responses could not be saved ({note}). Please tell the "
                 f"researcher and do not close this window yet.")
        return
    st.session_state.submitted = True
    st.session_state.save_note = note
    goto("debrief")


def stage_debrief():
    st.subheader("Thank you for taking part")
    st.markdown(cfg.DEBRIEF)
    st.info(f"Recorded under participant code "
            f"**{st.session_state.participant_code}**. You may close this window.",
            icon=":material/check_circle:")


# ---------------------------------------------------------------------------
# Researcher panel
# ---------------------------------------------------------------------------

def researcher_panel():
    with st.sidebar:
        st.markdown("**Researcher**")
        try:
            expected = st.secrets["admin_password"]
        except Exception:
            st.caption("Set admin_password in secrets to enable this panel.")
            return
        if st.text_input("Password", type="password", key="adm") != expected:
            return

        st.divider()
        st.markdown("**Study domain**")
        keys = [d.key for d in available_domains()]
        chosen = st.selectbox("Assign participants to", keys,
                              index=keys.index(st.session_state.domain_key),
                              format_func=lambda k: dm.get(k).short,
                              key="admin_domain")
        if chosen != st.session_state.domain_key:
            switch_domain(chosen)
            st.rerun()

        store = get_store(getattr(st, "secrets", None))
        st.write("Storage:", store.name)
        if not store.durable:
            st.error("Active store is NOT durable. Responses will be lost on "
                     "restart. Set sheet_id and gcp_service_account in "
                     "secrets.", icon=":material/warning:")
        else:
            ok, detail = store.check()
            if ok:
                st.success(f"Sheet {detail}", icon=":material/check:")
            else:
                st.error(f"Sheet unreachable: {detail}",
                         icon=":material/warning:")

        faithful, problems = check_faithfulness(st.session_state.dialogue)
        st.write("Faithful to grounded extension:", faithful)
        if problems:
            st.write(problems)
        st.write("Likert items (all):", len(cfg.all_items()))
        st.write("Items for an ACCEPTED plan:", len(cfg.all_items("ACCEPTED")))

        rows = store.load_all()
        st.write("Responses stored:", len(rows))
        if rows:
            st.download_button("Download responses (CSV)",
                               data=to_csv(rows),
                               file_name="haasplan_responses.csv",
                               mime="text/csv")
            st.download_button("Download responses (JSON)",
                               data=json.dumps(rows, indent=2),
                               file_name="haasplan_responses.json",
                               mime="application/json")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="HaasPlan XAI", layout="centered",
                       page_icon=str(LOGO) if LOGO.exists() else None)
    try:
        init_state()
    except FileNotFoundError as missing:
        header()
        st.error(f"Missing artefact `{missing}` in data/. Run the notebook's "
                 f"Module 9 and 9b and commit the JSON files.",
                 icon=":material/error:")
        st.stop()

    header()
    mode = st.session_state.mode

    if mode is None:
        stage_landing()
    elif mode == "explore":
        stage_explore()
    else:
        if st.session_state.stage == "declined":
            stage_declined()
        else:
            study_progress()
            {"information": stage_information, "consent": stage_consent,
             "choose": stage_choose,
             "briefing": stage_briefing, "dialogue": stage_dialogue,
             "questionnaire": stage_questionnaire,
             "debrief": stage_debrief}[st.session_state.stage]()

    researcher_panel()


if __name__ == "__main__":
    main()
