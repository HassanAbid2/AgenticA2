"""Pricing Strategist: market statistics + client budget + the user's floor -> PriceQuote, and whether the
Connects cost is worth it (expected reply rate per Connect)."""

from __future__ import annotations

from agent.handoffs import PriceQuote
from agent.nodes.common import deps, node, thresholds


def expected_reply_rate(fit: float, risk: float, proposals_count: int) -> float:
    competition = 1 / (1 + proposals_count / 15)
    return round(max(0.01, min(0.6, 0.45 * fit * (1 - risk) * (0.5 + competition))), 4)


def quote(job: dict, stats: dict | None, profile: dict, fit: float, risk: float, connects_cost: int) -> PriceQuote:
    b = job.get("budget") or {}
    unit = b.get("type", "fixed")
    why = []
    floor_applied = False
    if unit == "hourly":
        hr = (stats or {}).get("hourly_rate") or {}
        lo, mid, hi = hr.get("p25") or profile["hourly_rate"] * 0.8, hr.get("median") or profile["hourly_rate"], hr.get("p75") or profile["hourly_rate"] * 1.2
        amount = min(max(profile["hourly_rate"], lo), hi)
        why.append(f"market hourly p25/median/p75 ${lo:.0f}/${mid:.0f}/${hi:.0f}; your rate ${profile['hourly_rate']}")
        if b.get("max"):
            amount = min(amount, b["max"] * 1.05)
            why.append(f"kept within client's max ${b['max']}/h (+5%)")
        if amount < profile["floor_hourly"]:
            amount, floor_applied = profile["floor_hourly"], True
            why.append(f"raised to your floor ${profile['floor_hourly']}/h")
    else:
        fp = (stats or {}).get("fixed_price") or {}
        lo, mid, hi = fp.get("p25"), fp.get("median"), fp.get("p75")
        if mid is None:  # no market data (e.g. live mode): centre of client budget
            mid = ((b.get("min") or 0) + (b.get("max") or 0)) / 2 or profile["min_fixed"]
            lo, hi = mid * 0.8, mid * 1.2
            why.append("no market statistics; centred on the client's budget")
        else:
            why.append(f"similar jobs closed at p25/median/p75 ${lo:,.0f}/${mid:,.0f}/${hi:,.0f}")
        amount = mid * (0.95 + 0.1 * fit)  # stronger evidence -> price nearer the upper middle
        if b.get("max"):
            if amount > b["max"]:
                why.append(f"capped near client's max ${b['max']:,.0f}")
            amount = min(amount, b["max"])
        if b.get("min"):
            amount = max(amount, b["min"])
        if amount < profile["min_fixed"]:
            amount, floor_applied = profile["min_fixed"], True
            why.append(f"raised to your minimum ${profile['min_fixed']}")
    p = expected_reply_rate(fit, risk, job.get("proposals_count", 0))
    worth = (p / max(1, connects_cost)) >= thresholds()["connects_value_min"]
    why.append(f"{connects_cost} Connects for ~{p:.0%} expected reply chance: {'worth it' if worth else 'poor value'}")
    return PriceQuote(amount=round(amount, 2 if unit == "hourly" else -1) or round(amount, 2), unit=unit,
                      band_low=round(lo, 2), band_high=round(hi, 2), connects_cost=connects_cost, connects_worth_it=worth,
                      expected_reply_rate=p, floor_applied=floor_applied, rationale=why)


@node("pricing")
async def pricing(state, config):
    d = deps(config)
    m = d.market("pricing")
    job = state["job"]
    spec = state.get("job_spec", {})
    try:
        stats = await m.get_market_stats(job.get("category", ""), max(1, min(20, len(spec.get("required_skills", [])) or 3)))
    except Exception:  # noqa: BLE001 - live mode has no market stats; quote() falls back to the budget
        stats = None
    q = quote(job, stats, d.profile | d.user_settings, state.get("fit_report", {}).get("score", 0.5),
              state.get("risk_report", {}).get("score", 0.0), int(job.get("connects_cost") or 0))
    out = {"price": q.model_dump(), "_summary": {"amount": q.amount, "unit": q.unit, "connects_worth_it": q.connects_worth_it}}
    budget = d.setting("weekly_connects_budget")
    if budget is not None:
        spent = d.setting("connects_spent_this_week", 0)
        if spent + q.connects_cost > budget:
            out["price"]["rationale"].append(f"WARNING: exceeds weekly Connects budget ({spent}+{q.connects_cost} > {budget})")
    return out
