import { describe, expect, it } from "vitest";
import { canChangeRole, canRemove, invitationEmail, parseInvite, type UserRow } from "@/lib/users";

const u = (id: string, role: "admin" | "member", active = true): UserRow => ({ id, email: `${id}@x.com`, role, active });

describe("canChangeRole", () => {
  it("blocks demoting the last active admin", () => {
    const users = [u("a", "admin"), u("m", "member")];
    expect(canChangeRole(users, "a", "member")).toEqual({ ok: false, error: "Cannot demote the last admin" });
  });
  it("allows demoting when another active admin exists, but not counting a removed one", () => {
    expect(canChangeRole([u("a", "admin"), u("b", "admin")], "a", "member").ok).toBe(true);
    expect(canChangeRole([u("a", "admin"), u("b", "admin", false)], "a", "member").ok).toBe(false);
  });
  it("allows promoting, no-ops, and rejects unknown or removed users", () => {
    const users = [u("a", "admin"), u("m", "member"), u("gone", "member", false)];
    expect(canChangeRole(users, "m", "admin").ok).toBe(true);
    expect(canChangeRole(users, "m", "member").ok).toBe(true);
    expect(canChangeRole(users, "zzz", "admin").ok).toBe(false);
    expect(canChangeRole(users, "gone", "admin").ok).toBe(false);
  });
});

describe("canRemove", () => {
  it("never lets you remove yourself", () => {
    expect(canRemove([u("a", "admin"), u("b", "admin")], "a", "a")).toEqual({ ok: false, error: "You cannot remove yourself" });
  });
  it("blocks removing the last active admin", () => {
    expect(canRemove([u("a", "admin"), u("m", "member")], "a", "m")).toEqual({ ok: false, error: "Cannot remove the last admin" });
  });
  it("allows removing a member or a non-last admin", () => {
    expect(canRemove([u("a", "admin"), u("m", "member")], "m", "a").ok).toBe(true);
    expect(canRemove([u("a", "admin"), u("b", "admin")], "b", "a").ok).toBe(true);
  });
});

describe("parseInvite", () => {
  it("normalizes the email and validates the role", () => {
    expect(parseInvite("  New.User@Example.COM ", "member")).toEqual({ ok: true, email: "new.user@example.com", role: "member" });
    expect(parseInvite("not-an-email", "member").ok).toBe(false);
    expect(parseInvite("a@b.co", "root").ok).toBe(false);
  });
});

describe("invitationEmail", () => {
  it("links to the login page and escapes the inviter", () => {
    const m = invitationEmail({ loginUrl: "https://pippo.example/login", role: "admin", invitedBy: "<b>x</b>@y.com" });
    expect(m.subject).toBe("[Pippo] You have been invited to Pippo");
    expect(m.text).toContain("https://pippo.example/login");
    expect(m.html).not.toContain("<b>x</b>");
    expect(m.html).toContain("&lt;b&gt;");
  });
});
