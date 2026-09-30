# On-Chain Spend Mandates for an AI Agent Prototype

*Claims link primary sources; UNVERIFIED marks what I could not confirm against a spec.*

## 1. Session keys / spend mandates: what the chain enforces

ERC-4337 accounts expose `validateUserOp`, returning a packed `(aggregator, validAfter, validUntil)` validity **time range** the EntryPoint enforces on-chain ([ERC-4337](https://eips.ethereum.org/EIPS/eip-4337)). That is the only spend-relevant primitive the standard enforces. Per-period limits, allowlists, and per-target caps are **not** in ERC-4337 — they are app logic in the account or a validator module.

Session keys are explicitly not standardized: "implemented wallet-by-wallet," with constraints "enforced in `validateUserOp()` by wallet-specific logic... not natively supported by ERC-4337" ([ERC-4337 docs](https://docs.erc4337.io/smart-accounts/session-keys-and-delegation.html)). A "session key with a spend cap" is a pattern; whether the cap binds depends on the validator installed.

The critical split: [ERC-7562](https://docs.erc4337.io/core-standards/erc-7562.html) validation rules are enforced **off-chain by bundlers**, not the EntryPoint. `TIMESTAMP`, `NUMBER`, `BLOCKHASH` are banned *during validation*; storage reads must be bounded and deterministic; unstaked contracts may not depend on shared mutable state. That page states: "These rules are enforced off-chain by bundlers. The EntryPoint enforces correctness on-chain, but not simulation rules like opcode bans or gas metering." A validator reading a clock during validation may pass locally and be rejected by real bundlers.

Some wallets do bind on-chain: Rhinestone's validator rejects out-of-scope calls "onchain by the account's session-key validator," warning "deleting a local key does not revoke its onchain authority" ([Rhinestone](https://docs.rhinestone.dev/wallets/session-keys/overview)) — the crispest statement of the enforced-vs-client gap.

## 2. On-chain spend accumulators

**No widely-adopted standard exists for per-window spend limits.** ERC-20 `allowance` is per-spender with no time semantics. [ERC-7579](https://eips.ethereum.org/EIPS/eip-7579) standardizes module *types* only (validation 1, execution 2, fallback 3, hooks 4) and omits spend-limit logic; a limit is your own validator or hook. `preCheck`/`postCheck` are the seam, but the spec warns malicious hooks can DoS the account by reverting.

The closest production reference is Safe's [Allowance Module](https://github.com/safe-global/safe-modules/blob/master/modules/allowances/contracts/AllowanceModule.sol): per (Safe, delegate, token) `{uint96 amount, uint96 spent, uint16 resetTimeMin, uint32 lastResetMin, uint16 nonce}`, one storage word, recurring allowances resetting lazily on read ([README](https://github.com/safe-global/safe-modules/blob/master/modules/allowances/README.md)). Treat it as a reference implementation, not a maintained standard (UNVERIFIED: deprecation status; it predates Safe's payments module).

Pitfalls, sourced:

- **Timestamp windows.** It windows on `uint32(block.timestamp / 60)`, capped ~45 days. Block timestamps are validator-influenced and unreliable for fine-grained logic ([SCWE-065](https://scs.owasp.org/SCWE/SCSVS-BLOCK/SCWE-065/)).
- **Boundary double-spend.** Lazy reset lets the full cap be spent just before and after a boundary — legal per rule, surprising per intent.
- **Overflow.** It hand-rolls `newSpent > allowance.spent && newSpent <= allowance.amount` because `uint96` addition wraps; pre-0.8.0 math is unchecked ([SC09](https://scs.owasp.org/sctop10/SC09-IntegerOverflowUnderflow/)).
- **Reentrancy.** It updates `spent` *before* transfers, which is why it is not trivially drainable; one that transfers first is ([SC08](https://scs.owasp.org/sctop10/SC08-ReentrancyAttacks/)). Unchecked calls are their own class ([SC06](https://scs.owasp.org/sctop10/SC06-UncheckedExternalCalls/)); OpenZeppelin ships `SafeERC20` because return values are inconsistent ([OZ](https://docs.openzeppelin.com/contracts/5.x/api/token/erc20#SafeERC20)).
- **Gas griefing.** [ERC-7562](https://docs.erc4337.io/core-standards/erc-7562.html) warns unstaked validation touching shared state lets one UserOp invalidate many; bundlers ban abusers. Transfers are also front-runnable once public, and unbounded `removeDelegate` loops can run out of gas.
- **Validation cost.** Limits checked during validation must be bounded; unbounded allowlist iteration is rejected.

## 3. Authorization receipts

There is **no ERC for agent authorization receipts.** Available pieces:

- **[EAS](https://docs.attest.org/)** — generic attestation registry; attestations are revocable and carry `expirationTime`. [Timestamping](https://docs.attest.org/docs/tutorials/timestamping-attestations) anchors a hash; [off-chain attestations](https://docs.attest.org/docs/easscan/offchain) are signed and anchored later. The practical receipt layer: attest `keccak256(decision ‖ policy ‖ context)`.
- **[ERC-7710](https://eips.ethereum.org/EIPS/eip-7710)** — `redeemDelegations` executes under a delegation; the spec names "Grant bounded permissions to AI agents" and notes delegations "can be revoked, expire, or become invalid."
- **[ERC-7715](https://eips.ethereum.org/EIPS/eip-7715)** — `wallet_requestExecutionPermissions` / `wallet_revokeExecutionPermission`, with typed permission and `expiry` rules.
- **[RFC 9421](https://www.rfc-editor.org/rfc/rfc9421.html)** — HTTP Message Signatures (`Signature-Input`/`Signature`, `created`/`expires`/`keyid`). Signs *requests*, not decisions.
- **Visa Trusted Agent Protocol** builds on RFC 9421 with an Agent Registry ([repo](https://github.com/visa/trusted-agent-protocol)). An industry framework, not an IETF RFC (UNVERIFIED: no formal spec doc).
- **[ERC-8004](https://eips.ethereum.org/EIPS/erc-8004)** — agent identity/reputation/validation registries; states "Payments are orthogonal to this protocol and not covered here."

## 4. Revocation / kill switch

- **Delegation/module model (ERC-7710, ERC-7579, Safe):** uninstall the module, `removeDelegate`, or disable the delegation. Effective next transaction — sub-block, no chain wait. MetaMask documents `disableDelegation` ([docs.metamask.io](https://docs.metamask.io/smart-accounts-kit/guides/delegation/disable-delegation)) (UNVERIFIED: not directly fetchable).
- **Session-key model:** revocation does not delete a leaked key; it stops validating. "Deleting a local key does not revoke its onchain authority."
- **ERC-20 allowance:** `approve(0)`, next block.

The guarantee is only "this mandate cannot be used after block N" — not "the agent stops acting," since it may hold other keys or channels.

## 5. What the blockchain does NOT solve

- **It cannot attest intent.** Receipts show what was submitted and accepted. If the policy check runs off-chain, the chain records the outcome, not the reasoning. An attested decision hash proves the receipt is unmodified — not that its policy is the one the user drew.
- **"Auditable" ≠ "enforced."** ERC-7562 makes the split explicit: opcode/storage restrictions are bundler-enforced off-chain, so they differ between bundlers.
- **Enforcement is only as good as the predicate.** "Under $50/day" fails if the asset is volatile or the agent routes through a second account, a bridge, or a fresh key. The chain sees transfers, not purposes.
- **The human-authorization link is the weak point.** Nothing on-chain proves the user drew *that* budget; only that a signature exists.

## Recommended minimal design for a prototype

Use an **enforced accumulator plus an anchored receipt**: a single dedicated spend contract, or Safe + the [Allowance Module](https://github.com/safe-global/safe-modules/blob/master/modules/allowances/README.md), holding the budget, with the spend counter incremented in the same transaction as the transfer and the period derived from `block.number` (coarser but less manipulable than `block.timestamp`). This is the only option making the budget *binding* rather than advisory, and it needs no ERC-4337 bundler, custom validator, or account deployment — removing the largest integration risks. Add one [EAS](https://docs.attest.org/) attestation per decision hashing `(policy, context, amount, txHash)`, written off-chain and anchored when needed; do not try to prove policy compliance on-chain. Enforce the cap on-chain, record reasoning off-chain, and state plainly that a receipt proves what was authorized, never that the authorization was correct. Revocation is then one `removeDelegate` call effective next block — the strongest kill switch without protocol changes.
