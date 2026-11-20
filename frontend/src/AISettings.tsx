import { useEffect, useState } from "react";
export type AIConfig = {
  enabled: boolean;
  consent: boolean;
  provider: string;
  model: string;
  credentials: Record<string, boolean>;
  cost: string;
};
export async function send<T>(
  url: string,
  value?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: value === undefined ? undefined : JSON.stringify(value),
  });
  let data: any;
  try {
    data = await response.json();
  } catch {
    throw Error(
      `Local service returned ${response.status}; your input is preserved`,
    );
  }
  if (!response.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Request could not be validated",
    );
  return data;
}
export function AISettings({
  config: savedConfig,
  onChange,
}: {
  config: AIConfig;
  onChange: (c: AIConfig) => void;
}) {
  const [config, setConfig] = useState(savedConfig);
  useEffect(() => setConfig(savedConfig), [savedConfig]);
  const [secret, setSecret] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const change = (value: Partial<AIConfig>) =>
    setConfig({ ...config, ...value });
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="settings-card ai-settings">
      <h3>Cloud AI · Gemini / OpenAI</h3>
      <p>
        Only your question and selected source excerpts are sent to the chosen
        provider. No full PDFs are uploaded. API usage may incur charges; cost
        and quota are unknown until reported by your provider.
      </p>
      <label>
        Provider
        <select
          aria-label="AI provider"
          value={config.provider}
          onChange={(e) => {
            change({ provider: e.target.value, model: "" });
            setModels([]);
          }}
        >
          <option>Gemini</option>
          <option>OpenAI</option>
        </select>
      </label>
      <p>
        {config.credentials[config.provider]
          ? "A key is saved in Windows Credential Manager."
          : "No saved key for this provider."}
      </p>
      <label>
        API key
        <input
          aria-label="API key"
          type="password"
          autoComplete="off"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          placeholder="Enter once; stored only in Windows Credential Manager"
        />
      </label>
      <div>
        <button
          disabled={busy || !secret}
          onClick={() =>
            action(async () => {
              await send("/api/ai/credentials", {
                provider: config.provider,
                secret,
              });
              setSecret("");
              change({
                credentials: { ...config.credentials, [config.provider]: true },
              });
              setMessage("Credential saved securely.");
            })
          }
        >
          Save / replace key
        </button>
        <button
          disabled={busy || !config.credentials[config.provider]}
          onClick={() =>
            action(async () => {
              await send(
                "/api/ai/credentials/" + config.provider,
                undefined,
                "DELETE",
              );
              change({
                credentials: {
                  ...config.credentials,
                  [config.provider]: false,
                },
              });
            })
          }
        >
          Forget key
        </button>
      </div>
      <button
        disabled={busy || !config.credentials[config.provider]}
        onClick={() =>
          action(async () => {
            const response = await fetch(
              "/api/ai/models?provider=" + config.provider,
            );
            const data = await response.json();
            if (!response.ok) throw Error(data.detail);
            setModels(data);
          })
        }
      >
        Load available provider models
      </button>
      <label>
        Model
        <select
          aria-label="AI model"
          value={config.model}
          onChange={(e) => change({ model: e.target.value })}
        >
          <option value="">Select a discovered model</option>
          {config.model && !models.includes(config.model) && (
            <option>{config.model}</option>
          )}
          {models.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
      </label>
      <label>
        <input
          aria-label="Cloud consent"
          type="checkbox"
          checked={config.consent}
          onChange={(e) =>
            change({
              consent: e.target.checked,
              enabled: e.target.checked ? config.enabled : false,
            })
          }
        />{" "}
        I authorise sending selected research excerpts and questions to this
        provider and accept possible API charges.
      </label>
      <button
        className="primary"
        disabled={busy}
        onClick={() =>
          action(async () => {
            const saved = await send<AIConfig>(
              "/api/ai/settings",
              config,
              "PUT",
            );
            onChange(saved);
            setMessage(
              "Preferences saved. Use AI On in the composer when ready.",
            );
          })
        }
      >
        Save AI preferences
      </button>
      {message && <p role="status">{message}</p>}
    </div>
  );
}
export function OrganisationHistory() {
  const [rows, setRows] = useState<
    {
      id: number;
      document_id?: number;
      state: string;
      created: string;
      old_name?: string;
      new_name?: string;
    }[]
  >([]);
  const [error, setError] = useState("");
  const refresh = () =>
    fetch("/api/library/organisation")
      .then((r) => r.json())
      .then(setRows);
  useEffect(() => {
    void refresh();
  }, []);
  return (
    <div className="settings-card ai-settings">
      <h3>Reversible library organisation</h3>
      <button
        onClick={async () => {
          try {
            const result = await send<{
              restored_moves: number;
              blocked_operations: number[];
            }>("/api/library/organisation/restore-all");
            setError(
              `Restored ${result.restored_moves} moves; ${result.blocked_operations.length} operations require attention.`,
            );
            void refresh();
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      >
        Restore original file locations
      </button>
      <p>
        Every move is integrity checked. Undo restores the original location and
        pauses organisation for that content.
      </p>
      {error && <p role="alert">{error}</p>}
      {rows.slice(0, 40).map((r) => (
        <div key={r.id}>
          {r.old_name || `Operation ${r.id}`} → {r.new_name || "Organised PDF"}{" "}
          · {r.created} · {r.state}{" "}
          <button
            disabled={r.state !== "done"}
            onClick={async () => {
              try {
                await send(`/api/library/organisation/${r.id}/undo`);
                void refresh();
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Undo
          </button>
          {r.state === "undone" && r.document_id && (
            <button
              onClick={async () => {
                try {
                  await send(`/api/documents/${r.document_id}/organise`);
                  void refresh();
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Resume organising
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
