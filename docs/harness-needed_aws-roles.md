# AWS Roles & Permissions the Harness Needs

*What the harness authenticates as, what each plugin calls, and
exact policy examples to bootstrap a new account or business —
from read-only belts to mutation-capable setups. Every example is
shareable-clean (placeholder IDs).*

---

## 1 · The authentication model

The harness supports **two credential patterns**, mixed freely per
account (config decides — see `harness_config/templates/config.yaml`):

| Pattern | How | Typical use |
|---|---|---|
| **Direct IAM user** | named profile (`~/.aws/credentials`) or key-pair per account | few accounts; the account you already have a user in |
| **Cross-account AssumeRole** | one entry credential + `role_arn` + **`role_external_id`** per target account | many accounts; least-privilege role per account |

```
# config.yaml — per account:
accounts:
  - name: member
    id: "111111111111"
    profile: sandbox                  # direct user pattern

  - name: management
    id: "222222222222"
    role_arn: "arn:aws:iam::222222222222:role/HarnessAccess"
    role_external_id: "harness-example"   # cross-account pattern
```

**Why the ExternalId matters:** any principal in *your* member
account that can call `sts:AssumeRole` would be able to use the role
without it. The ExternalId (`role_external_id` in config, sent as
`ExternalId=` on every AssumeRole) makes the confused-deputy attack
against the role impossible. Always set one.

### Attribution (CloudTrail)

The harness assumes roles with `RoleSessionName: harness-<account-id>-<ts>`
and requests **`SourceIdentity: harness-<operator>`** so every
CloudTrail event shows who drove it. Two STS permissions make
attribution richer — request them, but the harness **degrades
gracefully** without them (falls back to RoleSessionName):

```json
"Action": ["sts:TagSession", "sts:SetSourceIdentity"]
```

> ⚠️ **Reality check (learned live):** some orgs block
> `sts:TagSession`/`sts:SetSourceIdentity` org-wide via
> account-access governance that sits *above* SCP/RCP. The harness
> detects the rejection and continues with session-name attribution.
> Do not burn time fighting the org — the fallback is fine.

### Minimum for ANY pattern

```json
"Statement": [{
  "Effect": "Allow",
  "Action": "sts:GetCallerIdentity",
  "Resource": "*"
}]
```

---

## 2 · Read-only permission matrix (per plugin)

The read surface — what `harness <plugin> list/describe/audit` and
the corresponding MCP tools call. Grant the rows for the plugins you
actually use; nothing else is needed.

