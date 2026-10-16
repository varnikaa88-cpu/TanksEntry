import json
import time
import threading
import random
from datetime import datetime

import pandas as pd
import streamlit as st
import paho.mqtt.client as mqtt

st.set_page_config(
    page_title="TANKSENTRY",
    page_icon="💧",
    layout="wide"
)

BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC = "tanksentry/demo7264/status"
COMMAND_TOPIC = "tanksentry/demo7264/command"


@st.cache_resource
def get_mqtt_store():
    return {
        "lock": threading.Lock(),
        "connected": False,
        "latest": None,
        "history": [],
        "error": None,
        "client": None,
    }


def start_mqtt():
    store = get_mqtt_store()

    if store["client"] is not None:
        return store

    def on_connect(client, userdata, flags, reason_code, properties):
        with store["lock"]:
            store["connected"] = (reason_code == 0)
            store["error"] = (
                None if reason_code == 0
                else f"MQTT connection failed: {reason_code}"
            )
        if reason_code == 0:
            client.subscribe(TOPIC, qos=0)

    def on_disconnect(client, userdata, disconnect_flags,
                      reason_code, properties):
        with store["lock"]:
            store["connected"] = False

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Message must be a JSON object")

            level = float(data["level"])
            if not 0 <= level <= 100:
                raise ValueError("Water level must be between 0 and 100")

            row = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level_pct": round(level, 1),
                "distance_cm": float(data["distance"]),
                "pump_on": bool(data["pump_on"]),
                "alarm": bool(data["alarm"]),
                "sensor_fault": bool(data["sensor_fault"]),
            }

            with store["lock"]:
                store["latest"] = row
                store["history"].append(row)
                store["history"] = store["history"][-180:]
                store["error"] = None

        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            with store["lock"]:
                store["error"] = f"Invalid MQTT message: {exc}"

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"tanksentry-dashboard-{random.randint(100000, 999999)}",
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    store["client"] = client

    try:
        client.connect(BROKER, PORT, keepalive=60)
        client.loop_start()
    except Exception as exc:
        with store["lock"]:
            store["error"] = str(exc)

    return store
def publish_command(command):
    store = get_mqtt_store()

    with store["lock"]:
        client = store["client"]
        connected = store["connected"]

    if client is None or not connected:
        return False, "MQTT is not connected."

    try:
        result = client.publish(
            COMMAND_TOPIC,
            command,
            qos=0,
            retain=False,
        )

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            return False, f"Command publish failed: {result.rc}"

        return True, f"{command} command sent."

    except Exception as exc:
        return False, f"Could not send command: {exc}"

def reset_simulation():
    now = time.time()
    st.session_state.level = 35.0
    st.session_state.simulation_running = True
    st.session_state.pump_on = False
    st.session_state.leak_on = False
    st.session_state.sensor_fault = False
    st.session_state.pump_fault = False
    st.session_state.history = []
    st.session_state.log_rows = []
    st.session_state.last_tick = now
    st.session_state.last_level = 35.0
    st.session_state.last_change_time = now


