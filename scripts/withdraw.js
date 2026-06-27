#!/usr/bin/env node
/**
 * Owner withdrawal — get YOUR managed funds out. Your money is always yours.
 *
 * The heartbeat's anti-drain deny-list blocks the AUTONOMOUS model from moving funds;
 * it does NOT lock the owner out. You hold the control wallet, so you can always
 * withdraw. This wraps the two managed-custody legs the SDK already exposes:
 *
 *   1. HL → Arbitrum:   perpWithdraw  (USDC off the HyperLiquid perp account)
 *   2. Arbitrum → you:  transferToken (USDC from the managed wallet to any address)
 *
 *   node withdraw.js status                         # balances + route (read-only)
 *   node withdraw.js hl   --amount 50               # DRY RUN: plan the HL→Arbitrum leg
 *   node withdraw.js hl   --amount 50   --confirm   # execute it
 *   node withdraw.js send --to 0xYou --amount 50            # DRY RUN: plan the payout
 *   node withdraw.js send --to 0xYou --amount 50 --confirm  # execute it
 *
 * Anti-drain: a real (`--confirm`) move requires an interactive terminal (a TTY). The
 * unattended heartbeat is headless, so the autonomous agent can never withdraw through
 * this script; under GCLAW_SANDBOX the wallet is masked too. Env: GCLAW_WALLET, ARB_RPC.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ARB_CHAIN = 42161;
const ARB_USDC = '0xaf88d065e77c8cC2239327C5EDb3A432268e5831';
const ARB_RPC = process.env.ARB_RPC || 'https://arb1.arbitrum.io/rpc';
const GDEX_DIR = process.env.GDEX_SKILL_DIR || path.join(os.homedir(), 'gdex-skill');
const WALLET_PATH =
  process.env.GCLAW_WALLET ||
  [path.join(os.homedir(), '.gclaw', 'wallet.json'), path.join(os.homedir(), 'gdex-test-wallet.json')].find((p) =>
    fs.existsSync(p),
  ) ||
  path.join(os.homedir(), 'gdex-test-wallet.json');

const loadSdk = () => ({
  ethers: require(path.join(GDEX_DIR, 'node_modules', 'ethers')).ethers,
  SDK: require(path.join(GDEX_DIR, 'dist')),
});

function die(msg) {
  process.stdout.write(JSON.stringify({ ok: false, error: msg }) + '\n');
  process.exit(1);
}

function loadWallet() {
  const w = JSON.parse(fs.readFileSync(WALLET_PATH, 'utf8'));
  const managed = w.managed?.['Arbitrum (HyperLiquid)']?.address;
  if (!w.control?.address || !w.control?.privateKey) die('wallet missing control key');
  if (!managed) die('wallet missing managed Arbitrum (HyperLiquid) address');
  return { control: w.control.address, pk: w.control.privateKey, managed };
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      out[key] = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[(i += 1)] : true;
    }
  }
  return out;
}

async function signIn(wallet, SDK, ethers) {
  const apiKey = process.env.GDEX_API_KEY || SDK.GDEX_API_KEY_PRIMARY;
  const skill = new SDK.GdexSkill({ timeout: 60000, maxRetries: 1 });
  skill.loginWithApiKey(apiKey);
  const kp = SDK.generateGdexSessionKeyPair();
  const nonce = SDK.generateGdexNonce().toString();
  const sig = (
    await new ethers.Wallet(wallet.pk).signMessage(SDK.buildGdexSignInMessage(wallet.control, nonce, kp.sessionKey))
  ).replace(/^0x/, '');
  const payload = SDK.buildGdexSignInComputedData({
    apiKey,
    userId: wallet.control,
    sessionKey: kp.sessionKey,
    nonce,
    signature: sig,
  });
  await skill.signInWithComputedData({ computedData: payload.computedData, chainId: ARB_CHAIN });
  return { skill, creds: { apiKey, walletAddress: wallet.control, sessionPrivateKey: kp.sessionPrivateKey } };
}

async function balances(wallet, ethers) {
  const provider = new ethers.JsonRpcProvider(ARB_RPC);
  const erc20 = new ethers.Contract(ARB_USDC, ['function balanceOf(address) view returns (uint256)'], provider);
  const arbUsdc = Number(ethers.formatUnits(await erc20.balanceOf(wallet.managed).catch(() => 0n), 6));
  return { arbUsdc };
}

// A real fund move is allowed only from an interactive owner terminal (a TTY). The
// autonomous heartbeat is headless — its Bash has no TTY and can't fake one — so the
// agent can never withdraw through this script. (No env override, since the model can
// set its own env vars; under GCLAW_SANDBOX the wallet is also masked, a hard backstop.)
function requireOwner() {
  if (process.stdin.isTTY) return;
  die('refused: a real withdrawal must be run from an interactive terminal (a TTY). This keeps the unattended agent from ever moving your funds.');
}

function plan(action, detail) {
  return { ok: true, dryRun: true, action, ...detail, note: 'DRY RUN — nothing moved. Re-run with --confirm to execute.' };
}

async function cmdStatus(wallet, _args, { ethers }) {
  const { arbUsdc } = await balances(wallet, ethers);
  return {
    ok: true,
    managed: wallet.managed,
    control: wallet.control,
    arbitrumUsdc: arbUsdc,
    route: ['1) hl  --amount <usd>  → USDC HyperLiquid → managed Arbitrum', '2) send --to <addr> --amount <usd> → managed Arbitrum → your wallet'],
    note: 'Your funds are always withdrawable. Check HL withdrawable via `node hl_perp.js status`.',
  };
}

async function cmdHl(wallet, args, { SDK, ethers }) {
  const amount = String(args.amount || '');
  if (!Number(amount) || Number(amount) <= 0) die('usage: hl --amount <usd> [--confirm] — amount required');
  if (!args.confirm) {
    return plan('hl-withdraw', { amount, from: 'HyperLiquid perp', to: `managed Arbitrum ${wallet.managed}` });
  }
  requireOwner();
  const { skill, creds } = await signIn(wallet, SDK, ethers);
  const out = await skill.perpWithdraw({ amount, ...creds });
  return { ok: true, action: 'hl-withdraw', amount, result: out };
}

async function cmdSend(wallet, args, { SDK, ethers }) {
  const amount = String(args.amount || '');
  const to = String(args.to || '');
  if (!ethers.isAddress(to)) die('usage: send --to <address> --amount <usd> [--confirm] — valid --to required');
  if (!Number(amount) || Number(amount) <= 0) die('amount required (USDC, > 0)');
  if (!args.confirm) return plan('send', { amount, token: 'USDC', from: `managed Arbitrum ${wallet.managed}`, to });
  requireOwner();
  const { skill, creds } = await signIn(wallet, SDK, ethers);
  const nonce = SDK.generateGdexNonce().toString();
  const out = await skill.transferToken({
    recipient: to,
    amount,
    tokenAddress: ARB_USDC,
    chainId: ARB_CHAIN,
    managed: { ...creds, userId: wallet.control, nonce },
  });
  return { ok: true, action: 'send', amount, to, result: out };
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const args = parseArgs(rest);
  const { ethers, SDK } = loadSdk();
  const wallet = loadWallet();
  const handlers = { status: cmdStatus, hl: cmdHl, send: cmdSend };
  const handler = handlers[cmd];
  if (!handler) die("unknown command. Use: status | hl --amount N | send --to ADDR --amount N (add --confirm to execute)");
  process.stdout.write(JSON.stringify(await handler(wallet, args, { SDK, ethers })) + '\n');
}

if (require.main === module) {
  main().catch((e) => die(e?.responseBody ? JSON.stringify(e.responseBody) : e.message || String(e)));
}

module.exports = { parseArgs, requireOwner };
