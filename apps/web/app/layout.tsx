import type { Metadata, Viewport } from "next";
import { Nav } from "@/components/Nav";
import { Footer } from "@/components/Footer";
import { APP } from "@/lib/meta";
import "./globals.css";

export const metadata: Metadata = {
  title: APP.name,
  description: APP.tagline,
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col">
        <Nav />
        <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
