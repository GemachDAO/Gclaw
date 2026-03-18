/**
 * Tempo MPP Payment Helper
 *
 * Handles 402 Payment Required challenges by parsing the WWW-Authenticate
 * header, signing a Tempo charge credential, and returning the Authorization
 * header value for the retry request.
 *
 * Called by the Go tempo client via stdin/stdout JSON.
 *
 * Input (stdin JSON):
 *   {
 *     "action": "pay",
 *     "params": {
 *       "private_key": "0x...",
 *       "wallet_address": "0x...",
 *       "www_authenticate": "Payment id=\"...\", realm=\"...\", ...",
 *       "rpc_url": "https://rpc.tempo.xyz"
 *     }
 *   }
 *
 * Output (stdout JSON):
 *   {
 *     "authorization": "Payment eyJ..."
 *   }
 */

const { privateKeyToAccount } = require("viem/accounts");
const { createWalletClient, http } = require("viem");
const { tempo } = require("viem/chains");

/**
 * Parse a single auth-param value (quoted-string or token).
 */
function readValue(input, start) {
  if (input[start] === '"') {
    let i = start + 1;
    let value = "";
    let escaped = false;
    while (i < input.length) {
      const ch = input[i];
      i++;
      if (escaped) {
        value += ch;
        escaped = false;
        continue;
      }
      if (ch === "\\") {
        escaped = true;
        continue;
      }
      if (ch === '"') return [value, i];
      value += ch;
    }
    throw new Error("Unterminated quoted-string");
  }
  let i = start;
  while (i < input.length && input[i] !== ",") i++;
  return [input.slice(start, i).trim(), i];
}

/**
 * Parse auth-params from a WWW-Authenticate header value (after "Payment ").
 */
function parseAuthParams(input) {
  const result = {};
  let i = 0;
  while (i < input.length) {
    while (i < input.length && /[\s,]/.test(input[i])) i++;
    if (i >= input.length) break;

    const keyStart = i;
    while (i < input.length && /[A-Za-z0-9_-]/.test(input[i])) i++;
    const key = input.slice(keyStart, i);
    if (!key) break;

    while (i < input.length && /\s/.test(input[i])) i++;
    if (input[i] !== "=") break;
    i++;
    while (i < input.length && /\s/.test(input[i])) i++;

    const [value, nextIndex] = readValue(input, i);
    i = nextIndex;
    result[key] = value;
  }
  return result;
}

/**
 * Deserialize a base64url-encoded JSON request field.
 */
function deserializeRequest(encoded) {
  // base64url → base64 standard
  let b64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
  const pad = b64.length % 4;
  if (pad) b64 += "=".repeat(4 - pad);
  const json = Buffer.from(b64, "base64").toString("utf-8");
  return JSON.parse(json);
}

/**
 * Serialize an object to base64url (no padding) for the MPP protocol.
 */
