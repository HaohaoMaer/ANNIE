"use client";

import { useEffect, useRef } from "react";

interface Blob {
  x: number;
  y: number;
  radius: number;
  speedX: number;
  speedY: number;
  opacity: number;
}

export function FogOverlay({ intensity = "low" }: { intensity?: "low" | "medium" | "high" }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const blobsRef = useRef<Blob[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const count = intensity === "high" ? 40 : intensity === "medium" ? 25 : 15;
    const maxOpacity = intensity === "high" ? 0.08 : intensity === "medium" ? 0.05 : 0.03;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    blobsRef.current = Array.from({ length: count }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      radius: 100 + Math.random() * 300,
      speedX: (Math.random() - 0.5) * 0.3,
      speedY: (Math.random() - 0.5) * 0.15,
      opacity: Math.random() * maxOpacity,
    }));

    let animId: number;
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const b of blobsRef.current) {
        b.x += b.speedX;
        b.y += b.speedY;
        if (b.x > canvas.width + b.radius) b.x = -b.radius;
        if (b.x < -b.radius) b.x = canvas.width + b.radius;
        if (b.y > canvas.height + b.radius) b.y = -b.radius;
        if (b.y < -b.radius) b.y = canvas.height + b.radius;

        const grad = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.radius);
        grad.addColorStop(0, `rgba(148, 163, 184, ${b.opacity})`);
        grad.addColorStop(1, "rgba(148, 163, 184, 0)");
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2);
        ctx.fill();
      }
      animId = requestAnimationFrame(animate);
    };
    animate();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, [intensity]);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-50 pointer-events-none"
      aria-hidden
    />
  );
}
