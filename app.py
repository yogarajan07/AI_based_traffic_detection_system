from flask import Flask, jsonify, request
from flask_cors import CORS
import time

app = Flask(__name__)
CORS(app)  # Enable for local frontend testing

# System/Intersection state (simple in-memory model)
state = {
    "mode": "vehicle",  # or "standard"
    "counts": {"N": 0, "E": 0, "S": 0, "W": 0},       # queue preset
    "waiting": {"N": 0, "E": 0, "S": 0, "W": 0},      # dynamic per tick
    "served": 0,
    "current_lane": None,
    "phase": "idle",   # "green", "yellow", "idle"
    "green_time": 20,
    "yellow_time": 3,
    "release_interval": 0.6,
    "green_elapsed": 0,
    "yellow_elapsed": 0,
    "last_release": 0,
    "last_tick": 0,
    "vehicle_moving": 0,
    "running": False,
    "logs": [],
    "last_lane": None
}
dir_order = ['N', 'E', 'S', 'W']
dirs = {
    "N": ["E", "S", "W"],
    "E": ["S", "W", "N"],
    "S": ["W", "N", "E"],
    "W": ["N", "E", "S"]
}


def log(msg):
    state["logs"].insert(0, f"[{time.strftime('%H:%M:%S')}] {msg}")
    state["logs"] = state["logs"][:50]

@app.route('/api/status')
def status():
    # Send current state (minus a few unneeded values)
    resp = {k: v for k, v in state.items() if k != "logs"}
    resp["logs"] = state["logs"][:12]
    return jsonify(resp)

@app.route('/api/set_mode', methods=["POST"])
def set_mode():
    m = request.json.get("mode", None)
    if m not in ("vehicle", "standard"):
        return jsonify({"error": "Invalid mode"}), 400
    state["mode"] = m
    log(f"Switched mode to {m}")
    return jsonify(state)

@app.route('/api/set_counts', methods=["POST"])
def set_counts():
    for d in ["N", "E", "S", "W"]:
        val = request.json.get(d)
        if isinstance(val, int) and val >= 0:
            state["counts"][d] = val
            if not state["running"]:
                state["waiting"][d] = val
    return jsonify(state)

@app.route('/api/preset', methods=["POST"])
def preset():
    inp = request.json.get('preset', [0,0,0,0])
    for i, d in enumerate(dir_order):
        state["counts"][d] = max(0, inp[i])
        if not state["running"]:
            state["waiting"][d] = state["counts"][d]
    log("Preset vehicles updated")
    return jsonify(state)

@app.route('/api/config', methods=["POST"])
def config():
    for key in ['yellow_time', 'release_interval', 'green_time']:
        val = request.json.get(key)
        if val is not None:
            state[key] = float(val)
    return jsonify(state)

@app.route('/api/control', methods=['POST'])
def control():
    act = request.json.get("action","")
    if act == "start":
        for d in dir_order:
            state["waiting"][d] = state["counts"][d]
        state["served"] = 0
        state["vehicle_moving"] = 0
        state["phase"] = "idle"
        state["current_lane"] = None
        state["running"] = True
        state["last_lane"] = None
        log("Simulation started")
    elif act == "pause":
        state["running"] = False
        log("Simulation paused")
    elif act == "reset":
        state["counts"] = {d: 0 for d in dir_order}
        state["waiting"] = {d: 0 for d in dir_order}
        state["served"] = 0
        state["running"] = False
        state["phase"] = "idle"
        state["current_lane"] = None
        state["vehicle_moving"] = 0
        state["last_lane"] = None
        log('System reset')
    return jsonify(state)

# ---- Simulation step
@app.route('/api/tick', methods=["POST"])
def tick():
    if not state["running"]:
        return jsonify(state)
    now = time.time()
    dt = now - state.get("last_tick", now)
    state["last_tick"] = now

    # Vehicle release event logic.
    if state["phase"] == "green" and state["current_lane"]:
        # Release vehicle if waiting and enough time passed.
        rel_intvl = state["release_interval"]
        lane = state["current_lane"]
        if state["waiting"][lane] > 0 and (now-state.get("last_release",0))>=rel_intvl:
            state["waiting"][lane] -= 1
            state["served"] += 1
            state["vehicle_moving"] += 1  # simplified, instant move
            state["last_release"] = now
        # Green/yellow timing
        if state["mode"] == "vehicle":
            if state["waiting"][lane] == 0:
                state["phase"] = "yellow"
                state["yellow_elapsed"] = 0
                log(f"Cleared {lane}, Yellow.")
        else:  # standard
            state["green_elapsed"] += dt
            if state["green_elapsed"] > state["green_time"]:
                state["phase"] = "yellow"
                state["yellow_elapsed"] = 0
                log(f"Green time up for {lane}.")

    # On yellow, wait yellow_time then change lane or finish
    if state["phase"] == "yellow":
        state["yellow_elapsed"] += dt
        if state["yellow_elapsed"] >= state["yellow_time"]:
            state["phase"] = "idle"
            state["current_lane"] = None

    # If idle, pick next lane
    if state["phase"] == "idle":
        if state["mode"] == "standard":
            if not state["last_lane"]:
                nx = "N"
            else:
                ci = dir_order.index(state["last_lane"])
                nx = dir_order[(ci+1)%4]
            state["last_lane"] = nx
            state["phase"] = "green"
            state["current_lane"] = nx
            state["green_elapsed"] = 0
            state["last_release"] = now
            log(f"Green {nx} started.")
        else:  # vehicle-based
            # Pick lane with most waiting (if any)
            options = sorted([(v, d) for d, v in state["waiting"].items()], reverse=True)
            if options and options[0][0] > 0:
                nx = options[0][1]
                state["current_lane"] = nx
                state["phase"] = "green"
                state["green_elapsed"] = 0
                state["last_release"] = now
                log(f"Green {nx} started (vehicle-based).")
            else:
                state["current_lane"] = None
                state["phase"] = "idle"

    # Vehicle moves "complete" immediately after being "served"
    state["vehicle_moving"] = 0
    return jsonify(state)

if __name__ == "__main__":
    app.run(debug=True)
