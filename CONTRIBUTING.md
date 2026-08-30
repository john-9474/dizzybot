# Contributing

Thanks for contributing to DizzyBot.

1. Open an issue before undertaking a large behavioral or public-contract change.
2. Create a focused branch and preserve the separation between contracts, domain types, defaults,
   and the composition root.
3. Add tests for behavior changes. External provider calls must be optional; required CI must remain
   deterministic.
4. Run the development checks documented in the README.
5. Update configuration and operator documentation when behavior or deployment changes.

New behavior should normally be introduced as a base contract plus a default subclass. Avoid runtime
plugin discovery, media downloading, credential logging, or dependencies on privileged Discord
intents.

By contributing, you agree that your contribution is licensed under GPL-3.0-only.
