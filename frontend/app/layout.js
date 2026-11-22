import "./globals.css";
import { Manrope, Space_Grotesk } from "next/font/google";
import Nav from "@/components/Nav";
import { LanguageProvider } from "@/components/LanguageProvider";
import RegisterSW from "@/components/RegisterSW";

const body = Manrope({ subsets: ["latin"], variable: "--font-body" });
const display = Space_Grotesk({ subsets: ["latin"], variable: "--font-display" });

export const metadata = {
  title: "MIRA — Go Beyond the Headline",
  description: "AI-powered news discovery and research for journalists.",
  manifest: "/manifest.json",
  icons: { icon: "/mira-logo.png" },
};
export const viewport = { themeColor: "#000000", viewportFit: "cover", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className={`${body.variable} ${display.variable} font-body`}>
        <LanguageProvider>
          <div id="app-root">
            <Nav />
            <main className="mira-main mx-auto w-full max-w-[1800px] px-4 py-5 sm:px-6 lg:px-8">{children}</main>
          </div>
          <RegisterSW />
        </LanguageProvider>
      </body>
    </html>
  );
}
