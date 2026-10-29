// 29 Oct 2026 audit: a trade could open with stopPx null when the market data had a gap (no ATR yet), and the risk
// layer only fires stops it has. No stop, no trade.
import { describe, expect, it } from "vitest";
import { Alerts } from "../src/alerts.js";
import { Db } from "../src/db.js";
import { Engine } from "../src/engine.js";
import { EventBus } from "../src/events.js";
import { SimExecutor } from "../src/exec/executor.js";
import { Jev, type SystemOne } from "../src/jev.js";
import type { MarketFeed } from "../src/market/data.js";
import { coin, NOW, testConfig, view } from "./fixtures.js";

async function momentumBee(atr14Pct: number | null) {
  const cfg = testConfig({ DRY_RUN: "true" });
  const v = view([coin("ENA", { ret24hPct: 25, ret7dPct: 43, atr14Pct }), coin("SUI", { ret24hPct: 12, ret7dPct: 40, atr14Pct })]);
  const feed = { view: () => v, refresh: async () => {}, refreshTickers: async () => {}, get lastRefreshAt() { return NOW; } } as unknown as MarketFeed;
  const client: SystemOne = {
    async systemOne() {
      return { model: "fake", usage: { input_tokens: 100, output_tokens: 0 }, answers: { action: { type: "choice", choice: "APE_ENA", confidence: 0.9, probabilities: { APE_ENA: 0.9, APE_SUI: 0.1 } }, conviction: { type: "score", score: 3, confidence: 1, legend: {}, probabilities: {} } } } as never;
    },
  };
  const db = new Db(":memory:");
  const sim = new SimExecutor(() => v, cfg.risk.takerFeeRate);
  const sent: string[] = [];
  const exec = Object.assign(Object.create(sim) as SimExecutor, {
    market: (bee: string, req: Parameters<SimExecutor["market"]>[1]) => {
      sent.push(`${bee}:${req.instId}`);
      return sim.market(bee as never, req);
    },
  });
  const events: Array<{ type: string; event?: string }> = [];
  const bus = new EventBus(db);
  bus.subscribe((_line, e) => events.push(e as never));
  const engine = new Engine({ cfg, db, feed, jev: new Jev({ ...cfg.jev, client, now: () => NOW }), exec, bus, alerts: new Alerts(undefined), now: () => NOW });
  await engine.start();
  engine.stop();
  for (const id of ["bee1", "bee2"] as const) engine.bees[id].cap = "trade_cap"; // only the Momentum bee acts
  engine.bees.bee3.flatSince = NOW - 60 * 60_000;
  await engine.tick();
  return { engine, sent, events };
}

describe("an open needs a stop loss", () => {
  it("with ATR data the bee opens and the position carries a stop below the entry", async () => {
    const { engine, sent } = await momentumBee(0.5);
    expect(sent.filter((s) => s.startsWith("bee3"))).toHaveLength(1);
    const p = engine.bees.bee3.position!;
    expect(p.stopPx).not.toBeNull();
    expect(p.stopPx!).toBeLessThan(p.entryPx);
  });

  it("with a gap in the data (no ATR) no order is sent and the bee stays flat", async () => {
    const { engine, sent, events } = await momentumBee(null);
    expect(sent.filter((s) => s.startsWith("bee3"))).toHaveLength(0);
    expect(engine.bees.bee3.position).toBeNull();
    expect(events.some((e) => e.event === "open_skipped_no_stop")).toBe(true);
  });
});
