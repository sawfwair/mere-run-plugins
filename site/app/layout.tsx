import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "plugins.mere.run";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  const metadataBase = new URL(`${protocol}://${host}`);

  return {
    metadataBase,
    title: "mere.run plugins — Local AI, extended",
    description:
      "Official companion plugins for mere.run: realtime music, VFX, private documents, production workflows, and user-owned GPU training.",
    openGraph: {
      type: "website",
      url: "/",
      siteName: "mere.run plugins",
      title: "Local AI, extended.",
      description: "Twelve companion plugins. One local-first runtime.",
      images: [
        {
          url: "/og.png",
          width: 1200,
          height: 630,
          alt: "Local AI, extended — mere.run plugins",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: "mere.run plugins — Local AI, extended",
      description: "Twelve companion plugins. One local-first runtime.",
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