| Plugin | Commands | IAM actions needed |
|---|---|---|
| **core** | whoami, doctor | `sts:GetCallerIdentity` |
| **iam** | list, describe, find-unused, check-mfa, audit | `iam:ListUsers`, `iam:GetUser`, `iam:ListAccessKeys`, `iam:GetAccessKeyLastUsed`, `iam:ListMFADevices`, `iam:ListGroupsForUser`, `iam:ListAttachedUserPolicies` |
| **ec2** | list, describe, audit | `ec2:DescribeInstances`, `ec2:DescribeImages` |
| **s3** | list, info (bucket detail) | `s3:ListAllMyBuckets` + `s3:ListBucket`, `s3:GetBucketLocation`, `s3:GetBucketVersioning`, `s3:GetBucketEncryption`, `s3:GetBucketPolicy`, `s3:GetBucketAcl`, `s3:GetPublicAccessBlock` |
| **vpc** | describe, internet-gateways, nat-gateways, nacls, endpoints, flow-logs, audit | `ec2:DescribeVpcs`, `ec2:DescribeSubnets`, `ec2:DescribeInternetGateways`, `ec2:DescribeNatGateways`, `ec2:DescribeNetworkAcls`, `ec2:DescribeRouteTables`, `ec2:DescribeVpcEndpoints`, `ec2:DescribeFlowLogs` |
| **cloudfront** | list, describe | `cloudfront:ListDistributions`, `cloudfront:GetDistribution` |
| **lambda** | list, describe | `lambda:ListFunctions`, `lambda:GetFunctionConfiguration` |
| **org** | list-accounts, list-ous (mgmt account only) | `organizations:ListAccounts`, `organizations:ListRoots`, `organizations:ListOrganizationalUnitsForParent`, `organizations:DescribeAccount` |
| **cost** | total, by-service | `ce:GetCostAndUsage` (+ Cost Explorer must be **activated** in the billing account) |
| **security** | guardduty, hub | `guardduty:ListDetectors`, `guardduty:GetFindingsStatistics`, `securityhub:DescribeHub`, `securityhub:GetFindingsStatistics` (detectors/hub must exist — enablement is out of scope) |
| **backup** | list-vaults, list-plans, list-recovery-points, list-jobs | `backup:ListVaults`, `backup:DescribeBackupVault`, `backup:ListBackupPlans`, `backup:ListRecoveryPointsByBackupVault`, `backup:ListBackupJobs` |
| **inventory** | collect, summarize, show, search, export | union of the read actions of every service collected (it fans out through the other plugins' list methods) |

**Read-only done in one statement** (the lazy but correct start):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "sts:GetCallerIdentity",
      "iam:List*", "iam:Get*",
      "ec2:Describe*",
      "s3:ListAllMyBuckets", "s3:ListBucket", "s3:GetBucket*",
      "cloudfront:List*", "cloudfront:Get*",
      "lambda:List*", "lambda:Get*",
      "organizations:List*", "organizations:Describe*",
      "ce:GetCostAndUsage",
      "guardduty:List*", "guardduty:Get*",
      "securityhub:Describe*", "securityhub:Get*",
      "backup:List*", "backup:Describe*",
      "cloudtrail:LookupEvents"
    ],
    "Resource": "*"
  }]
}
```

This is intentionally read-shaped: no `Create*`, `Delete*`, `Update*`,
`Put*`, `Start*`, `Invoke*`, `Attach*`, `Detach*`, `Add*`, `Remove*`
anywhere. For tighter control, paste the specific actions from the
matrix instead of the wildcards.

---

## 3 · Mutation permissions (safe ops)

Only for accounts where mutations are allowed. Each safe op runs
`--dry-run` by default; the CLI `--yes` executes; MCP can only
simulate. `read_only: true` businesses/accounts are blocked in code
before any AWS call (`ensure_mutable`).

| Safe op | CLI | IAM actions |
|---|---|---|
| `ec2:start` / `ec2:stop` | ec2 start/stop-instances | `ec2:StartInstances`, `ec2:StopInstances` |
| `lambda:invoke` | lambda invoke | `lambda:InvokeFunction` (scoped: `"Resource": "arn:aws:lambda:*:*:function:my-fn-*"`) |
| `cloudfront:invalidate` | cloudfront invalidate | `cloudfront:CreateInvalidation` |
| `iam:rotate-keys` | iam rotate-keys | `iam:CreateAccessKey`, `iam:UpdateAccessKey`, `iam:ListAccessKeys` |
| `backup:start-backup` | backup start-backup | `backup:StartBackupJob`, `backup:GetBackupJob` |
| iam user lifecycle (seed/bootstrap helpers) | — | `iam:CreateUser`, `iam:DeleteUser`, `iam:AddUserToGroup`, `iam:RemoveUserFromGroup`, `iam:DetachUserPolicy`, `iam:DeactivateMFADevice`, `iam:DeleteLoginProfile`, `iam:CreateAccessKey`, `iam:DeleteAccessKey` |

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "HarnessSafeOps",
    "Effect": "Allow",
    "Action": [
      "ec2:StartInstances", "ec2:StopInstances",
      "iam:CreateAccessKey", "iam:UpdateAccessKey"
    ],
    "Resource": "*"
  }]
}
```

---

## 4 · Worked examples

### Example A — read-only IAM user in one account (simplest)

Use `scripts/bootstrap-readonly-user.py` (creates the user, attaches
the policy, writes the key to a 0600 file — never stdout):

```bash
python3 scripts/bootstrap-readonly-user.py \
    --profile existing-admin-profile \
    --user-name harness
```

Resulting inline policy (this is the real shape the script attaches):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "HarnessReadOnly",
    "Effect": "Allow",
    "Action": [
      "iam:List*", "iam:Get*",
      "ec2:Describe*",
      "s3:List*", "s3:GetBucket*",
      "cloudtrail:LookupEvents",
      "sts:GetCallerIdentity"
    ],
    "Resource": "*"
  }]
}
```

### Example B — cross-account role for the multi-account pattern

**In each TARGET account** (create once; the trust policy pins your
entry account + ExternalId):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "TrustHarnessEntryAccount",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::111111111111:root" },
    "Action": ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"],
    "Condition": {
      "StringEquals": { "sts:ExternalId": "harness-example" }
    }
  }]
}
```

**In your ENTRY account**, the harness's user needs to assume it:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::222222222222:role/HarnessAccess"
  }]
}
```

**In the TARGET account**, the role carries one of the permission
policies from §2/§3. Split them: read-only is the default; safe-ops
only where you accept real mutations.

### Example C — the org-view addition (management account)

The `org` plugin needs a tiny separate policy on the role in the
**management** account (members get `AccessDenied` from AWS by
design — that's correct, not a bug):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "OrgsReadOnly",
    "Effect": "Allow",
    "Action": [
      "organizations:ListAccounts",
      "organizations:ListRoots",
      "organizations:ListOrganizationalUnitsForParent"
    ],
    "Resource": "*"
  }]
}
```

### Example D — production business: the belt-and-suspenders lock

The harness enforces `read_only` in **code** (exit 2 before any AWS
call; see user-manual §8). AWS-side, make the same promise so even a
buggy future release cannot mutate:

```yaml
# config.yaml — harness-side lock
businesses:
  - name: prod-biz
    read_only: true        # code-level: mutations impossible via harness
```

