"use client";

import { useState } from "react";
import Link from "next/link";
import { supabaseBrowser } from "@/lib/supabase";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const mismatch = confirm.length > 0 && password !== confirm;
  const tooShort = password.length > 0 && password.length < 8;

  async function signUp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) return setError("Password must be at least 8 characters.");
    if (password !== confirm) return setError("Passwords don't match.");

    setBusy(true);
    const supabase = supabaseBrowser();
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/login` },
    });
    setBusy(false);
    if (error) setError(error.message);
    else setDone(true);
  }

  if (done) {
    return (
      <div className="mx-auto mt-20 max-w-sm text-center fade-in">
        <h1 className="page-title">Check your email</h1>
        <p className="mt-3 text-[15px] text-subtle leading-relaxed">
          We sent a confirmation link to <span className="text-ink">{email}</span>.
          Confirm it, then sign in.
        </p>
        <Link href="/login" className="btn-primary mt-8 inline-block">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto mt-20 max-w-sm fade-in">
      <h1 className="page-title text-center">Create account</h1>
      <p className="mt-2 text-center text-[15px] text-subtle">
        Your CV, tailored to every role.
      </p>

      <form onSubmit={signUp} className="mt-10 space-y-3">
        <input
          className="field"
          type="email"
          placeholder="Email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <div>
          <input
            className="field"
            type="password"
            placeholder="Password (min 8 characters)"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {tooShort && (
            <p className="mt-1.5 px-1 text-[13px] text-warn">At least 8 characters.</p>
          )}
        </div>
        <div>
          <input
            className={`field ${mismatch ? "ring-2 ring-bad/40" : ""}`}
            type="password"
            placeholder="Confirm password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          {mismatch && (
            <p className="mt-1.5 px-1 text-[13px] text-bad">Passwords don't match.</p>
          )}
        </div>
        <button
          className="btn-primary w-full"
          disabled={busy || mismatch || tooShort || !email || !password || !confirm}
        >
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>

      <div className="divider mt-8" />
      <p className="mt-6 text-center text-[14px] text-subtle">
        Already have an account?{" "}
        <Link href="/login" className="text-accent hover:underline">
          Sign in
        </Link>
      </p>

      {error && <p className="mt-5 text-center text-[14px] text-bad">{error}</p>}
    </div>
  );
}
