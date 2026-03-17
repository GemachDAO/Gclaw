/**
 * x402 Payment Signing Helper
 *
 * Signs EIP-3009 transferWithAuthorization payloads for the x402 protocol.
 * Called by the Go x402 client via stdin/stdout JSON.
 *
 * Input (stdin JSON):
 *   {
 *     "action": "sign",
 *     "params": {
 *       "private_key": "0x...",
 *       "wallet_address": "0x...",
 *       "pay_to": "0x...",
 *       "amount": "1000",
 *       "network": "base",
 *       "extra": { "name": "USDC", "version": "2", "chainId": 8453, "tokenAddress": "0x..." }
 *     }
 *   }
 *
 * Output (stdout JSON):
 *   {
 *     "x402Version": 1,
 *     "scheme": "exact",
 *     "network": "base",
 *     "payload": {
 *       "signature": "0x...",
 *       "authorization": {
 *         "from": "0x...",
 *         "to": "0x...",
 *         "value": "1000",
 *         "validAfter": "0",
 *         "validBefore": "...",
 *         "nonce": "0x..."
 *       }
 *     }
 *   }
 */

const { ethers } = require("ethers");

// Well-known USDC contract details per network.
const NETWORK_CONFIG = {
  base: {
    chainId: 8453,
    tokenAddress: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    name: "USD Coin",
    version: "2",
  },
  ethereum: {
    chainId: 1,
    tokenAddress: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    name: "USD Coin",
    version: "2",
  },
  "base-sepolia": {
    chainId: 84532,
    tokenAddress: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    name: "USD Coin",
    version: "2",
  },
};

// EIP-712 types for EIP-3009 TransferWithAuthorization.
const EIP3009_TYPES = {
  TransferWithAuthorization: [
    { name: "from", type: "address" },
    { name: "to", type: "address" },
    { name: "value", type: "uint256" },
    { name: "validAfter", type: "uint256" },
    { name: "validBefore", type: "uint256" },
    { name: "nonce", type: "bytes32" },
  ],
};

async function signPayment(params) {
  const { private_key, wallet_address, pay_to, amount, network, extra } =
    params;

  if (!private_key || !pay_to || !amount) {
    throw new Error("private_key, pay_to, and amount are required");
  }

  // Resolve network config (prefer extra fields if provided).
  const netCfg = NETWORK_CONFIG[network] || NETWORK_CONFIG["base"];

  const chainId = extra?.chainId ?? netCfg.chainId;
  const tokenAddress = extra?.tokenAddress ?? netCfg.tokenAddress;
  const tokenName = extra?.name ?? netCfg.name;
  const tokenVersion = extra?.version ?? netCfg.version;

  // Create wallet from private key.
  const pk = private_key.startsWith("0x") ? private_key : "0x" + private_key;
  const wallet = new ethers.Wallet(pk);

  const from = wallet_address || wallet.address;

  // Generate random nonce (bytes32).
  const nonce = ethers.hexlify(ethers.randomBytes(32));

  // Set validity window: valid immediately, expires in 1 hour.
  const validAfter = "0";
  const validBefore = String(Math.floor(Date.now() / 1000) + 3600);

  // EIP-712 domain.
  const domain = {
    name: tokenName,
    version: tokenVersion,
    chainId: chainId,
    verifyingContract: tokenAddress,
  };

  // Authorization message.
  const message = {
    from: from,
    to: pay_to,
    value: amount,
    validAfter: validAfter,
    validBefore: validBefore,
    nonce: nonce,
  };

  // Sign the typed data (EIP-712).
  const signature = await wallet.signTypedData(domain, EIP3009_TYPES, message);

  return {
    x402Version: 1,
    scheme: "exact",
    network: network || "base",
    payload: {
      signature: signature,
      authorization: {
        from: from,
        to: pay_to,
        value: amount,
        validAfter: validAfter,
        validBefore: validBefore,
        nonce: nonce,
      },
    },
  };
}

// Main: read JSON from stdin, process, write JSON to stdout.
async function main() {
  let inputData = "";
  for await (const chunk of process.stdin) {
    inputData += chunk;
  }

  try {
    const input = JSON.parse(inputData);

    if (input.action !== "sign") {
      throw new Error(`unknown action: ${input.action}`);
    }

    const result = await signPayment(input.params);
    process.stdout.write(JSON.stringify(result));
  } catch (err) {
    process.stdout.write(JSON.stringify({ error: err.message }));
    process.exit(1);
  }
}

main();
