"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { supabaseBrowser } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const supabase = supabaseBrowser();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setError(error.message);
    else router.push("/dashboard");
  }

  async function magicLink() {
    if (!email) return setError("Enter your email first.");
    setBusy(true);
    setError(null);
    const supabase = supabaseBrowser();
    const { error } = await supabase.auth.signInWithOtp({ email });
    setBusy(false);
    if (error) setError(error.message);
    else setNotice("Magic link sent — check your email.");
  }

  async function forgotPassword() {
    if (!email) return setError("Enter your email first, then tap Forgot password.");
    setBusy(true);
    setError(null);
    const supabase = supabaseBrowser();
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });
    setBusy(false);
    if (error) setError(error.message);
    else setNotice("Password reset link sent — check your email.");
  }

  return (
    <div className="mx-auto mt-20 max-w-sm fade-in">
      <h1 className="page-title text-center">CV Tailor</h1>
      <p className="mt-2 text-center text-[15px] text-subtle">
        Sign in to tailor your next application.
      </p>

      <form onSubmit={signIn} className="mt-10 space-y-3">
        <input
          className="field"
          type="email"
          placeholder="Email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          className="field"
          type="password"
          placeholder="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="mt-5 flex items-center justify-center gap-5 text-[14px]">
        <button className="text-accent hover:underline" onClick={forgotPassword} disabled={busy}>
          Forgot password?
        </button>
        <span className="text-hairline">·</span>
        <button className="text-accent hover:underline" onClick={magicLink} disabled={busy}>
          Email me a magic link
        </button>
      </div>

      <div className="divider mt-8" />
      <p className="mt-6 text-center text-[14px] text-subtle">
        New here?{" "}
        <Link href="/signup" className="text-accent hover:underline">
          Create an account
        </Link>
      </p>

      {notice && <p className="mt-5 text-center text-[14px] text-good">{notice}</p>}
      {error && <p className="mt-5 text-center text-[14px] text-bad">{error}</p>}
    </div>
  );
}
