"""Run from an installed checkout. This never imports Bleak or contacts hardware."""
import asyncio
from dance_code_belle import Belle, MockTransport, AudioPhrase


async def main():
    transport = MockTransport()
    async with Belle(transport) as belle:
        await belle.start_remote_mode()
        await belle.speak(AudioPhrase.eP001, wait=False)
        await belle.stop()
    print("Offline command transcript:")
    for packet in transport.packets:
        print(packet.hex(" "))


if __name__ == "__main__":
    asyncio.run(main())
