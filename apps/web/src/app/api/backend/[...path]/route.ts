import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const FASTAPI_URL = process.env.FASTAPI_BACKEND_URL || "http://127.0.0.1:8000";

async function proxyRequest(
  request: NextRequest,
  params: Promise<{ path: string[] }>
) {
  try {
    const resolvedParams = await params;
    const path = resolvedParams.path ? resolvedParams.path.join("/") : "";
    const search = request.nextUrl.search;
    const targetUrl = `${FASTAPI_URL}/${path}${search}`;

    // Prepare headers for upstream FastAPI
    const headers = new Headers();
    request.headers.forEach((val, key) => {
      if (
        !["host", "connection", "content-length", "cookie"].includes(
          key.toLowerCase()
        )
      ) {
        headers.set(key, val);
      }
    });

    // Check if client already provided Authorization header
    if (!headers.has("Authorization")) {
      const supabase = await createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (session?.access_token) {
        headers.set("Authorization", `Bearer ${session.access_token}`);
      }
    }

    // Forward raw body stream directly for non-GET/HEAD methods
    let body: BodyInit | undefined = undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await request.arrayBuffer();
    }

    const fetchOptions: RequestInit = {
      method: request.method,
      headers,
    };

    if (body) {
      fetchOptions.body = body;
      // @ts-expect-error duplex required when streaming body in Node fetch
      fetchOptions.duplex = "half";
    }

    const response = await fetch(targetUrl, fetchOptions);

    const responseHeaders = new Headers();
    response.headers.forEach((val, key) => {
      if (!["content-encoding", "transfer-encoding"].includes(key.toLowerCase())) {
        responseHeaders.set(key, val);
      }
    });

    const responseBody = await response.arrayBuffer();
    return new NextResponse(responseBody, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("Proxy error:", error);
    return NextResponse.json(
      { error: "Backend proxy service unavailable" },
      { status: 503 }
    );
  }
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, context.params);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, context.params);
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, context.params);
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, context.params);
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, context.params);
}
