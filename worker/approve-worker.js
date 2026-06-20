export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/respond") {
      return new Response("Not found", { status: 404 });
    }

    const token = url.searchParams.get("token");
    if (!token) {
      return new Response("Missing token", { status: 400 });
    }

    const [encodedPayload, sig] = token.split(".");
    if (!encodedPayload || !sig) {
      return new Response("Malformed token", { status: 400 });
    }

    let payload;
    try {
      payload = atob(encodedPayload.replace(/-/g, "+").replace(/_/g, "/"));
    } catch (e) {
      return new Response("Malformed token", { status: 400 });
    }

    const expectedSig = await hmacHex(env.APPROVAL_SECRET, payload);
    if (expectedSig !== sig) {
      return new Response("Invalid signature", { status: 403 });
    }

    const [date, decision, expiry] = payload.split("|");
    if (Date.now() / 1000 > Number(expiry)) {
      return new Response(
        "<html><body style='font-family:sans-serif;text-align:center;padding:60px'><h2>This link has expired.</h2></body></html>",
        { status: 410, headers: { "Content-Type": "text/html" } }
      );
    }

    const dispatchResp = await fetch(
      `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/publish1.yml/dispatches`,
      
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_PAT}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "ig-auto-poster-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "master", inputs: { date, decision } }),
      }
    );

    if (!dispatchResp.ok) {
      const errText = await dispatchResp.text();
      return new Response(`GitHub dispatch failed: ${errText}`, { status: 502 });
    }

    const message =
      decision === "approve"
        ? "Approved. Your post is being published now."
        : "Skipped. Nothing will be posted today.";

    return new Response(
      `<html><body style="font-family:sans-serif;text-align:center;padding:60px"><h2>${message}</h2></body></html>`,
      { headers: { "Content-Type": "text/html" } }
    );
  },
};

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
