"""
test_mp_join.py

Standalone check of /api/mp/join's three join_method branches, run
without a real Flask install (Flask isn't available in this dev
sandbox). Stubs just enough of flask's surface (Flask, jsonify,
request, send_file, send_from_directory) for app.py to import and for
its route functions to be called directly as plain Python functions.

Not a pytest suite -- run directly:
    python3 test_mp_join.py
Exits non-zero and prints which assertion failed if anything's wrong;
prints "ALL OK" and exits 0 if every branch behaves.
"""

import importlib.util
import json
import os
import sys
import types

APP_DIR = os.path.dirname(os.path.abspath(__file__))
COMMON_DIR = os.path.join(APP_DIR, "..", "common")
sys.path.insert(0, COMMON_DIR)
sys.path.insert(0, APP_DIR)

# ---- stub flask ----
flask_stub = types.ModuleType("flask")


class _FakeRequest:
    _json = None

    def get_json(self, force=True, silent=True):
        return self._json


fake_request = _FakeRequest()


class _FakeApp:
    def __init__(self, *a, **kw):
        pass

    def route(self, *a, **kw):
        def deco(f):
            return f
        return deco


def fake_jsonify(obj):
    return ("JSONIFIED", obj)


def fake_send_file(*a, **kw):
    return None


def fake_send_from_directory(*a, **kw):
    return None


flask_stub.Flask = _FakeApp
flask_stub.jsonify = fake_jsonify
flask_stub.request = fake_request
flask_stub.send_file = fake_send_file
flask_stub.send_from_directory = fake_send_from_directory
sys.modules["flask"] = flask_stub

# ---- load app.py as a module ----
spec = importlib.util.spec_from_file_location("pod_app", os.path.join(APP_DIR, "app.py"))
pod_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pod_app)

failures = []


def check(label, cond):
    if not cond:
        failures.append(label)
        print(f"FAIL: {label}")
    else:
        print(f"ok:   {label}")


BODY = {
    "server_ip": "192.168.1.50",
    "server_port": 9641,
    "server_http_port": 8641,
    "car_id": "ks_ferrari_488_gt3",
    "track_id": "spa",
    "customer_name": "Chad",
    "password": "",
}


def run_case(join_method, expect_fn_name):
    fake_request._json = dict(BODY)

    # Force get_config()/get_mp_config() caches so we control join_method
    # and don't need real packs.json/mp_config.json on disk for this check.
    pod_app._config_cache = {"drive_click": {"enabled": False}}
    pod_app._mp_config_loaded = True
    pod_app._mp_config_cache = {"pod_id": "pod1", "control_pc_url": "x", "join_method": join_method}

    calls = {}

    def fake_join_online_server(**kwargs):
        calls["join_online_server"] = kwargs
        return "acmanager://race/online/join?FAKE"

    def fake_join_online_server_direct(**kwargs):
        calls["join_online_server_direct"] = kwargs
        return "acmanager://race/online?FAKE"

    orig_a, orig_b = pod_app.join_online_server, pod_app.join_online_server_direct
    pod_app.join_online_server = fake_join_online_server
    pod_app.join_online_server_direct = fake_join_online_server_direct
    try:
        status, payload = pod_app.api_mp_join()
    finally:
        pod_app.join_online_server = orig_a
        pod_app.join_online_server_direct = orig_b

    check(f"[{join_method}] response status is JSONIFIED", status == "JSONIFIED")
    check(f"[{join_method}] method field == {join_method}", payload.get("method") == join_method)
    check(f"[{join_method}] {expect_fn_name} was called, and only that one",
          expect_fn_name in calls and len(calls) == 1)
    return calls.get(expect_fn_name, {})


# ---- content_manager (dialog) branch ----
kwargs = run_case("content_manager", "join_online_server")
check("[content_manager] ip passed through", kwargs.get("ip") == BODY["server_ip"])
check("[content_manager] http_port passed through (int)", kwargs.get("http_port") == BODY["server_http_port"])
check("[content_manager] no car/track/name params (join_online_server doesn't take them)",
      "car" not in kwargs and "track" not in kwargs and "name" not in kwargs)

# ---- content_manager_direct (no dialog) branch -- the new one ----
kwargs = run_case("content_manager_direct", "join_online_server_direct")
check("[content_manager_direct] ip passed through", kwargs.get("ip") == BODY["server_ip"])
check("[content_manager_direct] port (raw UDP) passed through, distinct from http_port",
      kwargs.get("port") == BODY["server_port"])
check("[content_manager_direct] http_port passed through", kwargs.get("http_port") == BODY["server_http_port"])
check("[content_manager_direct] car_id carried through as 'car'", kwargs.get("car") == BODY["car_id"])
check("[content_manager_direct] track_id carried through as 'track'", kwargs.get("track") == BODY["track_id"])
check("[content_manager_direct] customer_name carried through as 'name'", kwargs.get("name") == BODY["customer_name"])

if failures:
    print(f"\n{len(failures)} FAILURE(S)")
    sys.exit(1)
print("\nALL OK")
