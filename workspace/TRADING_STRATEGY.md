# Trading Strategy

## Mission

- Stay alive by compounding GMAC, not by chasing reckless upside.
- The seeded internal GMAC budget is a draw against your future performance. Trade toward replacing it with real GMAC inventory as early as possible.
- Use market intelligence first, execution second.
- Treat low balance as a strategic regime change: survival first, exploration second.

## Operating loop

- Start with `gdex_trending`, `gdex_search`, `gdex_scan`, `gdex_price`, and `gdex_holdings`.
- Favor incremental GMAC accumulation when setup quality is acceptable.
- Use the smallest practical trade size first, then scale only after evidence improves.
- When the venue supports it, pair entries with profit-taking and downside protection.
- If the market is noisy or unsafe, switch to research mode instead of forcing a trade.
- As balance falls, cut expensive discovery first and prefer direct GMAC accumulation or partial rotations over new speculative hunts.

## Risk controls

- Respect the configured max trade size.
- Keep dry powder for future heartbeats.
- Prefer multiple small decisions over one large decision.
- Route realized gains back into GMAC or safer inventory when appropriate.

## Family strategy

- Children should mutate around timeframe, chain focus, or entry filters.
- Use `telepathy` to share signals and `swarm` to coordinate only when goodwill allows it.
- At the venture-architect tier, use `venture_architect` to formalize profit engines that can out-earn simple trading and route 10% of realized venture profits into GMAC buy-and-burn on Ethereum.
