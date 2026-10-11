# Recovered protocol

The supplied archive contains a top-level C# project and a `Backup` copy. Core
identifier tables match. `BLEToyAPI.cs` is modified at the top level: its
connection coroutine definition is missing and `DisconnectFromToy` has a
commented-out coroutine call. The backup references compiler-generated iterator
classes that are not supplied either. This Python port implements transport
cleanup independently; it does not claim a complete migration of app pairing.

## Bluetooth endpoints

| Item | Observed value | Source |
| --- | --- | --- |
| Advertised name | `DanceCD` | `BLEToyAPI.toyNameFilter` |
| App to doll | `51901383-030F-4859-B643-256B0B2F5562` | `BLEToyAPI.appToToyCharacteristic` |
| Doll to app | `51901382-030F-4859-B643-256B0B2F5562` | `BLEToyAPI.toyToAppCharacteristic` |
| Service | Discover the service containing both characteristics | `onDiscoveredCharacteristic` |
| Write mode | Without response | `BluetoothHandler.SendCharacteristicData(..., false, ...)` |
| Packet maximum | Source warns above 20 bytes | `BLEToyAPI.SendPacketToToy` |
| Keep-alive | `50 8d`, approximately every second outside connected free play | `BLEToyAPI.Update`, `AppModeSignal` |

`BLEToyHandler.cs` uses the unrelated `Makers` name and `5DAE...` characteristics.
Those are not used by this port.

## Implemented application packets

| Operation | Bytes | Source |
| --- | --- | --- |
| Stored audio | `10 ID_LO ID_HI` | `BLEToyAPI.PlayAudioSequence` |
| High-level sequence | `17 02 ID_LO ID_HI` | `BLEToySequenceQueue.PlayHLSequence` |
| Stop command queue | `12` | `StopSequenceQueuePlayback` |
| Stop all sequences | `18 ff` | `StopSequence`, `BLEToyStopSequenceFlag.All` |
| Request input | `20` | `RequestInputState` |
| Request volume | `22` | `CheckToyVolume` |
| Set volume | `23 VALUE`, value 0–5 | `SetToyVolume` |
| Remote keep-alive | `50 8d` | `SendAppModeSignal(RCAppModeKeepAlive)` |
| End app mode | `50 8c` | `SendAppModeSignal(EndAppMode)` |

Two-byte IDs are encoded little endian, matching `BitConverter.GetBytes(ushort)`
on the original Android target. No extra checksum or packet header is present in
these source methods.

The original `PlayAudioSequence` and `PlayHLSequence` first cancel music fading,
which calls queue-stop/audio-stop helpers and may restore volume to 5. This port
does not silently reproduce those UI/music side effects; it provides explicit
stop and volume methods. A comparison against the owner's working controller
should include any preparation packets it sends.

## Decoded notifications

| Opcode | Payload | Interpretation |
| --- | --- | --- |
| `10` | 16-bit ID | Audio playlist ended |
| `13` | One byte | Queue free-space report (queue uploading not implemented) |
| `17` | Type byte, 16-bit ID | Sequence ended; type 2 is high level, type 5 is queue |
| `20` | Two input bytes | 16 input-state bits; necklace is bit 3 |
| `22` | One byte | Reported volume |
| `50` | One byte | App mode signal |
| Other | Preserve raw payload | Unknown/debug notifications |

Truncated known notifications are counted and ignored by the client. Unknown
notifications are retained. The recent-event queue is bounded to 128 entries;
old entries are dropped on overflow. Completion waiters match opcode, ID and
sequence type independently of that queue. Playback is never automatically
retried, including when a completion notification is missed.

## Catalog interpretation

`BLEToyAudioPhrase` has 421 implicit enum members, values 0–420. For example:

| Name | Wire ID | Audio packet |
| --- | --- | --- |
| `eP001` | 0 | `10 00 00` |
| `eP008` | 6 | `10 06 00` |
| `eP798` | 405 | `10 95 01` |
| `eP083` | 420 | `10 a4 01` |

`BLEToyHLSequence` has 454 implicit enum members, values 0–453. For example,
`eHLS_DanceInstruct_1` is 59 (`17 02 3b 00`). These are a different namespace
from audio IDs, even where numeric values coincide. Duration estimates come
from `BLEToyAudio.TimeForPhrase` and `BLEToyHLSequences.TimeForSequence`.

Phrase transcripts, physical safety of individual sequences, hardware revision
compatibility and full lesson composition have not been recovered or verified.
The catalogs identify recorded assets; they do not describe arbitrary speech.

Bleak interface references: [client](https://bleak.readthedocs.io/en/stable/api/client.html)
and [scanner](https://bleak.readthedocs.io/en/stable/api/scanner.html).
