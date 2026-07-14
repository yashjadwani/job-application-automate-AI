"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";

type Section = { id: string; title: string; bullets: { index: number; text: string }[] };

export default function CvPage() {
  const [sections, setSections] = useState<Section[] | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api<{ cv: { sections: Section[] } | null }>("/profile")
      .then(({ cv }) => setSections(cv?.sections ?? []))
      .catch((e) => setError(e.message));
  }, []);

  async function upload(file: File) {
    setStatus("Parsing…");
    setError(null);
    const body = new FormData();
    body.append("file", file);
    try {
      const cv = await api<{ sections: Section[] }>("/cv/upload", { method: "POST", body });
      setSections(cv.sections);
      setStatus(null);
    } catch (e: any) {
      setError(e.message);
      setStatus(null);
    }
  }

  async function saveBullet(secIdx: number, bulIdx: number, text: string) {
    if (!sections) return;
    const next = structuredClone(sections);
    next[secIdx].bullets[bulIdx].text = text;
    setSections(next);
    try {
      await api("/cv/sections", { method: "PUT", body: JSON.stringify(next) });
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div>
      <PageHeader
        title="Your CV"
        subtitle="Upload a .docx — its exact formatting is preserved in every export."
        action={
          <button className="btn-primary" onClick={() => fileRef.current?.click()}>
            {sections?.length ? "Replace CV" : "Upload CV"}
          </button>
        }
      />
      <input ref={fileRef} type="file" accept=".docx" className="hidden"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />

      {status && <p className="mt-6 text-[14px] text-subtle">{status}</p>}
      {error && <p className="mt-6 text-[14px] text-bad">{error}</p>}

      {sections?.length === 0 && !status && (
        <p className="mt-12 text-[15px] text-subtle">No CV uploaded yet.</p>
      )}

      <div className="mt-10 space-y-10">
        {sections?.map((sec, si) => (
          <section key={sec.id}>
            <h2 className="section-title">{sec.title}</h2>
            <div className="divider mt-3" />
            <ul className="mt-3 space-y-1">
              {sec.bullets.map((b, bi) => (
                <li key={b.index}>
                  <textarea
                    className="w-full resize-none rounded-lg px-2 py-1.5 text-[14px] leading-relaxed
                               hover:bg-canvas focus:bg-canvas outline-none transition-colors"
                    rows={2}
                    defaultValue={b.text}
                    onBlur={(e) => e.target.value !== b.text && saveBullet(si, bi, e.target.value)}
                  />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
