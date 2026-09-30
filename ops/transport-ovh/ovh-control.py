#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time

import ovh

SERVICE = os.getenv("OVH_VPS_SERVICE_NAME", "vps-a13eee97.vps.ovh.us")
ENDPOINT = os.getenv("OVH_ENDPOINT", "ovh-us")


def client():
    required = {
        "OVH_APPLICATION_KEY": os.getenv("OVH_APPLICATION_KEY"),
        "OVH_APPLICATION_SECRET": os.getenv("OVH_APPLICATION_SECRET"),
        "OVH_CONSUMER_KEY": os.getenv("OVH_CONSUMER_KEY"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise SystemExit("Missing required secret(s): " + ", ".join(missing))
    return ovh.Client(
        endpoint=ENDPOINT,
        application_key=required["OVH_APPLICATION_KEY"],
        application_secret=required["OVH_APPLICATION_SECRET"],
        consumer_key=required["OVH_CONSUMER_KEY"],
    )


def get_state(c):
    data = c.get(f"/vps/{SERVICE}")
    return {
        "serviceName": SERVICE,
        "state": data.get("state"),
        "netbootMode": data.get("netbootMode"),
        "zone": data.get("zone"),
        "displayName": data.get("displayName"),
    }


def wait_for(c, *, netboot=None, states=None, timeout=240):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = get_state(c)
        netboot_ok = netboot is None or last.get("netbootMode") == netboot
        state_ok = states is None or last.get("state") in states
        if netboot_ok and state_ok:
            return last
        time.sleep(5)
    raise SystemExit(f"Timed out waiting for OVH VPS state; last={json.dumps(last)}")


def set_boot(c, mode):
    if mode not in {"local", "rescue"}:
        raise SystemExit(f"Unsupported netboot mode: {mode}")
    c.put(f"/vps/{SERVICE}", netbootMode=mode)
    return wait_for(c, netboot=mode, timeout=120)


def reboot(c):
    c.post(f"/vps/{SERVICE}/reboot")
    return wait_for(c, states={"running", "rescued"}, timeout=300)


def ensure_normal(c):
    state = get_state(c)
    if state.get("netbootMode") == "local":
        return state
    set_boot(c, "local")
    return reboot(c)


def main():
    p = argparse.ArgumentParser(description="Controlled OVH VPS operations for the FGB transport host")
    p.add_argument("action", choices=["status", "reboot", "normal", "ensure-normal", "rescue"])
    args = p.parse_args()
    c = client()

    if args.action == "status":
        result = get_state(c)
    elif args.action == "reboot":
        result = reboot(c)
    elif args.action == "normal":
        set_boot(c, "local")
        result = reboot(c)
    elif args.action == "ensure-normal":
        result = ensure_normal(c)
    elif args.action == "rescue":
        set_boot(c, "rescue")
        result = reboot(c)
    else:
        raise AssertionError(args.action)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ovh.exceptions.APIError as exc:
        print(f"OVH API error: {exc}", file=sys.stderr)
        raise SystemExit(2)
