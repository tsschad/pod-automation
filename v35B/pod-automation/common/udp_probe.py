"""
udp_probe.py

A minimal UDP echo test, with nothing Assetto-Corsa-related involved
at all -- built to answer one question directly: can raw UDP packets
actually get from a pod to the control PC (and back) on the port
acServer uses, or is something in the network path (a firewall rule,
VPN/security software, AP client isolation, a subnet/VLAN boundary)
blocking UDP specifically while TCP/HTTP keeps working fine?

Why this exists: every HTTP-based thing between a pod and the control
PC (pod registration, the admin GUI, acServer's own /INFO status
check) has worked. The only two things that have failed on real
hardware are both UDP -- AC's "Failed to connect: handshake failed"
joining a real acServer instance, and AC's own LAN server browser
finding zero servers on a network where one is confirmed running (LAN
discovery works via UDP broadcast, a completely different mechanism
from the point-to-point join, so both failing independently is a
strong signal, not a coincidence). This tool isolates the "is UDP
getting through at all" question from "is race.ini/acServer configured
right", since AC's own error message doesn't distinguish the two.

Usage
-----
On the control PC (or wherever acServer runs), start the listener:
    python udp_probe.py serve --port 9601

On a pod, send a probe at it:
    python udp_probe.py client --ip 192.168.86.200 --port 9601

A successful round-trip prints a clear "REACHABLE" line on the client
and logs the incoming packet on the server. No response within the
timeout prints "NOT REACHABLE" and is the concrete evidence needed to
go chase down a firewall rule, VPN/security client, or network
topology issue instead of anything in this codebase.
"""

import argparse
import socket
import sys
import time

DEFAULT_PORT = 9601
DEFAULT_TIMEOUT_SECONDS = 3.0
PING_MESSAGE = b"pod-automation-udp-probe-ping"
PONG_PREFIX = b"pod-automation-udp-probe-pong:"


def cmd_serve(args: argparse.Namespace) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    print(f"[udp_probe] Listening for UDP packets on 0.0.0.0:{args.port} -- "
          f"leave this running, then run the client from a pod pointed at "
          f"this machine's IP and this port. Ctrl+C to stop.")
    try:
        while True:
            data, addr = sock.recvfrom(1024)
            print(f"[udp_probe] Received {data!r} from {addr[0]}:{addr[1]} -- replying")
            sock.sendto(PONG_PREFIX + f"{addr[0]}:{addr[1]}".encode(), addr)
    except KeyboardInterrupt:
        print("\n[udp_probe] Stopped.")
    finally:
        sock.close()


def cmd_client(args: argparse.Namespace) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(args.timeout)
    target = (args.ip, args.port)

    print(f"[udp_probe] Sending a UDP packet to {args.ip}:{args.port} "
          f"(timeout {args.timeout}s)...")
    t0 = time.time()
    try:
        sock.sendto(PING_MESSAGE, target)
        data, addr = sock.recvfrom(1024)
        elapsed = time.time() - t0
        print(f"[udp_probe] REACHABLE -- got a reply from {addr[0]}:{addr[1]} "
              f"in {elapsed*1000:.0f}ms: {data!r}")
        print("[udp_probe] UDP is getting through fine on this port -- the "
              "handshake failure is NOT a network/firewall/UDP-blocking "
              "issue, look elsewhere (race.ini content, acServer config, "
              "Steam/GUID).")
    except socket.timeout:
        elapsed = time.time() - t0
        print(f"[udp_probe] NOT REACHABLE -- no reply after {elapsed:.1f}s.")
        print("[udp_probe] UDP is NOT getting through on this port between "
              "these two machines. This is consistent with the handshake "
              "failure and the empty LAN browser -- go look at: a firewall "
              "rule specifically for UDP (separate from any TCP/HTTP rule "
              "already allowed), VPN or security software that only proxies "
              "TCP, or whether these two machines are actually on the same "
              "network segment (a router/VLAN boundary between them would "
              "block this).")
    except OSError as exc:
        print(f"[udp_probe] Error sending/receiving: {exc}")
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the listener (on the control PC).")
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"UDP port to listen on (default {DEFAULT_PORT}, acServer instance 1's port).")
    p_serve.set_defaults(func=cmd_serve)

    p_client = sub.add_parser("client", help="Send a probe (from a pod).")
    p_client.add_argument("--ip", required=True, help="Control PC's LAN IP.")
    p_client.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"UDP port to probe (default {DEFAULT_PORT}).")
    p_client.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help=f"Seconds to wait for a reply (default {DEFAULT_TIMEOUT_SECONDS}).")
    p_client.set_defaults(func=cmd_client)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
