"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { supabaseBrowser } from "@/lib/supabase";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/analyse", label: "Analyse" },
  { href: "/cv", label: "CV" },
  { href: "/profile", label: "Profile" },
  { href: "/history", label: "History" },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();

  const publicPage = ["/login", "/signup", "/reset-password"].some((p) =>
    pathname.startsWith(p)
  );
  if (publicPage) return null;

  async function signOut() {
    await supabaseBrowser().auth.signOut();
    router.push("/login");
  }

  return (
    <header className="sticky top-0 z-10 bg-white/70 backdrop-blur-xl">
      <nav className="mx-auto flex max-w-4xl items-center px-6 py-3.5">
        <Link href="/dashboard" className="text-[17px] font-semibold tracking-tight">
          CV&nbsp;Tailor<span className="text-accent">.</span>
        </Link>
        <div className="ml-6 flex gap-1 overflow-x-auto text-[14px]">
          {links.map((l) => {
            const active = pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`whitespace-nowrap rounded-full px-3.5 py-1.5 transition-colors ${
                  active
                    ? "bg-canvas text-ink font-medium"
                    : "text-subtle hover:text-ink"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </div>
        <button
          onClick={signOut}
          className="ml-auto pl-4 text-[13px] text-subtle hover:text-ink transition-colors"
        >
          Sign out
        </button>
      </nav>
      <div className="divider" />
    </header>
  );
}
