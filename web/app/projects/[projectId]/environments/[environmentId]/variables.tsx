"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
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
                  <Input
                    autoFocus
                    type="password"
                    value={draftValue}
                    onChange={(event) => setDraftValue(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") submitEdit(variable.key);
                      if (event.key === "Escape") setEditingKey(null);
                    }}
                    placeholder="new value"
                    className="h-auto"
                  />
                ) : (
                  <span className="font-mono text-micro text-ink-faint">{MASK}</span>
                )}
              </td>
              <td className="px-lg py-sm text-right">
                {editingKey === variable.key ? (
                  <Button
                    onClick={() => submitEdit(variable.key)}
                    variant="outline"
                    size="sm"
                  >
                    save
                  </Button>
                ) : (
                  <span className="flex justify-end gap-sm">
                    <Button
                      onClick={() => {
                        setEditingKey(variable.key);
                        setDraftValue("");
                      }}
                      variant="ghost"
                      size="sm"
                    >
                      edit
                    </Button>
                    <Button
                      onClick={() => deleteVariable.mutate(variable.key)}
                      variant="ghost"
                      size="sm"
                      className="hover:text-status-failed"
                    >
                      remove
                    </Button>
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

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-sm px-lg py-md">
        <Input
          value={newKey}
          onChange={(event) => setNewKey(event.target.value)}
          placeholder="KEY"
          className="w-full border-hairline"
        />
        <Input
          type="password"
          value={newValue}
          onChange={(event) => setNewValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submitNew();
          }}
          placeholder="value"
          className="w-full border-hairline"
        />
        <Button
          onClick={submitNew}
          variant="outline"
          size="sm"
        >
          Add
        </Button>
      </div>

      <p className="px-lg pb-lg text-micro text-ink-faint">
        Values are encrypted at rest and never returned by the API. Setting a value
        takes effect on the next deploy.
      </p>
    </div>
  );
}