function serializeToBase64url(obj) {
  const json = JSON.stringify(obj);
  return Buffer.from(json, "utf-8")
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/**
 * Parse a WWW-Authenticate header into a challenge object.
 */
function parseChallenge(wwwAuthenticate) {
  const paymentIdx = wwwAuthenticate.indexOf("Payment ");
  if (paymentIdx === -1) throw new Error("Missing Payment scheme");

  const paramsStr = wwwAuthenticate.slice(paymentIdx + "Payment ".length);
  const params = parseAuthParams(paramsStr);

  if (!params.request) throw new Error("Missing request parameter in challenge");

  return {
    id: params.id,
    realm: params.realm,
    method: params.method,
    intent: params.intent,
    request: deserializeRequest(params.request),
    ...(params.description && { description: params.description }),
    ...(params.expires && { expires: params.expires }),
    ...(params.digest && { digest: params.digest }),
    ...(params.opaque && { opaque: deserializeRequest(params.opaque) }),
  };
}

/**
 * Create a signed payment credential for a Tempo charge challenge.
 */
async function handleCharge(challenge, account, walletClient) {
  // Preserve the original request value as received in the challenge.
  const rawRequest = challenge.request;

  // Decode the request separately for signing / budgeting logic.
  const request =
    typeof rawRequest === "string"
      ? JSON.parse(Buffer.from(rawRequest, "base64url").toString("utf8"))
      : rawRequest;

  const amount = BigInt(request.amount);
  const currency = request.currency;
  const recipient = request.recipient;

  // Build a TIP-20 transfer call (transfer(address,uint256) with memo).
  // For the Go client, we sign a transaction that the server can verify/submit.
  const transferAbi = [
    {
      name: "transfer",
      type: "function",
      stateMutability: "nonpayable",
      inputs: [
        { name: "to", type: "address" },
        { name: "amount", type: "uint256" },
      ],
      outputs: [{ name: "", type: "bool" }],
    },
  ];

  const { encodeFunctionData } = require("viem");
  const data = encodeFunctionData({
    abi: transferAbi,
    functionName: "transfer",
    args: [recipient, amount],
  });

  // Sign the transaction.
  const tx = {
    to: currency,
    data: data,
    chain: tempo,
    account: account,
  };

  const signature = await walletClient.signTransaction(tx);

  // Build the credential. Use the original request string (if any)
  // instead of re-serializing the decoded object to base64url.
  const credential = {
    challenge: {
      ...challenge,
      request: rawRequest,
    },
    payload: {
      signature: signature,
      type: "transaction",
    },
    source: `did:pkh:eip155:${tempo.id}:${account.address}`,
  };

  const encoded = serializeToBase64url(credential);
  return `Payment ${encoded}`;
}

/**
 * Main: read JSON from stdin, process, write JSON to stdout.
 */
async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const inputStr = Buffer.concat(chunks).toString("utf-8").trim();
  if (!inputStr) {
    console.log(JSON.stringify({ error: "empty input" }));
    process.exit(1);
  }

  let input;
  try {
    input = JSON.parse(inputStr);
  } catch (e) {
    console.log(JSON.stringify({ error: `invalid JSON input: ${e.message}` }));
    process.exit(1);
  }

  const { action, params } = input;
  if (action !== "pay") {
    console.log(JSON.stringify({ error: `unknown action: ${action}` }));
    process.exit(1);
  }

  const { private_key, wallet_address, www_authenticate, rpc_url } = params;
  if (!private_key || !www_authenticate) {
    console.log(
      JSON.stringify({ error: "private_key and www_authenticate are required" })
    );
    process.exit(1);
  }

  try {
    // Normalise the private key (ensure 0x prefix).
    let key = private_key;
    if (!key.startsWith("0x")) key = "0x" + key;

    const account = privateKeyToAccount(key);

    // If a wallet_address is provided, ensure it matches the derived address.
    if (wallet_address) {
      let providedAddress = wallet_address;
      if (!providedAddress.startsWith("0x")) {
        providedAddress = "0x" + providedAddress;
      }
      if (providedAddress.toLowerCase() !== account.address.toLowerCase()) {
        console.log(
          JSON.stringify({
            error:
              "wallet_address does not match the address derived from private_key",
          })
        );
        process.exit(1);
      }
    }

    const walletClient = createWalletClient({
      account,
      chain: tempo,
      transport: http(rpc_url || "https://rpc.tempo.xyz"),
    });

    const challenge = parseChallenge(www_authenticate);

    let authorization;
    if (challenge.method === "tempo" && challenge.intent === "charge") {
      authorization = await handleCharge(challenge, account, walletClient);
    } else {
      // For unsupported intents, still attempt to handle as a generic charge.
      authorization = await handleCharge(challenge, account, walletClient);
    }

    console.log(JSON.stringify({ authorization }));
  } catch (e) {
    console.log(JSON.stringify({ error: e.message || String(e) }));
    process.exit(1);
  }
}

main();
