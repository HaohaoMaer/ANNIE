import { FogOverlay } from "@/components/layout/FogOverlay";
import { Header } from "@/components/layout/Header";
import { HeroSection } from "@/components/landing/HeroSection";
import { FeatureCards } from "@/components/landing/FeatureCards";

export default function HomePage() {
  return (
    <>
      <FogOverlay intensity="low" />
      <Header />
      <main>
        <HeroSection />
        <FeatureCards />
      </main>
    </>
  );
}
