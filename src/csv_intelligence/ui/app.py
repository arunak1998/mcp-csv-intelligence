"""Streamlit front end:  streamlit run src/csv_intelligence/ui/app.py"""

import asyncio
import datetime

import streamlit as st

from csv_intelligence.agents.connection import local_connection
from csv_intelligence.agents.csv_agent import run_csv_agent
from csv_intelligence.agents.dashboard_agent import run_dashboard_agent
from csv_intelligence.ui.health import mcp_server_is_up
from csv_intelligence.ui.uploads import clear_uploads, save_upload

MAX_HISTORY = 25

st.set_page_config(page_title="MCP CSV Intelligence", page_icon="🧠", layout="wide")


def init_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("logs", [])
    st.session_state.setdefault("dashboard_html", "")
    st.session_state.setdefault("file", None)  # {"name", "location", "size_kb"} once uploaded


def log(message: str) -> None:
    st.session_state.logs.append(f"[{datetime.datetime.now():%H:%M:%S}] {message}")


def render_sidebar() -> None:
    with st.sidebar:
        if mcp_server_is_up():
            st.success("MCP server: running")
        else:
            st.error("MCP server: not running")
            st.code("csv-mcp-server", language="bash")
            st.caption("Start it in another terminal from the repo root, then refresh this page.")
        st.header("📁 Data file")
        file = st.session_state.file
        if file is None:
            uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
            if uploaded is not None:
                content = uploaded.getvalue()
                location = save_upload(uploaded.name, content)
                st.session_state.file = {
                    "name": uploaded.name,
                    "location": str(location),
                    "size_kb": len(content) / 1024,
                }
                st.session_state.messages = []
                st.session_state.dashboard_html = ""
                log(f"Uploaded {uploaded.name} to {location}")
                st.rerun()
            st.warning("Waiting for a file")
            return

        st.success(f"{file['name']} ({file['size_kb']:.1f} KB)")
        st.caption(file["location"])
        if st.button("🗑️ Remove file", use_container_width=True):
            clear_uploads()
            st.session_state.file = None
            st.session_state.messages = []
            st.session_state.dashboard_html = ""
            log(f"Removed {file['name']}")
            st.rerun()


def render_chat() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Ask a question about your data")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Analysing..."):
            try:
                answer = asyncio.run(run_csv_agent(question, local_connection()))
                log("Chat question answered")
            except Exception as error:
                answer = f"❌ {error}"
                log(f"Chat failed: {error}")
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.messages = st.session_state.messages[-MAX_HISTORY:]


def render_dashboard() -> None:
    question = st.text_input(
        "Describe the dashboard you want", placeholder="e.g. Sales dashboard with revenue trends by region"
    )
    if st.button("🚀 Generate dashboard", type="primary"):
        if not question:
            st.warning("Please describe the dashboard first.")
        else:
            with st.spinner("Building your dashboard..."):
                try:
                    st.session_state.dashboard_html = asyncio.run(
                        run_dashboard_agent(question, local_connection())
                    )
                    log("Dashboard generated")
                except Exception as error:
                    st.error(f"❌ {error}")
                    log(f"Dashboard failed: {error}")

    if st.session_state.dashboard_html:
        st.components.v1.html(st.session_state.dashboard_html, height=700, scrolling=True)


def render_logs() -> None:
    if not st.session_state.logs:
        st.info("No activity yet.")
    for entry in reversed(st.session_state.logs[-50:]):
        st.text(entry)


def main() -> None:
    init_state()
    st.title("🧠 MCP CSV Intelligence")
    st.caption("Chat with your CSV and generate dashboards, powered by an MCP server")
    render_sidebar()

    if st.session_state.file is None:
        st.info("👋 Upload a CSV file in the sidebar to get started.")
        return

    chat_tab, dashboard_tab, logs_tab = st.tabs(["💬 Chat", "📊 Dashboard", "📋 Activity"])
    with chat_tab:
        render_chat()
    with dashboard_tab:
        render_dashboard()
    with logs_tab:
        render_logs()


main()
