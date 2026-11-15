"""python -m generator run --scenario solar_storm --astronaut A1 --time-scale 60"""

import argparse
import json
import sys
import time

from generator.client import post_envelope
from generator.engine import iter_batches, list_scenarios, load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generator")
    parser.add_argument("command", choices=["run", "list", "serve"])
    parser.add_argument("--scenario")
    parser.add_argument("--scenario-file")
    parser.add_argument("--plan")
    parser.add_argument("--astronaut")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--device-token", default="")
    parser.add_argument("--time-scale", type=float, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args(argv)
    if args.command == "list":
        for name in list_scenarios():
            print(name)
        return 0
    if args.command == "serve":
        import uvicorn

        uvicorn.run("generator.webapp:app", host=args.host, port=args.port, reload=False)
        return 0
    name = args.plan or args.scenario or "nominal"
    scenario = load_scenario(name if not args.scenario_file else None, args.scenario_file)
    base = time.time()
    step = max(args.time_scale, 1.0)
    for envelope in iter_batches(scenario, args.seed, args.time_scale, base, args.duration, args.astronaut):
        if args.no_network:
            print(json.dumps(envelope, ensure_ascii=False))
            continue
        if not args.device_token:
            print("device token required", file=sys.stderr)
            return 2
        post_envelope(args.backend, args.device_token, envelope)
        time.sleep(step / args.time_scale if args.time_scale else 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
