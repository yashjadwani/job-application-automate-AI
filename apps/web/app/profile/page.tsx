"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";

export default function ProfilePage() {
  const [form, setForm] = useState({
    name: "", email: "", linkedin_url: "", bio: "", additional_context: "",
  });
  const [skills, setSkills] = useState<string[]>([]);
  const [skillInput, setSkillInput] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ profile: any }>("/profile")
      .then(({ profile }) => {
        if (profile) {
          setForm({
            name: profile.name ?? "",
            email: profile.email ?? "",
            linkedin_url: profile.linkedin_url ?? "",
            bio: profile.bio ?? "",
            additional_context: profile.additional_context ?? "",
          });
          setSkills(profile.skills ?? []);
        }
      })
      .catch((e) => setError(e.message));
  }, []);

  async function save() {
    setError(null);
    try {
      await api("/profile", {
        method: "POST",
        body: JSON.stringify({ ...form, skills }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e.message);
    }
  }

  function addSkill() {
    const s = skillInput.trim();
    if (s && !skills.includes(s)) setSkills([...skills, s]);
    setSkillInput("");
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<any>) =>
    setForm({ ...form, [k]: e.target.value });

  return (
    <div className="max-w-xl">
      <PageHeader
        title="Profile"
        subtitle="This context guides every analysis and rewrite."
      />

      <div className="mt-10 space-y-4">
        <input className="field" placeholder="Name" value={form.name} onChange={set("name")} />
        <input className="field" placeholder="Email" value={form.email} onChange={set("email")} />
        <input className="field" placeholder="LinkedIn URL" value={form.linkedin_url} onChange={set("linkedin_url")} />
        <textarea className="field min-h-32" placeholder="Professional summary"
          value={form.bio} onChange={set("bio")} />
        <textarea className="field min-h-24"
          placeholder="Anything else the AI should know (role level, location preferences…)"
          value={form.additional_context} onChange={set("additional_context")} />

        <div>
          <div className="flex gap-2">
            <input className="field" placeholder="Add a skill, press Enter"
              value={skillInput}
              onChange={(e) => setSkillInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addSkill())} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {skills.map((s) => (
              <button key={s}
                className="rounded-full bg-canvas px-3.5 py-1.5 text-[13px] hover:bg-hairline transition-colors"
                onClick={() => setSkills(skills.filter((x) => x !== s))}
                title="Remove">
                {s} ×
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4 pt-2">
          <button className="btn-primary" onClick={save}>Save</button>
          {saved && <span className="text-[14px] text-good">Saved</span>}
          {error && <span className="text-[14px] text-bad">{error}</span>}
        </div>
      </div>

      <TelegramConnect />
    </div>
  );
}

function TelegramConnect() {
  const [link, setLink] = useState<{ code: string; bot_username: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      setLink(await api("/telegram/link-code", { method: "POST" }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-16">
      <h2 className="section-title">Telegram</h2>
      <div className="divider mt-3" />
      <p className="mt-4 text-[15px] text-subtle">
        Link Telegram to get a ping when analyses finish — or send a job
        description straight to the bot and receive your tailored CV in chat.
      </p>
      {!link ? (
        <button className="btn-secondary mt-4" onClick={connect} disabled={busy}>
          {busy ? "Generating…" : "Connect Telegram"}
        </button>
      ) : (
        <div className="mt-4 text-[15px] leading-relaxed">
          {link.bot_username ? (
            <>
              Open{" "}
              <a className="text-accent hover:underline"
                 href={`https://t.me/${link.bot_username}?start=${link.code}`}
                 target="_blank" rel="noreferrer">
                @{link.bot_username}
              </a>{" "}
              and press <em>Start</em> — or send it:
            </>
          ) : (
            "Send this to your bot:"
          )}
          <code className="ml-2 rounded-lg bg-canvas px-3 py-1.5 font-mono text-[14px]">
            /start {link.code}
          </code>
        </div>
      )}
      {error && <p className="mt-3 text-[14px] text-bad">{error}</p>}
    </section>
  );
}