```json
// AWS-side: an explicit Deny on the same role/user
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DenyAllMutations",
    "Effect": "Deny",
    "Action": [
      "*:Create*", "*:Delete*", "*:Update*", "*:Put*",
      "*:Start*", "*:Stop*", "lambda:Invoke*", "s3:*Object*"
    ],
    "Resource": "*"
  }]
}
```

Two independent locks, one intent: production is read-only no matter
which layer fails first.

---

## 5 · Org-level constraints you may meet (observed live)

| Constraint | Effect on the harness | Handling |
|---|---|---|
| **SCP pinning regions** (e.g. all regional services denied outside one region) | calls only succeed in the pinned region | configure `regions:` per account to match — the harness already fails gracefully per region |
| **RCP/SCP denying `sts:AssumeRole` from outside the org** | entry account must be **in the org** | keep the entry account inside the org, or allowlist it |
| **Org-wide blocks on `sts:TagSession`/`sts:SetSourceIdentity`** | SourceIdentity rejected | automatic fallback to RoleSessionName attribution (`harness-<account>-<ts>`); audit trail unaffected |
| **Cost Explorer not activated** | cost plugin returns CE errors | activate CE in the billing account first |
| **GuardDuty/SecurityHub not enabled** | security plugin reports no detectors/hub | enable them (out of harness scope) or expect empty results |

---

## 6 · Quick-start checklists

**New account, read-only (direct user):**
1. `python3 scripts/bootstrap-readonly-user.py --profile X --user-name harness`
2. add the account to `config.yaml` with `profile:` pointing at the new credentials
3. `harness doctor --account <name>` → green
4. `harness whoami --account <name>` → identity + attribution visible

**New account, read-only (cross-account role):**
1. in the target account: create role `HarnessAccess` with the Example B trust policy (+ your ExternalId)
2. attach the §2 read policy (and §3 safe-ops only if wanted)
3. in the entry account: grant `sts:AssumeRole` on the role ARN to the harness user
4. add to `config.yaml` with `role_arn:` + `role_external_id:`
5. `harness doctor --account <name>` → green

**Management account (org view):** additionally attach the Example C
orgs policy — `harness org list-accounts --account <name>` then shows
the live org.

---

*Related: `harness_config/templates/config.yaml` (role/ExternalId
fields) · `scripts/bootstrap-readonly-user.py` (does Example A for
you) · `scripts/seed-sandbox.py` (sandbox seeding incl. safe-op
targets) · user-manual §8 (the read_only lock) · architecture.md
(session/role assumption internals).*

---

## 7 · The bootstrap identity (operator account, not the harness)

Everything above describes what the *harness* uses: the entry user
`harness` (read-only) and role `HarnessAccess` (read-only). Neither
can create IAM — deliberately. The identity that *provisions* those
belongs to the operator and is scoped separately.

| Principal | Where | Powers |
|---|---|---|
| `harness` | member `111111111111` | read-only plugins + `sts:AssumeRole` on `HarnessAccess` |
| `HarnessAccess` (role) | each target account | `HarnessReadOnly` (+ `HarnessOrgsRead` in mgmt) |
| `harness-mgmt` | management `222222222222` | **`HarnessMgmtBootstrap` only** — IAM role lifecycle, IAM read, policy simulation, self key hygiene |

`HarnessMgmtBootstrap` (`infra/policies/harness-bootstrap-user.json`)
replaced `AdministratorAccess` + `AdministratorAccess-Amplify` +
`AccountManagementFromVercel` on 2026-11-17, applied by
`scripts/apply-mgmt-bootstrap-scope.py` (dry-run default; it refuses
to detach admin unless `iam:SimulateCustomPolicy` proves the new
policy covers all 25 bootstrap actions, then self-tests role
create/update/delete).

Restore, if that user ever needs full admin again (console or any
admin credential in the management account):

```bash
aws iam attach-user-policy --user-name harness-mgmt \
    --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

### Onboarding one more account

```bash
# in the target account, with a profile that may create roles:
python3 scripts/create-harness-role.py --profile <target-admin> --yes
# management account additionally gets the org view:
python3 scripts/create-harness-role.py --profile <target-admin> --orgs-read --yes
```

then add the account to `config.yaml` (`role_arn` +
`external_id` from `accounts.defaults`) and run
`harness account list` to persist discovery — a config entry alone is
invisible until discovery runs, because `resolve_all()` reads the
store, not the file.

### Accounts whose role does not exist yet

`333333333333` (the AWS *identity delegated admin* account of a
new-AWS org) is in `config.yaml` with
`role_arn: arn:aws:iam::333333333333:role/HarnessAccess`, but the role
could not be created: no API path reaches that account from the
current credentials (nothing trusts the management account, and
CloudFormation StackSets trusted access is not enabled on the org).
Until `create-harness-role.py` is run there, every command against it
reports:

```
Failures (1):
  333333333333 [-] AccessDenied: User: arn:aws:iam::111111111111:user/harness ...
```

Other accounts remain unaffected — the failure is per-account.
