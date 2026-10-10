import { describe, expect, it } from "vitest";
import { buildReport, rankIssues, type Issue, type ReportInput } from "@/lib/report";

const issue = (severity: "critical" | "warning", scope: string, checkId = "img.broken_ratio"): Issue => ({
  severity,
  scope,
  checkId,
  value: 0.06,
  threshold: 0.05,
});

const base: ReportInput = {
  countryCode: "IT",
  countryName: "Italy",
  startedAt: new Date("2026-10-09T04:00:00Z"),
  finishedAt: new Date("2026-10-09T05:10:00Z"),
  counts: { ok: 120, warning: 5, critical: 2, error: 0 },
  images: [{ page: "home", total: 100, broken: 6, placeholder: 0 }],
  issues: [issue("warning", "Zeta"), issue("critical", "home"), issue("warning", "Alpha"), issue("critical", "Beta")],
  becameCritical: ["Beta"],
  recovered: ["Gamma"],
  dashboardUrl: "https://pippo.example/runs/abc",
};

describe("daily report", () => {
  it("builds the subject from failed checks", () => {
    expect(buildReport(base).subject).toBe("[Pippo] IT — Daily report 2026-10-09 — 2 critical, 2 warnings");
  });

  it("ranks critical first, then by scope", () => {
    expect(rankIssues(base.issues).map((i) => `${i.severity}:${i.scope}`)).toEqual([
      "critical:Beta",
      "critical:home",
      "warning:Alpha",
      "warning:Zeta",
    ]);
  });

  it("limits to the top 10 issues and says how many exist", () => {
    const many = Array.from({ length: 25 }, (_, i) => issue("warning", `Channel ${String(i).padStart(2, "0")}`));
    const { text } = buildReport({ ...base, issues: many });
    expect(text).toContain("Top issues (10 of 25)");
    expect(text).toContain("Channel 09");
    expect(text).not.toContain("Channel 10");
  });

  it("includes counts, images, changes and the dashboard link in both formats", () => {
    const { text, html } = buildReport(base);
    for (const body of [text, html]) {
      expect(body).toContain("Channels (127)");
      expect(body).toContain("home: 100 images, broken 6.0%");
      expect(body).toContain("Became critical: Beta");
      expect(body).toContain("Recovered: Gamma");
      expect(body).toContain("https://pippo.example/runs/abc");
    }
  });

  it("escapes HTML in channel names and handles an empty run", () => {
    const { html, text } = buildReport({ ...base, issues: [issue("critical", "<script>x</script>")], images: [], becameCritical: [], recovered: [] });
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(text).toContain("no images result for this run");
    expect(text).toContain("Became critical: none");
  });
});
