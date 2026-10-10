"use client";

import { useActionState } from "react";
import type { FormState } from "../actions";

type Action = (prev: FormState, formData: FormData) => Promise<FormState>;

function Message({ state }: { state: FormState }) {
  if (!state) return null;
  return (
    <p role={state.ok ? "status" : "alert"} className={`text-xs ${state.ok ? "text-green-800" : "text-red-700"}`}>
      {state.message}
    </p>
  );
}

export function RoleForm({ userId, role, action }: { userId: string; role: "admin" | "member"; action: Action }) {
  const [state, formAction, pending] = useActionState(action, null);
  return (
    <form action={formAction} className="flex items-center gap-2">
      <input type="hidden" name="userId" value={userId} />
      <select name="role" defaultValue={role} aria-label="Role" className="rounded border border-neutral-300 px-2 py-1 text-sm">
        <option value="member">member</option>
        <option value="admin">admin</option>
      </select>
      <button disabled={pending} className="text-sm underline disabled:opacity-50">
        Save
      </button>
      <Message state={state} />
    </form>
  );
}

export function RemoveForm({ userId, email, action }: { userId: string; email: string; action: Action }) {
  const [state, formAction, pending] = useActionState(action, null);
  return (
    <form
      action={formAction}
      onSubmit={(e) => {
        if (!window.confirm(`Remove access for ${email}? They keep their history but can no longer sign in.`)) e.preventDefault();
      }}
    >
      <input type="hidden" name="userId" value={userId} />
      <button disabled={pending} className="text-sm text-red-700 underline disabled:opacity-50">
        Remove
      </button>
      <Message state={state} />
    </form>
  );
}

export function InviteForm({ action }: { action: Action }) {
  const [state, formAction, pending] = useActionState(action, null);
  return (
    <form action={formAction} className="flex flex-wrap items-end gap-3">
      <label className="text-sm">
        Email
        <input
          name="email"
          type="email"
          required
          autoComplete="off"
          className="ml-1 w-64 rounded border border-neutral-300 px-2 py-1"
        />
      </label>
      <label className="text-sm">
        Role
        <select name="role" defaultValue="member" className="ml-1 rounded border border-neutral-300 px-2 py-1">
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
      </label>
      <button disabled={pending} className="rounded bg-black px-3 py-1 text-sm text-white disabled:opacity-50">
        Send invitation
      </button>
      <div className="w-full">
        <Message state={state} />
      </div>
    </form>
  );
}