defaults = {
    "level": 35.0,
    "simulation_running": True,
    "pump_on": False,
    "leak_on": False,
    "sensor_fault": False,
    "pump_fault": False,
    "history": [],
    "last_tick": time.time(),
    "last_level": 35.0,
    "last_change_time": time.time(),
    "log_rows": [],
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


st.title("💧 TANKSENTRY — Water Tank Monitoring")
mode = st.radio(
    "Choose data source",
    ["Simulation mode", "Live ESP32 mode"],
    horizontal=True,
)

if mode == "Live ESP32 mode":
    st.caption("Live readings received through HiveMQ MQTT.")
    store = start_mqtt()

    with store["lock"]:
        connected = store["connected"]
        latest = dict(store["latest"]) if store["latest"] else None
        history = list(store["history"])
        error = store["error"]

    if connected:
        st.success("Connected to the MQTT broker.")
    else:
        st.warning("Connecting to MQTT, or connection unavailable.")

    st.caption(f"Status topic: {TOPIC}")
    st.subheader("Remote pump controls")
    st.caption(f"Command topic: {COMMAND_TOPIC}")

    col_on, col_off, col_auto = st.columns(3)

    with col_on:
        if st.button("🟢 Pump ON", use_container_width=True):
            ok, message = publish_command("ON")
            if ok:
                st.success(message)
            else:
                st.error(message)

    with col_off:
        if st.button("🔴 Pump OFF", use_container_width=True):
            ok, message = publish_command("OFF")
            if ok:
                st.success(message)
            else:
                st.error(message)

    with col_auto:
        if st.button("🔄 Automatic mode", use_container_width=True):
            ok, message = publish_command("AUTO")
            if ok:
                st.success(message)
            else:
                st.error(message)

    if error:
        st.error(error)
    if latest is None:
        st.info(
            "Waiting for an ESP32 message. Keep Wokwi running and "
            "check that the ESP32 publishes to the exact topic above."
        )
    else:
        level = latest["level_pct"]
        pump = latest["pump_on"]
        sensor_fault = latest["sensor_fault"]
        alarm = latest["alarm"]

        if sensor_fault:
            status = "SENSOR FAULT"
        elif alarm:
            status = "ALARM"
        elif level >= 90:
            status = "HIGH LEVEL"
        elif level <= 15:
            status = "LOW LEVEL"
        elif alarm:
            status = "ALARM"
        else:
            status = "NORMAL"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Water level", f"{level:.1f}%")
        m2.metric("Pump", "ON" if pump else "OFF")
        m3.metric("Sensor", "FAULT" if sensor_fault else "OK")
        m4.metric("System status", status)

        left, right = st.columns(2)
        with left:
            st.subheader("Tank level")
            if sensor_fault:
                st.error("Sensor fault reported by ESP32.")
            else:
                st.progress(
                    int(level),
                    text=f"{level:.1f}% full"
                )
            st.metric("Sensor distance", f'{latest["distance_cm"]:.1f} cm')

        with right:
            st.subheader("Alerts")
            if sensor_fault:
                st.error("ESP32 reports a sensor fault.")
            if alarm:
                st.warning("ESP32 alarm is active.")
            if level >= 90:
                st.warning("High water level reported.")
            if not sensor_fault and not alarm and level < 90:
                st.success("No active alarm reported.")

        st.caption(f'Last message received: {latest["time"]}')

        if history:
            st.subheader("Live water-level trend")
            df = pd.DataFrame(history)
            st.line_chart(df.set_index("time")[["level_pct"]])
            st.dataframe(df.tail(15), use_container_width=True)

    st.caption(
        "Live mode shows values published by the ESP32. "
        "Alerts are based on the received fields and level thresholds."
    )

else:
    st.caption("Python-only simulator — no physical sensor required.")

    st.sidebar.header("Simulation controls")
    st.sidebar.toggle("Run simulation", key="simulation_running")
    st.sidebar.toggle("Request pump ON", key="pump_on")
    st.sidebar.toggle("Simulate leak / rapid drain", key="leak_on")
    st.sidebar.toggle("Simulate pump failure (no filling)", key="pump_fault")
    st.sidebar.toggle("Simulate sensor failure", key="sensor_fault")
    st.sidebar.button("Reset simulation", on_click=reset_simulation)

    now = time.time()
    dt = min(max(now - st.session_state.last_tick, 0.0), 2.0)
    st.session_state.last_tick = now

    if st.session_state.simulation_running:
        if (st.session_state.pump_on
                and not st.session_state.pump_fault
                and not st.session_state.sensor_fault):
            st.session_state.level += 2.0 * dt
        if st.session_state.leak_on:
            st.session_state.level -= 3.5 * dt
        st.session_state.level = max(
            0.0, min(100.0, st.session_state.level)
        )

    level = st.session_state.level
    pump_on = st.session_state.pump_on
    sensor_fault = st.session_state.sensor_fault
    pump_fault = st.session_state.pump_fault
    leak_on = st.session_state.leak_on

    if abs(level - st.session_state.last_level) >= 0.5:
        st.session_state.last_change_time = now
    st.session_state.last_level = level

    if st.session_state.simulation_running:
        row = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level_pct": round(level, 1),
            "pump_requested": pump_on,
            "sensor_ok": not sensor_fault,
            "pump_fault_simulated": pump_fault,
            "leak_simulated": leak_on,
        }
        st.session_state.history.append(row)
        st.session_state.history = st.session_state.history[-180:]
        st.session_state.log_rows.append(row)
        st.session_state.log_rows = st.session_state.log_rows[-2000:]

    alerts = []
    if sensor_fault:
        displayed_level = None
        status = "SENSOR FAULT"
        alerts.append("Sensor reading unavailable.")
    else:
        displayed_level = level
        if level >= 90:
            status = "HIGH LEVEL"
            alerts.append("High water level: filling should stop.")
        elif level <= 15:
            status = "LOW LEVEL"
            alerts.append("Low water level.")
        else:
            status = "NORMAL"

    if pump_on and pump_fault:
        alerts.append("Pump requested ON, but simulated pump is not filling.")
    if leak_on:
        alerts.append("Leak / rapid-drain scenario is active.")
    if pump_on and level >= 90:
        alerts.append("FULL-TANK WARNING: simulated warning only.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Water level",
        "Unavailable" if displayed_level is None else f"{displayed_level:.1f}%"
    )
    m2.metric("Pump request", "ON" if pump_on else "OFF")
    m3.metric("Sensor", "FAULT" if sensor_fault else "OK")
    m4.metric("System status", status)

    left, right = st.columns(2)
    with left:
        st.subheader("Tank level")
        if displayed_level is None:
            st.error("No reliable water-level reading.")
        else:
            st.progress(int(level), text=f"{level:.1f}% full")
            st.caption("Illustrative simulated value.")
    with right:
        st.subheader("Alerts")
        if alerts:
            for alert in alerts:
                st.warning(alert)
        else:
            st.success("No active warnings.")

    st.subheader("Water-level trend")
    if st.session_state.history:
        df = pd.DataFrame(st.session_state.history)
        st.line_chart(df.set_index("time")[["level_pct"]])
        with st.expander("Show recent simulated data"):
            st.dataframe(df.tail(15), use_container_width=True)
    else:
        st.info("Start the simulation to collect readings.")

    if st.session_state.log_rows:
        csv = pd.DataFrame(st.session_state.log_rows).to_csv(
            index=False
        ).encode("utf-8")
        st.download_button(
            "Download simulation log (CSV)",
            data=csv,
            file_name="tanksentry_simulation_log.csv",
            mime="text/csv",
        )

    st.caption(
        "Simulation only: pump, sensor, leak and fault behaviours "
        "are software-generated."
    )

if mode == "Simulation mode" and st.session_state.simulation_running:
    time.sleep(1)
    st.rerun()
elif mode == "Live ESP32 mode":
    time.sleep(1)
    st.rerun()
