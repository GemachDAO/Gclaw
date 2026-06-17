#!/usr/bin/env node
/**
 * Gclaw GDEX session signer — the ONE step the MCP cannot do.
 *
 * Managed custody never exposes the control private key to the MCP, so the
 * sign-in message must be signed locally. This is pure crypto (no network, no
 * HyperLiquid websocket) so it returns instantly — unlike a full SDK trade call.
 *
 * It prints the credentials the MCP managed-custody tools then consume:
 *   1. node gdex_sign.js            -> { apiKey, userId, sessionKey, sessionPrivateKey, nonce, signature }
 *   2. mcp__gdex__build_sign_in_payload  (apiKey,userId,sessionKey,nonce,signature) -> computedData
 *   3. mcp__gdex__managed_sign_in        (computedData, chainId)
 *   4. mcp__gdex__open_perp_position     (apiKey, walletAddress=userId, sessionPrivateKey, ...)
 *
 * Env: GDEX_SKILL_DIR (default ~/gdex-skill), GCLAW_WALLET (default ~/gdex-test-wallet.json),
 *      GDEX_API_KEY (overrides shared primary).
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH = process.env.GCLAW_WALLET || [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) => fs.existsSync(p)) || path.join(os.homedir(), 'gdex-test-wallet.json');
const { ethers } = require(path.join(GDEX_DIR, 'node_modules', 'ethers'));
const SDK = require(path.join(GDEX_DIR, 'dist'));

async function main() {
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  if (!w.control?.address || !w.control?.privateKey) {
    throw new Error(`wallet ${WALLET_PATH} missing control key`);
  }
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const userId = w.control.address;
  const { sessionKey, sessionPrivateKey } = SDK.generateGdexSessionKeyPair();
  const nonce = SDK.generateGdexNonce().toString();
  const message = SDK.buildGdexSignInMessage(userId, nonce, sessionKey);
  const signature = (await new ethers.Wallet(w.control.privateKey).signMessage(message)).replace(/^0x/, '');
  process.stdout.write(
    JSON.stringify({ apiKey, userId, sessionKey, sessionPrivateKey, nonce, signature }) + '\n',
  );
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ error: e.message || String(e) }) + '\n');
  process.exit(1);
});
