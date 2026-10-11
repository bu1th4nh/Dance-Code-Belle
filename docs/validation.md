# Validation and next milestone

## Offline verification

- 21 unit tests pass on Python 3.12 in the development environment.
- Tests cover golden packet examples, catalog bounds and namespace mixing,
  notification decoding, timeout without retransmission, completion arriving
  during a write, malformed messages, bounded event storage, movement opt-in,
  keep-alive failures, stop cancellation and disconnect after cleanup failure.
- A fake Bleak client checks characteristic selection, notification callback
  conversion, writes without response and rejection of unrelated devices.
- All 421 audio and 454 high-level catalog entries were compared against source
  enum order and duration tables during development.
- Packaging and installed command examples are checked locally. The GitHub Actions
  workflow checks Python 3.10–3.14; see the repository's Actions tab for each run.

## First hardware milestone

1. Recover the exact ID and any preparation/connection packets from the owner's
   known-working C# speech controller. The provided archive alone does not show
   which phrase the owner previously used successfully.
2. Scan for `DanceCD`; connect and check the discovered endpoints. Resolve any
   necklace pairing requirement before playback. Do not guess a password.
3. Preview the known phrase and compare bytes against the C# controller.
4. Send that single phrase once. Record its completion notification and confirm
   that stop, mode exit and disconnect work. Keep the physical power switch
   accessible; a software stop cannot be relied on after a lost connection.
5. If there is no completion or an unexpected behavior, stop testing and inspect
   the packet transcript. Do not loop playback to try to fix the problem.

Only after this milestone should dance instruction fragments be tried. Complete
necklace dance-lesson triggering remains a separate research question. No
physical commands were transmitted during construction of this library.
