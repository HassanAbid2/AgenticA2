# ADR 0001: Every capability is an MCP tool, behind one marketplace port

Status: accepted

**Context.** Agents must never call GigSim, Upwork, the database or files directly, and live Upwork must
be usable through the same code as the simulator.

**Decision.** Three GigBid MCP servers (portfolio, marketplace, workspace) plus the official Upwork and
GitHub servers. The graph holds a single `MarketplacePort`; the Marketplace MCP server picks the adapter
from config. Agents get tools by name from the `agents:` allowlists in config.

**Consequences.** One extra hop per call. Idempotency, dry-run, rate limiting and the audit log live in one
place. The server can be killed in the viva and the UI shows degraded mode, because the client maps
transport failures to `MarketplaceUnavailable` and the API health check reports it.
