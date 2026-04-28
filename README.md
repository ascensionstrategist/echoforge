# 3CH0F0RG3

AI-driven Flipper Zero control from Windows desktop, powered by your Claude Max subscription.

Ported from [V3SP3R](https://github.com/elder-plinius/V3SP3R) (GPL-3.0, Android/Kotlin) to Python.

## Status

**Phase 1 — Foundation** (in progress)

- [x] Project scaffold
- [ ] Flipper protobuf bindings
- [ ] USB-CDC serial transport
- [ ] RPC frame codec
- [ ] Ping smoke test

## Requirements

- Windows 10/11
- Python 3.10+
- Flipper Zero (USB-C cable)
- Claude Code CLI installed and logged into a Claude Max/Pro subscription (added in Phase 4)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts/fetch_protos.py
python scripts/build_protos.py
```

## Smoke test (Phase 1)

```bash
python -m echoforge.tools.ping
```

## License

GPL-3.0-or-later (inherits from upstream V3SP3R).
