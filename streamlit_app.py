"""Run locally: python -m streamlit run streamlit_app.py"""
import json
import math

import streamlit as st

from dance_code_belle import AUDIO, SEQUENCES
from dance_code_belle.protocol import play_audio, play_sequence
from dance_code_belle.ui_controller import UIController

st.set_page_config(page_title="Dance Code Belle", page_icon="🌹", layout="wide")


def perform(action, *args, **kwargs):
    try:
        action(*args, **kwargs)
        return True
    except Exception as exc:
        st.error(str(exc))
        return False


def controller():
    worker = st.session_state.get("belle_controller")
    if worker is None or worker.snapshot().closed:
        worker = UIController()
        st.session_state.belle_controller = worker
        st.session_state.devices = []
    return worker


worker = controller()
worker.touch()
st.title("🌹 Dance Code Belle")
st.caption("Connect, choose a stored phrase or routine, and see the command transcript.")

with st.expander("Connection", expanded=True):
    state = worker.snapshot()
    mode_label = st.radio("Connection mode", ["Mock · offline", "Bluetooth · physical Belle"],
                          horizontal=True, disabled=state.connected, key="connection_mode")
    mode = "mock" if mode_label.startswith("Mock") else "bluetooth"
    target = ""
    if mode == "bluetooth":
        st.info("Run this app on the computer beside Belle. Bluetooth uses that computer's adapter, not your browser's.")
        if st.button("Scan for Belle", disabled=state.connected):
            try:
                with st.spinner("Scanning for DanceCD…"):
                    st.session_state.devices = worker.scan()
                if not st.session_state.devices:
                    st.warning("No DanceCD found. Wake Belle, check Bluetooth permissions, then scan again.")
            except Exception as exc:
                st.error(str(exc))
        devices = st.session_state.get("devices", [])
        found = st.selectbox("Discovered Belle", [d["address"] for d in devices],
                             index=None, placeholder="Choose a device", disabled=state.connected)
        manual = st.text_input("Or enter a device address", disabled=state.connected,
                               help="Bluetooth address on Windows/Linux; device UUID on macOS.")
        target = manual.strip() or found or ""
        st.caption("Connect subscribes to replies and enters remote mode. First pairing with this Python port is still unverified.")
    else:
        st.caption("Mock mode sends to a simulated doll. It never scans or opens a Bluetooth connection.")
    connect_col, disconnect_col, _ = st.columns([1, 1, 4])
    if connect_col.button("Connect", type="primary", disabled=state.connected or (mode == "bluetooth" and not target)):
        with st.spinner("Connecting…"):
            if perform(worker.connect, mode, target):
                st.rerun()
    if disconnect_col.button("Disconnect", disabled=not state.connected):
        if perform(worker.disconnect):
            st.rerun()

connection_rendered = state.connected


@st.fragment(run_every="1s")
def command_panel():
    state = worker.snapshot()
    if state.closed:
        st.rerun()
    if state.connected != connection_rendered:
        st.rerun()
    worker.touch()
    status_col, stop_col = st.columns([4, 1])
    status_col.markdown(f"**{'🟢' if state.connected else '⚪'} {state.status}**")
    if state.error:
        status_col.error(state.error)
    if stop_col.button("⏹ Stop", type="primary", disabled=not state.connected, key="stop"):
        perform(worker.stop)
        state = worker.snapshot()
    if state.blocked:
        st.warning("Playback was not confirmed. Stop has been attempted; press Stop to reset before sending another command.")

    group = st.radio("Command group", ["Audio phrases", "High-level routines"], horizontal=True, key="group")
    kind = "audio" if group == "Audio phrases" else "sequence"
    table = AUDIO if kind == "audio" else SEQUENCES
    search_col, grid_col = st.columns([3, 1])
    query = search_col.text_input("Filter by name or wire number", key="filter", placeholder="eP008, DanceInstruct, Spin…")
    grid_width = grid_col.selectbox("Grid columns", [3, 4, 5, 6], index=1, key="grid_width")
    matches = [entry for entry in table.values()
               if query.lower() in entry.name.lower() or query == str(entry.id)]
    st.caption(f"{len(matches)} of {len(table)} entries · names do not identify the spoken text")
    movement = st.checkbox("Enable high-level routines that may move Belle", key="allow_movement") if kind == "sequence" else False
    if kind == "sequence":
        st.caption("These are stored high-level routines. A name such as Spin does not prove it moves the motors or launches a full lesson.")
    direct = st.toggle("Send when a grid button is clicked", value=False, key="direct_send")
    if direct:
        st.caption("Grid buttons send one command to the connected mock or doll. Completion is awaited before another command is allowed.")
    else:
        st.caption("Grid buttons select and preview a command. Use Send selected to transmit it.")
    allowed = state.connected and not state.busy and not state.blocked and (kind == "audio" or movement)

    page_size = 24
    pages = max(1, math.ceil(len(matches) / page_size))
    if st.session_state.get("page", 1) > pages:
        st.session_state.page = 1
    page = st.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key="page")
    visible = matches[(page - 1) * page_size:page * page_size]
    for start in range(0, len(visible), grid_width):
        columns = st.columns(grid_width)
        for column, entry in zip(columns, visible[start:start + grid_width]):
            label = entry.name if kind == "audio" else entry.name.removeprefix("eHLS_").replace("_", " ")
            if column.button(label, key=f"grid_{kind}_{entry.name}", width="stretch",
                             help=f"{entry.name} · wire ID {entry.id} · approximately {entry.duration:.3f}s",
                             disabled=state.busy or (direct and not allowed)):
                st.session_state[f"selected_{kind}"] = entry.name
                if direct:
                    perform(worker.send, kind, entry.name, allow_movement=movement)
    if not matches:
        st.info("No matching commands. Try a shorter name or clear the filter.")

    selected = st.session_state.get(f"selected_{kind}")
    if selected:
        entry = table[selected]
        packet = (play_audio if kind == "audio" else play_sequence)(selected)
        st.markdown(f"**Selected:** `{selected}` · wire ID **{entry.id}** · approximately **{entry.duration:.3f}s**")
        st.code(packet.hex(" "), language="text")
        if st.button("Send selected", disabled=not allowed, key="send_selected", type="primary"):
            perform(worker.send, kind, selected, allow_movement=movement)

    with st.expander("Volume and input"):
        volume = st.slider("Volume", min_value=0, max_value=5, value=3, key="volume")
        c1, c2, c3 = st.columns(3)
        if c1.button("Set volume", disabled=not state.connected or state.busy):
            perform(worker.control, "volume", volume)
        if c2.button("Read volume", disabled=not state.connected):
            perform(worker.control, "read_volume")
        if c3.button("Read input", disabled=not state.connected):
            perform(worker.control, "read_input")
        st.caption("Last reported volume: " + (str(state.volume) if state.volume is not None else "unknown"))

    st.subheader("Command transcript")
    keepalive = st.checkbox("Show keep-alives", key="show_keepalive")
    events = worker.events(include_keepalive=keepalive)
    if events:
        st.dataframe(events, width="stretch", hide_index=True)
        st.download_button("Download transcript", json.dumps(events, indent=2),
                           file_name="belle-transcript.json", mime="application/json", key="download_transcript")
    else:
        st.caption("Connect or select a command to begin. Sent commands and replies appear here.")
    st.caption("Stop uses the connection; if Belle moves unexpectedly and the connection is lost, use her physical power switch. Closing or abandoning this page expires the connection after 75 seconds without page updates.")


command_panel()
