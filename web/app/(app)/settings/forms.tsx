"use client";

import { useActionState } from "react";
import type { FormState } from "./actions";

function Message({ state }: { state: FormState }) {
  if (!state) return null;
  return (
    <p role={state.ok ? "status" : "alert"} className={`text-sm ${state.ok ? "text-green-800" : "text-red-700"}`}>
      {state.message}
    </p>
  );
}

type Action = (prev: FormState, formData: FormData) => Promise<FormState>;

export function ThresholdRow(props: {
  checkId: string;
  name: string;
  description: string;
  unitLabel: string;
  warn: string;
  critical: string;
  isDefault: boolean;
  defaultText: string;
  save: Action;
  reset: Action;
}) {
  const [saved, saveAction, savePending] = useActionState(props.save, null);
  const [resetState, resetAction, resetPending] = useActionState(props.reset, null);
  const inputClass = "w-24 rounded border border-neutral-300 px-2 py-1";
  return (
    <tr className="border-b border-neutral-100 align-top">
      <td className="py-3 pr-4">
        <div className="font-medium">{props.name}</div>
        <div className="text-xs text-neutral-600">{props.description}</div>
        <div className="text-xs text-neutral-500">
          <code>{props.checkId}</code> · default {props.defaultText}
        </div>
      </td>
      <td className="py-3" colSpan={2}>
        <form action={saveAction} className="flex flex-wrap items-end gap-3">
          <input type="hidden" name="checkId" value={props.checkId} />
          <label className="text-sm">
            Warning ({props.unitLabel})
            <input name="warn" defaultValue={props.warn} inputMode="decimal" className={`${inputClass} ml-1`} />
          </label>
          <label className="text-sm">
            Critical ({props.unitLabel})
            <input name="critical" defaultValue={props.critical} inputMode="decimal" className={`${inputClass} ml-1`} />
          </label>
          <button disabled={savePending} className="rounded bg-black px-3 py-1 text-sm text-white disabled:opacity-50">
            Save
          </button>
        </form>
        {!props.isDefault && (
          <form action={resetAction} className="mt-1">
            <input type="hidden" name="checkId" value={props.checkId} />
            <button disabled={resetPending} className="text-xs underline">
              Reset to default
            </button>
          </form>
        )}
        <Message state={saved ?? resetState} />
      </td>
    </tr>
  );
}

export function SimpleForm(props: { action: Action; children: React.ReactNode; button: string }) {
  const [state, formAction, pending] = useActionState(props.action, null);
  return (
    <form action={formAction} className="space-y-2">
      {props.children}
      <button disabled={pending} className="rounded bg-black px-3 py-1 text-sm text-white disabled:opacity-50">
        {props.button}
      </button>
      <Message state={state} />
    </form>
  );
}
