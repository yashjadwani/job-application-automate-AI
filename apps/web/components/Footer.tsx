import Link from "next/link";
import { APP } from "@/lib/meta";

const links = [
  { label: "Documentation", href: APP.docsUrl, external: true },
  { label: "GitHub", href: APP.repoUrl, external: true },
  { label: "Changelog", href: "#" },
  { label: "Feedback", href: "#" },
  { label: "Privacy", href: "#" },
  { label: "Terms", href: "#" },
];

export function Footer() {
  return (
    <footer className="mt-auto">
      <div className="divider" />
      <div className="mx-auto max-w-4xl px-6 py-8">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-xs">
            <div className="text-[15px] font-semibold tracking-tight">
              {APP.name}<span className="text-accent">.</span>
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-subtle">
              {APP.tagline}
            </p>
          </div>

          <nav className="flex flex-wrap gap-x-6 gap-y-2 text-[13px]">
            {links.map((l) =>
              l.external ? (
                <a key={l.label} href={l.href} target="_blank" rel="noreferrer"
                   className="text-subtle transition-colors hover:text-ink">
                  {l.label}
                </a>
              ) : (
                <Link key={l.label} href={l.href}
                      className="text-subtle transition-colors hover:text-ink">
                  {l.label}
                </Link>
              )
            )}
          </nav>
        </div>

        <div className="mt-6 flex flex-col gap-1 text-[12px] text-subtle sm:flex-row sm:items-center sm:justify-between">
          <span>
            © {new Date().getFullYear()} {APP.name} · v{APP.version}
          </span>
          <span>
            Built with <span className="text-bad">♥</span> using {APP.stack}
          </span>
        </div>
      </div>
    </footer>
  );
}
