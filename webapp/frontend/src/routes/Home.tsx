import { useState, useEffect } from "react";
import "../marketing/marketing.css";
import MarketingNav from "../marketing/MarketingNav";
import Hero from "../marketing/Hero";
import {
  About,
  Features,
  Problems,
  Process,
  CoreEngine,
  Advantages,
  Sectors,
  FAQ,
  CTAStrip,
} from "../marketing/Sections";
import MarketingFooter from "../marketing/Footer";

export default function Home() {
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  const fireToast = (msg: string) => setToast(msg);

  return (
    <>
      <MarketingNav />
      <Hero onCTA={fireToast} />
      <About />
      <Features />
      <Problems />
      <CoreEngine />
      <Process />
      <Advantages />
      <Sectors />
      <FAQ />
      <CTAStrip onCTA={fireToast} />
      <MarketingFooter />

      {/* toast notification */}
      <div className={`mkt-toast ${toast ? "show" : ""}`}>
        <span className="dot" />
        {toast || ""}
      </div>
    </>
  );
}
