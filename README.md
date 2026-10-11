# Dance Code Belle

An offline-first Python library for commanding the Disney Princess Dance Code
Belle doll over Bluetooth Low Energy. Built from the protocol and identifier
tables in Thanh Bui's supplied `Assembly-CSharp.rar` C# archive.

**Status: packet encoding and client behavior tested offline; physical Bluetooth
connection, pairing and playback are not yet verified with this Python port.**
The owner previously had speech working from C#. This repository does not claim
that the Python transport has already reproduced that result on hardware.

## What works in the library

- Encode and preview playback packets without Bluetooth dependencies.
- Select from 421 existing audio phrase identifiers and their estimated durations.
- Inspect 454 named high-level sequence identifiers and estimated durations.
- Scan for `DanceCD` and connect through the optional Bleak adapter.
- Explicitly enter remote mode, send its one-second keep-alive, and exit it.
- Play a stored phrase, request input/volume, set volume from 0 to 5, and stop playback.
- Match completion notifications and use timeouts without automatically retrying playback.
- Play named high-level routines when movement is explicitly enabled.
- Exercise the same controller through a recording mock transport.

`speak()` selects an existing recording in Belle. It does not synthesize speech or
accept arbitrary text. Phrase labels are not spoken transcripts. High-level
routine names are clues to function, not a guarantee that the routine is audio
only or a complete built-in dance lesson.

## Install and preview

Python 3.10 or newer. From this checkout:

```sh
python -m pip install .
belle catalog --filter eP008
belle speak eP008
python examples/offline.py
python -m unittest discover -s tests -v
```

`belle speak eP008` prints `10 06 00` and exits without contacting a doll.
If your installation's scripts directory is not on your executable search path,
use `python -m dance_code_belle speak eP008` (and the same form for other commands).
`eP008` has wire ID **6**, because the source enum is zero based and skips some
phrase labels. Use names or `AudioPhrase` members rather than converting the
digits in a name to an integer.

The offline example records:

```text
50 8d       enter/maintain remote mode
10 00 00    play eP001 (wire ID 0)
12          stop the command queue
18 ff       stop active sequences
50 8c       end remote mode
```

## Python usage without a doll

```python
import asyncio
from dance_code_belle import Belle, MockTransport, AudioPhrase

async def main():
    transport = MockTransport()
    async with Belle(transport) as belle:
        await belle.start_remote_mode()
        await belle.speak(AudioPhrase.eP008, wait=False)
        await belle.stop()
    print([packet.hex(" ") for packet in transport.packets])

asyncio.run(main())
```

The mock records writes and only sends simulated notifications when `emit()` is
called. It does not invent acknowledgements or claim hardware success.

## Connect to physical Belle

Install Bluetooth support, turn on Belle, and scan:

```sh
python -m pip install ".[ble]"
belle scan
```

Scanning does not connect. Connecting subscribes to the notification
characteristic; that subscription writes a Bluetooth notification descriptor,
but no Belle application command is sent until a controller method is called.
The adapter checks both known characteristics and requires them to belong to the
same discovered service. It does not guess a service identifier.

After reviewing a known phrase, one command can be transmitted explicitly:

```sh
belle speak eP008 --address DEVICE_FROM_SCAN --execute
```

The command enters remote mode, waits for the matching completion notification,
then attempts to stop playback, exit remote mode and disconnect. A timeout means
completion was not confirmed; it is **not** a reason to resend the command.
The Python connection sequence still needs verification. The supplied archive
references a necklace pairing coroutine whose body is absent. If pairing fails,
stop and recover the missing routine or compare a known-working C# connection.

For a Python application, preserve a discovered `BLEDevice` when possible:

```python
import asyncio
from dance_code_belle import Belle, BleakTransport, discover

async def main():
    devices = await discover()
    if len(devices) != 1:
        raise RuntimeError("Select your own Belle explicitly when the scan is ambiguous")
    async with Belle(BleakTransport(devices[0])) as belle:
        await belle.start_remote_mode()
        try:
            await belle.speak("eP008")
        finally:
            await belle.stop()

asyncio.run(main())
```

Use a single controller per doll. Await playback completion before starting the
next clip. `wait=False` sends once and returns; the caller must manage timing and
avoid overlapping playback. `close()` exits remote mode and disconnects; call
`stop()` explicitly when you want to stop an active routine before closing.

## High-level routines and dance training

```sh
belle catalog --sequences --filter DanceInstruct
belle sequence eHLS_DanceInstruct_1
```

The second command previews `17 02 3b 00`. It does not move Belle.
Actual transmission requires both `--execute` and `--allow-movement`. In Python,
construct `Belle(..., allow_sequences=True)` and call `play_sequence()`.

The archive exposes dance instruction fragments, introductions, names and many
other high-level sequences. It has not established a single command for starting
one of the ten full necklace-triggered lessons. No such convenience method is
invented here. Raw motor control, arbitrary command queues, passwords, firmware
transfer and bootloader functions are outside this library's initial scope.

## Development and provenance

See [protocol notes](docs/protocol.md), [validation](docs/validation.md), and
[source fingerprints](docs/source-fingerprints.json).

The original archive, decompiled Unity application, DLL dependencies, voice
recordings and artwork are not bundled in this repository. The catalog preserves
observed protocol names, IDs and durations. This is an independent project and
does not imply affiliation with Disney or Hasbro. The Python library uses the
[MIT license](LICENSE) selected for this repository. Third-party names and assets
remain the property of their respective owners.
