# DuckyScript Walkthrough Examples (stub)

This is a stub. Expand with 3-5 annotated examples of unknown payloads and the walkthrough produced for each.

Template:

```
## Example 1: <payload filename>

### Input (raw)
<full DuckyScript contents>

### Walkthrough
<line-by-line annotation per `methodology.md` Phase 3>

### Decoded obfuscation
<any base64 / concat / char-code decoded per Phase 4>

### Description
<the structured description from Phase 5>
```

Candidate payloads to include when expanding:

- A benign hello-world, to show the walkthrough format on a trivial case.
- A typical `powershell -w hidden -EncodedCommand` downloader.
- A Mimikatz-invoker (credential-adjacent; tag CRED).
- A Defender-exclusion-adder (tag DEFEND).
- A Run-key persistence installer (tag PERSIST).

Keep the tone analytical throughout — the user gets the full explanation, including decoded obfuscation, and decides themselves.
