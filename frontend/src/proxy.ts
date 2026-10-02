import { NextResponse, type NextRequest } from "next/server";

/**
 * Content-Security-Policy con nonce por pedido: sólo ejecutan los scripts que
 * Next.js emitió para esta respuesta (y los que esos cargan, por
 * 'strict-dynamic'). Un script inyectado en la página —un XSS— no tiene el
 * nonce y el navegador no lo corre.
 *
 * No corre sobre /api: las respuestas del backend traen su propia CSP, y así
 * Next tampoco tiene que retener en memoria los cuerpos de las subidas.
 */
export function proxy(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  const isHttps =
    request.nextUrl.protocol === "https:" || request.headers.get("x-forwarded-proto") === "https";

  const policy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // React y MapLibre escriben estilos en línea; inyectar CSS no ejecuta código.
    "style-src 'self' 'unsafe-inline'",
    // Tiles de OpenStreetMap y glifos para los rótulos del mapa.
    "img-src 'self' data: blob: https://*.tile.openstreetmap.org",
    "connect-src 'self' https://*.tile.openstreetmap.org https://fonts.openmaptiles.org",
    // MapLibre dibuja en web workers creados desde blob:.
    "worker-src 'self' blob:",
    "child-src blob:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(isHttps ? ["upgrade-insecure-requests"] : []),
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  if (isHttps) response.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains");
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!api|_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
