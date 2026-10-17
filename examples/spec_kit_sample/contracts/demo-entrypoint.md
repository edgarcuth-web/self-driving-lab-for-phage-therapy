# Contract: One-Command Demo Entrypoint

**Status**: FROZEN — only the integrator may change this file.

## Signature

```bash
python -m phage_lab demo --host "Escherichia coli" --port 8080
```

## Hard requirements

- **Zero network, zero environment variables, zero API keys.**
- Uses the committed fixture under `examples/fixtures/`.
- Uses `--agent rule` (never OpenRouter).
- Runs both rounds automatically and prints the dashboard URL.
- On failure: exits non-zero and prints a **readable Chinese reason**, not a stack trace.
- After a successful start, the dashboard is reachable and its first frame is a complete snapshot.
