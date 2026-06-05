# Contributing to Ph3b3

Ph3b3 is a personal project in active development. It is built around specific hardware (Nyx, an RTX 4060 machine) and a specific physical robot (Stack-chan on M5Stack CoreS3). Contributions are welcome, but please read this first.

---

## Reporting Bugs

Open an issue and include:

- What you were doing when it broke
- The exact error message or unexpected behaviour
- Your OS, GPU, Python version, and Ollama version
- Whether this is reproducible or happened once

If the bug involves a specific module (Spotify, vision, weather, etc.), say which one.

---

## Suggesting Features

Open an issue with the label `suggestion`. Describe:

- What you want Ph3b3 to do
- Why it fits the project (local, private, personal AI companion)
- Whether you are willing to implement it yourself

Features that require cloud services, external APIs with keys baked in, or that compromise the local-only design will probably not be accepted.

---

## Pull Requests

1. Fork the repo and create a branch from `fresh`.
2. Keep changes focused — one thing per PR.
3. If you are adding a new module, follow the pattern in `modules/` — class-based, no global side effects at import time.
4. Test it on real hardware if you have it. If you do not, say so clearly in the PR.
5. Do not commit `.env`, `*.onnx`, `ph3b3_data/`, or any credentials.
6. Open the PR against the `fresh` branch with a clear description of what changed and why.

---

## What This Project Is Not

Ph3b3 is not a general-purpose AI assistant framework. It is one specific machine, one specific robot, one specific person's setup. PRs that generalise away from that (e.g. "made it work with any model provider") will be evaluated carefully — they are not automatically welcome.

If you want to build your own version, the code is MIT licensed. Fork it and make it yours.
