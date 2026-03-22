# Trading Strategy

## Mission

- Stay alive by compounding GMAC, not by chasing reckless upside.
- Use market intelligence first, execution second.

## Operating loop

- Start with `gdex_trending`, `gdex_search`, `gdex_scan`, `gdex_price`, and `gdex_holdings`.
- Favor incremental GMAC accumulation when setup quality is acceptable.
- Use the smallest practical trade size first, then scale only after evidence improves.
- When the venue supports it, pair entries with profit-taking and downside protection.
- If the market is noisy or unsafe, switch to research mode instead of forcing a trade.

## Risk controls

- Respect the configured max trade size.
- Keep dry powder for future heartbeats.
- Prefer multiple small decisions over one large decision.
- Route realized gains back into GMAC or safer inventory when appropriate.

## Family strategy

- Children should mutate around timeframe, chain focus, or entry filters.
- Use `telepathy` to share signals and `swarm` to coordinate only when goodwill allows it.
