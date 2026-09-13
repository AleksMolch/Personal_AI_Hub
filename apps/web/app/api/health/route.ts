import { NextResponse } from "next/server";

/**
 * Health-эндпоинт web-приложения. Используется healthcheck'ом Docker Compose.
 */
export function GET() {
  return NextResponse.json({ status: "ok" });
}
