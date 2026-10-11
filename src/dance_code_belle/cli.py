"""The command line previews playback packets unless --execute is supplied."""
import argparse
import asyncio
from .catalog import AUDIO, SEQUENCES
from .client import Belle
from .protocol import play_audio, play_sequence
from .transport import BleakTransport, discover


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="List names, IDs and estimated durations")
    catalog.add_argument("--sequences", action="store_true")
    catalog.add_argument("--filter", default="")
    scan = commands.add_parser("scan", help="Scan for DanceCD; do not connect")
    scan.add_argument("--timeout", type=float, default=10.0)
    for name in ("speak", "sequence"):
        command = commands.add_parser(name)
        command.add_argument("name", help="Exact catalog name, e.g. eP001")
        command.add_argument("--execute", action="store_true", help="Send to physical Belle")
        command.add_argument("--address", help="Explicit Bluetooth address or macOS device UUID")
        if name == "sequence":
            command.add_argument("--allow-movement", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "catalog":
            table = SEQUENCES if args.sequences else AUDIO
            for entry in table.values():
                if args.filter.lower() in entry.name.lower():
                    print(f"{entry.id:3d}  {entry.name:48s}  {entry.duration:.3f}s")
        elif args.command == "scan":
            for device in asyncio.run(discover(args.timeout)):
                print(f"{device.address}  {device.name}")
        else:
            packet = (play_sequence if args.command == "sequence" else play_audio)(args.name)
            if not args.execute:
                print("Preview only:", packet.hex(" "))
                return
            if not args.address:
                parser.error("--execute requires --address; run belle scan first")
            if args.command == "sequence" and not args.allow_movement:
                parser.error("Physical sequences require --allow-movement")
            asyncio.run(_execute(args))
    except (ValueError, RuntimeError, ConnectionError, TimeoutError) as exc:
        parser.exit(1, f"Error: {exc}\n")


async def _execute(args):
    async with Belle(BleakTransport(args.address), allow_sequences=args.command == "sequence") as belle:
        await belle.start_remote_mode()
        try:
            if args.command == "speak":
                await belle.speak(args.name)
            else:
                await belle.play_sequence(args.name)
        finally:
            await belle.stop()
