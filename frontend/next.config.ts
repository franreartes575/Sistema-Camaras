import type { NextConfig } from "next";

/**
 * El navegador sólo habla con este servidor: `/api/*` se reenvía al backend.
 * Así las cookies de sesión son del mismo origen (SameSite=Strict funciona) y
 * el backend no necesita CORS. `BACKEND_URL` es la dirección interna del
 * backend; NEXT_PUBLIC_API_BASE_URL se acepta por compatibilidad con un
 * .env.local viejo, pero ya no llega al navegador.
 */
const BACKEND_URL = (
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

// Cabeceras fijas para todas las páginas. La CSP (con nonce por pedido) la
// pone src/proxy.ts.
const SECURITY_HEADERS = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // El backend usa rutas con barra final (/upload-excel/): sin esto, Next
  // las redirigiría sin la barra y FastAPI las volvería a redirigir.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      // Primero la variante con barra final: `:path*` la descarta, y sin ella
      // FastAPI respondería 404 (no redirige: ver redirect_slashes en main.py).
      { source: "/api/:path*/", destination: `${BACKEND_URL}/:path*/` },
      { source: "/api/:path*", destination: `${BACKEND_URL}/:path*` },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
