"use client";

import { useState } from "react";

import { useDeleteVariable, usePutVariable, useVariables } from "@/lib/queries";

const MASK = "••••••••••••";

/**
 * Variable values are write-only. The control plane stores `value_encrypted`
 * and the API never returns it (PRD → Data Model note; Phase 1 step 4), so
 * there is nothing to reveal — the mask is not a toggle, it is the truth.
 */
export function Variables({ serviceId }: { serviceId: string }) {
  const variables = useVariables(serviceId);
  const putVariable = usePutVariable(serviceId);
  const deleteVariable = useDeleteVariable(serviceId);

  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState("");
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  function submitEdit(key: string) {
    if (draftValue.length === 0) return;
    putVariable.mutate({ key, value: draftValue });
    setEditingKey(null);
    setDraftValue("");
  }

  function submitNew() {
    if (newKey.trim().length === 0 || newValue.length === 0) return;
    putVariable.mutate({ key: newKey.trim(), value: newValue });
    setNewKey("");
    setNewValue("");
  }

  return (
    <div className="rd-scroll min-h-0 flex-1 overflow-auto">
      <table className="w-full border-collapse">
        <tbody>
          {(variables.data ?? []).map((variable) => (
            <tr key={variable.id} className="border-b border-hairline-faint align-middle">
              <td className="w-[45%] px-lg py-sm">
                <span className="block truncate font-mono text-micro text-ink">
                  {variable.key}
                </span>
                {variable.is_reference ? (
                  <span className="text-micro text-ink-faint">reference</span>
                ) : null}
              </td>
              <td className="px-sm py-sm">
                {editingKey === variable.key ? (
                  <input
                    autoFocus
                    type="password"
                    value={draftValue}
                    onChange={(event) => setDraftValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") submitEdit(variable.key);
                      if (event.key === "Escape") setEditingKey(null);
                    }}
                    placeholder="new value"
                    className="w-full rounded-sm border border-hairline-strong bg-surface-inset px-sm py-xs font-mono text-micro text-ink placeholder:text-ink-faint"
                  />
                ) : (
                  <span className="font-mono text-micro text-ink-faint">{MASK}</span>
                )}
              </td>
              <td className="px-lg py-sm text-right">
                {editingKey === variable.key ? (
                  <button
                    type="button"
                    onClick={() => submitEdit(variable.key)}
                    className="rounded-sm border border-hairline-strong px-sm py-xs text-micro text-ink hover:border-ink-faint"
                  >
                    save
                  </button>
                ) : (
                  <span className="flex justify-end gap-sm">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingKey(variable.key);
                        setDraftValue("");
                      }}
                      className="text-micro text-ink-mute hover:text-ink"
                    >
                      edit
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteVariable.mutate(variable.key)}
                      className="text-micro text-ink-faint hover:text-status-failed"
                    >
                      remove
                    </button>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {variables.isSuccess && (variables.data ?? []).length === 0 ? (
        <p className="px-lg py-md text-micro text-ink-faint">no variables set</p>
      ) : null}

      <div className="flex items-center gap-sm px-lg py-md">
        <input
          value={newKey}
          onChange={(event) => setNewKey(event.target.value)}
          placeholder="KEY"
          className="w-[45%] rounded-sm border border-hairline bg-surface-inset px-sm py-xs font-mono text-micro text-ink placeholder:text-ink-faint"
        />
        <input
          type="password"
          value={newValue}
          onChange={(event) => setNewValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submitNew();
          }}
          placeholder="value"
          className="flex-1 rounded-sm border border-hairline bg-surface-inset px-sm py-xs font-mono text-micro text-ink placeholder:text-ink-faint"
        />
        <button
          type="button"
          onClick={submitNew}
          className="rounded-sm border border-hairline-strong px-sm py-xs text-micro text-ink hover:border-ink-faint"
        >
          add
        </button>
      </div>

      <p className="px-lg pb-lg text-micro text-ink-faint">
        Values are encrypted at rest and never returned by the API. Setting a value
        takes effect on the next deploy.
      </p>
    </div>
  );
}
