# .sub Capture Walkthrough Examples (stub)

This is a stub. Expand with 3-5 annotated examples of unknown Sub-GHz captures and the walkthrough produced for each.

Template:

```
## Example 1: <filename>.sub

### Input (raw)
<full .sub contents>

### Parsed header
<Frequency, Preset, Protocol, Bit, Key/RAW_Data summary>

### What will transmit
<modulation, duration, repetition>

### Likely device family
<based on protocol + frequency — garage opener, RKE, TPMS, weather station, etc.>

### Replay-ability
<fixed-code = infinite; rolling = one-shot then desync>

### Legal context
<ISM-band note; transmission of someone else's signal caveat>

### Description
<structured description per methodology.md Phase 6>
```

Candidate captures to include when expanding:

- A plain Princeton 12-bit garage opener.
- A CAME ATOMO rolling capture, to explain the rolling-code failure mode.
- A KeeLoq capture, with bit-layout breakdown.
- A TPMS beacon, to show receive-only protocols.
- A raw-only capture that didn't decode, to walk through RAW_Data interpretation.

Reading a capture is passive — analysis does not need to transmit. The walkthrough explains what transmission would do without performing it.
