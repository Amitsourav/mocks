// Supabase "Send SMS Hook".
//
// Supabase Auth generates the OTP itself and POSTs it here instead of calling a
// built-in provider. We forward it to whichever SMS vendor is configured. This
// exists because Supabase natively supports only Twilio / MessageBird / Vonage /
// TextLocal — anything else (Plivo, MSG91, ...) must come through this hook.
//
// Switching vendor is an env change (SMS_PROVIDER + that vendor's secrets), not
// a code change.
//
// Required secrets (Dashboard -> Edge Functions -> Secrets):
//   SEND_SMS_HOOK_SECRET  - from Auth -> Hooks (the "v1,whsec_..." value)
//   SMS_PROVIDER          - "plivo" | "msg91"   (default: plivo)
//   -- Plivo (international route; no DLT, US-origin) --
//   PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_SRC (E.164 sender)
//   -- MSG91 (domestic India; requires DLT registration) --
//   MSG91_AUTH_KEY        - MSG91 account auth key
//   MSG91_TEMPLATE_ID     - DLT-registered flow/template id
//   MSG91_SENDER          - approved 6-char DLT header (optional if the
//                           template already binds a sender)
//
// The OTP text lives in MSG91's DLT-registered template server-side (we send
// only the code as var1). For Plivo we render the text here — keep it matching
// whatever template you register if you ever DLT-register the Plivo route too.

import { Webhook } from "https://esm.sh/standardwebhooks@1.0.0";

const SEND_TIMEOUT_MS = 10_000;

function env(key: string): string {
  const v = Deno.env.get(key);
  if (!v) throw new Error(`Missing required secret: ${key}`);
  return v;
}

/** E.164 with leading '+'. Supabase delivers the phone without one. */
function toE164(phone: string): string {
  const p = phone.trim();
  return p.startsWith("+") ? p : `+${p}`;
}

interface SmsProvider {
  readonly name: string;
  // Providers receive the raw OTP. A raw-SMS vendor (Plivo) renders the text;
  // a template vendor (MSG91) injects the code into a server-side template.
  send(toE164Phone: string, otp: string): Promise<void>;
}

const plivo: SmsProvider = {
  name: "plivo",
  async send(to, otp) {
    const authId = env("PLIVO_AUTH_ID");
    const authToken = env("PLIVO_AUTH_TOKEN");
    const res = await fetch(
      `https://api.plivo.com/v1/Account/${authId}/Message/`,
      {
        method: "POST",
        headers: {
          "Authorization": `Basic ${btoa(`${authId}:${authToken}`)}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          src: env("PLIVO_SRC"),
          dst: to,
          text: `Your code is ${otp}`,
        }),
        signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
      },
    );
    if (res.status !== 202) {
      throw new Error(`plivo ${res.status}: ${await res.text()}`);
    }
  },
};

const msg91: SmsProvider = {
  name: "msg91",
  async send(to, otp) {
    // MSG91 V5 Flow API: the message text is the DLT-registered template on
    // MSG91's side; we pass only the OTP as a variable. `mobiles` wants the
    // country code but no '+'.
    const recipient: Record<string, string> = {
      mobiles: to.replace(/^\+/, ""),
      var1: otp,
    };
    const sender = Deno.env.get("MSG91_SENDER");
    const payload: Record<string, unknown> = {
      template_id: env("MSG91_TEMPLATE_ID"),
      recipients: [recipient],
    };
    if (sender) payload.sender = sender;

    const res = await fetch("https://control.msg91.com/api/v5/flow", {
      method: "POST",
      headers: {
        "authkey": env("MSG91_AUTH_KEY"),
        "Content-Type": "application/json",
        "accept": "application/json",
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
    });
    // MSG91 returns 200 even for some logical errors, with {type:"error"} in
    // the body — so inspect the body, not just the status.
    const text = await res.text();
    if (!res.ok || /"type"\s*:\s*"error"/.test(text)) {
      throw new Error(`msg91 ${res.status}: ${text}`);
    }
  },
};

const PROVIDERS: Record<string, SmsProvider> = { plivo, msg91 };

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  const raw = await req.text();

  // This endpoint is public; only Supabase's signed webhook may trigger a send.
  let payload: { user: { phone: string }; sms: { otp: string } };
  try {
    const secret = env("SEND_SMS_HOOK_SECRET").replace("v1,whsec_", "");
    const wh = new Webhook(secret);
    payload = wh.verify(raw, Object.fromEntries(req.headers)) as typeof payload;
  } catch (err) {
    console.error("signature verification failed:", err instanceof Error ? err.message : err);
    return new Response(JSON.stringify({ error: "invalid signature" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const providerName = Deno.env.get("SMS_PROVIDER") ?? "plivo";
  const provider = PROVIDERS[providerName];
  if (!provider) {
    console.error(`unknown SMS_PROVIDER: ${providerName}`);
    return new Response(JSON.stringify({ error: "provider misconfigured" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  const to = toE164(payload.user.phone);
  try {
    await provider.send(to, payload.sms.otp);
  } catch (err) {
    // Never log the OTP. Mask the destination.
    const masked = to.slice(0, 4) + "****" + to.slice(-3);
    console.error(`${provider.name} send failed for ${masked}:`, err instanceof Error ? err.message : err);
    return new Response(
      JSON.stringify({ error: { http_code: 502, message: `sms delivery failed via ${provider.name}` } }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
});
