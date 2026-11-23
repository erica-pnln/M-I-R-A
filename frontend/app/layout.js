import "./globals.css";
import { Manrope, Space_Grotesk } from "next/font/google";
import { LanguageProvider } from "@/components/LanguageProvider";
import RegisterSW from "@/components/RegisterSW";
import AppShell from "@/components/AppShell";
import ThemeProvider from "@/components/ThemeProvider";

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
        <ThemeProvider>
          <LanguageProvider>
            <AppShell>{children}</AppShell>
            <RegisterSW />
          </LanguageProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
