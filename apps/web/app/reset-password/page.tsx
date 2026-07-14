"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabaseBrowser } from "@/lib/supabase";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mismatch = confirm.length > 0 && password !== confirm;

  async function reset(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) return setError("Password must be at least 8 characters.");
    if (password !== confirm) return setError("Passwords don't match.");

    setBusy(true);
    const supabase = supabaseBrowser();
    const { error } = await supabase.auth.updateUser({ password });
    setBusy(false);
    if (error) {
      setError(
        error.message.includes("session")
          ? "This reset link has expired — request a new one from the sign-in page."
          : error.message
      );
    } else {
      router.push("/dashboard");
    }
  }

  return (
    <div className="mx-auto mt-20 max-w-sm fade-in">
      <h1 className="page-title text-center">Set a new password</h1>
      <p className="mt-2 text-center text-[15px] text-subtle">
        You followed a reset link — choose your new password.
      </p>

      <form onSubmit={reset} className="mt-10 space-y-3">
        <input
          className="field"
          type="password"
          placeholder="New password (min 8 characters)"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <div>
          <input
            className={`field ${mismatch ? "ring-2 ring-bad/40" : ""}`}
            type="password"
            placeholder="Confirm new password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          {mismatch && (
            <p className="mt-1.5 px-1 text-[13px] text-bad">Passwords don't match.</p>
          )}
        </div>
        <button className="btn-primary w-full" disabled={busy || mismatch}>
          {busy ? "Saving…" : "Save new password"}
        </button>
      </form>

      {error && <p className="mt-5 text-center text-[14px] text-bad">{error}</p>}
    </div>
  );
}
