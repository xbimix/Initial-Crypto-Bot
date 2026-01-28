import { NextResponse } from "next/server";

const BACKEND = "http://127.0.0.1:8001";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/config`, {
      cache: "no-store",
    });

    const text = await res.text();

    if (!text) {
      return NextResponse.json(
        { error: "Empty response from Flask backend" },
        { status: 502 }
      );
    }

    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err: any) {
    return NextResponse.json(
      { error: err.message },
      { status: 500 }
    );
  }
}

export async function POST(req: Request) {
  try {
    const body = await req.json();

    const res = await fetch(`${BACKEND}/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const text = await res.text();

    if (!text) {
      return NextResponse.json(
        { error: "Empty response from Flask backend" },
        { status: 502 }
      );
    }

    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err: any) {
    return NextResponse.json(
      { error: err.message },
      { status: 500 }
    );
  }
}
