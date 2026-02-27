# CI/CD Pipeline — GitHub Actions for the AI Doc Processor

> **Automating Test, Synth, and Deploy with Keyless AWS Authentication**
> A step-by-step guide to wiring GitHub Actions into the serverless CDK application so every pull request is validated and every merge to `main` automatically deploys to AWS.

---

## Table of Contents

- [What This Lab Covers](#what-this-lab-covers)
- [How the Pipeline Works](#how-the-pipeline-works)
- [Prerequisites](#prerequisites)
- [Part 1 — One-Time AWS Setup](#part-1--one-time-aws-setup)
- [Part 2 — CDK Bootstrap](#part-2--cdk-bootstrap)
- [Part 3 — GitHub Repository Setup](#part-3--github-repository-setup)
- [Part 4 — Understanding the Workflow File](#part-4--understanding-the-workflow-file)
- [Part 5 — Test the Pipeline End-to-End](#part-5--test-the-pipeline-end-to-end)
- [Verify & Validate](#verify--validate)
- [Troubleshooting](#troubleshooting)

---

## What This Lab Covers

Manual `cdk deploy` works on a developer's machine but breaks down on a team — different local environments, no audit trail, and no gate on broken code reaching AWS. This lab replaces that manual step with a fully automated pipeline using **GitHub Actions**.

By the end you will have:

- Pull requests automatically **tested** (pytest) and **synthesised** (CDK template validation) before merge
- Merges to `main` automatically **deployed** to the `dev` AWS environment
- AWS credentials handled via **OIDC (keyless auth)** — no IAM access keys stored anywhere

---

## How the Pipeline Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  PULL REQUEST                                                       │
│                                                                     │
│   push  ──►  test job          ──►  synth job                       │
│             (pytest)                (cdk synth — validates          │
│                                      CloudFormation templates)      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PUSH TO MAIN                                                       │
│                                                                     │
│   push  ──►  test job  ──►  deploy job                              │
│             (pytest)        (cdk deploy --all)                      │
│                              │                                      │
│                              ├─ Builds Docker image                 │
│                              ├─ Pushes to ECR                       │
│                              └─ Deploys CloudFormation stack        │
│                                 AIDocProcessorStack                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Authentication flow:**

```
GitHub Actions runner
       │
       │  presents OIDC token
       ▼
AWS STS (AssumeRoleWithWebIdentity)
       │
       │  returns short-lived credentials
       ▼
IAM Role (GitHubActionsDeployRole)
       │
       ▼
CDK deploy → ECR push → CloudFormation update
```

No AWS access keys are stored anywhere. GitHub's OIDC provider issues a short-lived token for each run.

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| AWS Account | With permissions to create IAM roles, ECR, Lambda, S3, API Gateway, CloudFormation |
| GitHub Repository | The serverless-app project pushed to a GitHub repo |
| AWS CLI | Installed and configured locally (for the one-time bootstrap step) |
| Node.js | v18 or later (for CDK CLI) |
| Python | 3.12 (matches the Lambda runtime) |

> **Confirm your repo name before starting.** You will need the exact `owner/repo-name` string (e.g. `acme-org/serverless-app`) in Step 3 of Part 1.

---

## Part 1 — One-Time AWS Setup

These steps are performed **once per AWS account**. They create the trust relationship that allows GitHub Actions to authenticate to AWS without storing any credentials.

### Step 1 — Add the GitHub OIDC Identity Provider

GitHub Actions uses OpenID Connect (OIDC) to prove its identity to AWS. AWS needs to be told to trust tokens issued by GitHub.

**Option A — AWS Console:**

1. Open the **IAM Console** → **Identity providers** (left sidebar)
2. Click **Add provider**
3. Fill in:
   - Provider type: **OpenID Connect**
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Click **Get thumbprint**
   - Audience: `sts.amazonaws.com`
4. Click **Add provider**

**Option B — AWS CLI (faster):**

```bash
# Add GitHub as a trusted OIDC identity provider
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

echo "OIDC provider created"
```

> **Note:** The thumbprint is a fixed value published by GitHub. It does not change between accounts.

---

### Step 2 — Create the GitHub Actions IAM Deploy Role

This role is assumed by GitHub Actions during every pipeline run. It needs enough permissions to run CDK (CloudFormation, ECR, Lambda, S3, IAM, API Gateway).

**Option A — AWS Console:**

1. Open **IAM → Roles → Create role**
2. Trusted entity: **Web identity**
3. Identity provider: `token.actions.githubusercontent.com`
4. Audience: `sts.amazonaws.com`
5. Click **Next**
6. Add condition (click **Add condition**):
   - Condition key: `token.actions.githubusercontent.com:sub`
   - Operator: `StringEquals`
   - Value: `repo:YOUR_GITHUB_ORG/YOUR_REPO_NAME:ref:refs/heads/main`

   > Replace `YOUR_GITHUB_ORG/YOUR_REPO_NAME` with your actual GitHub org and repository name.

7. Attach permission policy: **AdministratorAccess**

   > **Note for production:** `AdministratorAccess` is used here because CDK needs to create and manage a wide range of services. In a production environment, scope this down to only the services your stack uses.

8. Role name: `GitHubActionsDeployRole`
9. Click **Create role**
10. Open the newly created role and **copy the Role ARN** — you will need it in Part 3.

**Option B — AWS CLI:**

```bash
# Set your GitHub org and repo name
GITHUB_ORG="your-github-org"
REPO_NAME="your-repo-name"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Create the IAM role with GitHub OIDC trust policy
aws iam create-role \
  --role-name GitHubActionsDeployRole \
  --assume-role-policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {
        \"Effect\": \"Allow\",
        \"Principal\": {
          \"Federated\": \"arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com\"
        },
        \"Action\": \"sts:AssumeRoleWithWebIdentity\",
        \"Condition\": {
          \"StringEquals\": {
            \"token.actions.githubusercontent.com:aud\": \"sts.amazonaws.com\",
            \"token.actions.githubusercontent.com:sub\": \"repo:${GITHUB_ORG}/${REPO_NAME}:ref:refs/heads/main\"
          }
        }
      }
    ]
  }"

# Attach AdministratorAccess (scope down for production)
aws iam attach-role-policy \
  --role-name GitHubActionsDeployRole \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

# Print the role ARN — save this for Part 3
aws iam get-role \
  --role-name GitHubActionsDeployRole \
  --query 'Role.Arn' \
  --output text
```

**Save the Role ARN** — it looks like:
```
arn:aws:iam::123456789012:role/GitHubActionsDeployRole
```

---

### Step 3 — Verify the Trust Policy

Confirm the trust relationship is correct before moving on:

```bash
aws iam get-role \
  --role-name GitHubActionsDeployRole \
  --query 'Role.AssumeRolePolicyDocument' \
  --output json
```

You should see the `token.actions.githubusercontent.com` principal and your repo's `sub` condition in the output. If the condition shows the wrong org/repo name, the role assumption will silently fail during pipeline runs.

---

## Part 2 — CDK Bootstrap

CDK Bootstrap creates the supporting infrastructure in your AWS account that CDK needs to operate — an S3 bucket for assets, an ECR repository for staging Docker images, and a set of IAM roles for the CloudFormation deployment process.

> **This command must be run once per AWS account per region.** If you have previously run `cdk bootstrap` in this account and region, skip this step.

```bash
# Set your account and region
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION="ap-southeast-2"   # Change if you use a different region

# Bootstrap CDK
cd infra
cdk bootstrap aws://${AWS_ACCOUNT_ID}/${AWS_REGION}
```

Expected output ends with:
```
 ✅  Environment aws://123456789012/ap-southeast-2 bootstrapped.
```

**What was created (visible in CloudFormation):**

| Resource | Name | Purpose |
|----------|------|---------|
| CloudFormation Stack | `CDKToolkit` | Manages all bootstrap resources |
| S3 Bucket | `cdk-hnb659fds-assets-ACCOUNT-REGION` | Stores Lambda zips and CloudFormation templates |
| ECR Repository | `cdk-hnb659fds-container-assets-ACCOUNT-REGION` | Stages Docker images before Lambda deployment |
| IAM Roles | `cdk-*-deploy-role-*`, `cdk-*-cfn-exec-role-*` | Used by CDK during deployment |

> **Verify:** Navigate to **CloudFormation → Stacks** in the AWS Console. You should see a stack named `CDKToolkit` with status `CREATE_COMPLETE`.

---

## Part 3 — GitHub Repository Setup

GitHub Actions reads secrets from the repository's settings. Three secrets are required.

### Step 1 — Gather the values

| Secret | How to get it |
|--------|---------------|
| `AWS_ACCOUNT_ID` | Run `aws sts get-caller-identity --query Account --output text` |
| `AWS_REGION` | Your deployment region, e.g. `ap-southeast-2` |
| `AWS_DEPLOY_ROLE_ARN` | The Role ARN you saved at the end of Part 1, Step 2 |

### Step 2 — Add secrets to GitHub

1. Open your repository on GitHub
2. Go to **Settings** (top tab bar) → **Secrets and variables** (left sidebar) → **Actions**
3. Click **New repository secret** for each of the three secrets:

**Secret 1:**
- Name: `AWS_ACCOUNT_ID`
- Secret: *(your 12-digit account number)*

**Secret 2:**
- Name: `AWS_REGION`
- Secret: `ap-southeast-2`

**Secret 3:**
- Name: `AWS_DEPLOY_ROLE_ARN`
- Secret: `arn:aws:iam::123456789012:role/GitHubActionsDeployRole` *(your actual ARN)*

4. After adding all three, the **Actions secrets** page should show:

```
AWS_ACCOUNT_ID      Updated just now
AWS_DEPLOY_ROLE_ARN Updated just now
AWS_REGION          Updated just now
```

> **Tip:** Secret values are never shown after saving. If you enter a wrong value, use the **Update** button to overwrite it.

---

## Part 4 — Understanding the Workflow File

The pipeline is defined in `.github/workflows/pipeline.yml`. Let's walk through what each section does.

### Trigger

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

The workflow runs on two events:
- Any **push to `main`** (direct commit or merged PR)
- Any **pull request targeting `main`**

### Permissions

```yaml
permissions:
  id-token: write   # Allows GitHub to mint an OIDC token for this run
  contents: read    # Allows checkout of the repository
```

`id-token: write` is the critical line. Without it, GitHub will not issue the OIDC JWT that AWS needs to validate the role assumption.

### Job 1 — `test` (always runs)

```yaml
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
        cache: pip
    - run: pip install -r requirements.txt -r requirements-dev.txt
      working-directory: infra
    - run: pytest tests/ -v
      working-directory: infra
```

Runs `pytest` against `infra/tests/`. The pip cache is keyed on `requirements.txt` — unchanged dependencies are restored from cache, making subsequent runs faster.

### Job 2 — `synth` (PR only)

```yaml
synth:
  needs: test
  if: github.event_name == 'pull_request'
  steps:
    ...
    - run: cdk synth
      working-directory: infra
      env:
        CDK_DEFAULT_ACCOUNT: ${{ secrets.AWS_ACCOUNT_ID }}
        CDK_DEFAULT_REGION: ${{ secrets.AWS_REGION }}
```

`cdk synth` renders the full CloudFormation template including **building the Docker image**. If the Dockerfile has a syntax error, a missing pip package, or the CDK Python code is broken, this step fails — before anything reaches AWS. It gates all PRs so broken infrastructure code cannot be merged.

### Job 3 — `deploy` (push to main only)

```yaml
deploy:
  needs: test
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  steps:
    ...
    - uses: docker/setup-buildx-action@v3
    - run: |
        cdk deploy --all \
          --require-approval never \
          --outputs-file ../cdk-outputs.json
      working-directory: infra
      env:
        CDK_DEFAULT_ACCOUNT: ${{ secrets.AWS_ACCOUNT_ID }}
        CDK_DEFAULT_REGION: ${{ secrets.AWS_REGION }}
```

`--require-approval never` suppresses the interactive confirmation prompt (required in CI). `--outputs-file` captures stack outputs (like the API Gateway URL) to a JSON file that is then printed to the job summary for easy access.

**What CDK deploy actually does during this step:**

```
1. Synthesises the CloudFormation template
2. Builds the Docker image (from app/orchestrator/Dockerfile)
3. Authenticates to ECR (using the OIDC role)
4. Pushes the Docker image to ECR
5. Uploads CloudFormation template to the CDK assets S3 bucket
6. Calls CloudFormation CreateChangeSet / ExecuteChangeSet
7. Waits for the stack to reach UPDATE_COMPLETE
```

---

## Part 5 — Test the Pipeline End-to-End

### Test A — Pull Request (triggers `test` + `synth`)

1. **Create a feature branch:**

```bash
git checkout -b feature/test-pipeline
```

2. **Make a small visible change** (e.g. add a comment to the Lambda function):

```bash
# Open app/orchestrator/lambda_function.py and add a comment at the top
# # Pipeline test - 2026
```

3. **Commit and push:**

```bash
git add app/orchestrator/lambda_function.py
git commit -m "test: trigger CI pipeline"
git push origin feature/test-pipeline
```

4. **Open a Pull Request** on GitHub:
   - Base: `main`
   - Compare: `feature/test-pipeline`

5. **Watch the checks appear** on the PR:
   - Navigate to the **Checks** tab on the pull request
   - You should see two jobs running: `Unit Tests` and `CDK Synth (PR validation)`

6. **Expected outcome:**

```
✅ Unit Tests          — pytest passes (tests are vacuously passing currently)
✅ CDK Synth (PR validation) — CloudFormation template generated successfully
```

> **If `CDK Synth` fails:** The most common cause is missing secrets. Check that all three secrets are set correctly in **Settings → Secrets and variables → Actions**.

---

### Test B — Merge to Main (triggers `test` + `deploy`)

1. **Merge the pull request** by clicking **Merge pull request** on GitHub

   > Alternatively, push directly to main:
   > ```bash
   > git checkout main
   > git merge feature/test-pipeline
   > git push origin main
   > ```

2. **Navigate to Actions:**
   - Go to your repository → **Actions** tab
   - Click the most recent workflow run (triggered by your merge)

3. **Watch the deploy job progress** — it takes approximately 5–10 minutes because CDK builds the Docker image:

```
✅ Unit Tests
  └─ Set up Python 3.12
  └─ Install CDK dependencies
  └─ Run unit tests

⏳ Deploy to Dev
  └─ Set up Python 3.12
  └─ Install CDK dependencies
  └─ Set up Node.js
  └─ Install AWS CDK CLI
  └─ Configure AWS credentials (OIDC)    ← short-lived token minted here
  └─ Set up Docker Buildx
  └─ CDK Deploy                          ← Docker build + ECR push + CloudFormation
  └─ Show stack outputs
```

4. **Read the stack outputs** from the job summary:

   After the deploy job completes, click **Summary** (top of the job page). You will see a section like:
   ```json
   {
     "AIDocProcessorStack": {
       "ApiUrl": "https://abc123.execute-api.ap-southeast-2.amazonaws.com/prod/"
     }
   }
   ```

---

## Verify & Validate

After a successful deploy, confirm the infrastructure is live in the AWS Console.

### Check 1 — CloudFormation Stack

1. Open **CloudFormation → Stacks**
2. Find `AIDocProcessorStack`
3. Status must be `UPDATE_COMPLETE` (or `CREATE_COMPLETE` on first deploy)
4. Click **Outputs** tab — verify `ApiUrl` is present

### Check 2 — ECR Image

1. Open **ECR → Repositories**
2. Find `ai-doc-processor-repo-dev`
3. Click the repository — verify a new image was pushed with a recent timestamp

### Check 3 — Lambda Function

1. Open **Lambda → Functions**
2. Find `OrchestratorContainer-dev`
3. Click the function → **Configuration** → **General configuration**
4. Verify the image URI matches the ECR image you just pushed

### Check 4 — API Gateway

```bash
# Get the API URL from CloudFormation outputs
API_URL=$(aws cloudformation describe-stacks \
  --stack-name AIDocProcessorStack \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" \
  --output text)

echo "API URL: ${API_URL}"

# Call the /items endpoint
curl "${API_URL}items"
```

A `200 OK` response (even an empty one) confirms the full stack — API Gateway → Lambda container → response — is working end-to-end.

### Check 5 — Pipeline Run Summary

In GitHub → **Actions** → click the latest run → click **Deploy to Dev** job → scroll to the bottom. Confirm:

```
✅ CDK Deploy          exit code 0
✅ Show stack outputs  outputs printed to summary
```

---

## Troubleshooting

### `Error: Not authorized to perform: sts:AssumeRoleWithWebIdentity`

**Cause:** The OIDC condition in the IAM trust policy does not match the GitHub context.

**Fix:** Check the `sub` condition in the trust policy:

```bash
aws iam get-role \
  --role-name GitHubActionsDeployRole \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
```

The `sub` value must exactly match `repo:YOUR_ORG/YOUR_REPO:ref:refs/heads/main`. Common mistakes:
- Wrong org name or repo name (case-sensitive)
- Missing `ref:refs/heads/main` suffix
- Trailing slash

---

### `Error: Context value for 'account' and 'region' not provided`

**Cause:** `CDK_DEFAULT_ACCOUNT` or `CDK_DEFAULT_REGION` environment variables are not set, and the CDK context flags were not passed.

**Fix:** Confirm the secrets `AWS_ACCOUNT_ID` and `AWS_REGION` exist in GitHub and are correctly named. The workflow passes them as environment variables:
```yaml
env:
  CDK_DEFAULT_ACCOUNT: ${{ secrets.AWS_ACCOUNT_ID }}
  CDK_DEFAULT_REGION: ${{ secrets.AWS_REGION }}
```
If the secret name is wrong (e.g. `AWS_ACCOUNT` instead of `AWS_ACCOUNT_ID`), the variable will be empty.

---

### `Docker build failed` during `CDK Synth` or `CDK Deploy`

**Cause:** An error in `app/orchestrator/Dockerfile` or `app/orchestrator/requirements.txt`.

**Fix:** Reproduce locally:
```bash
cd app/orchestrator
docker build --build-arg MODEL_ID=test --build-arg PROMPT_BUCKET=test \
  --build-arg PROMPT_KEY=test .
```
Fix the error, commit, and push again.

---

### `CDKToolkit stack not found` or bootstrap errors

**Cause:** CDK bootstrap has not been run in the target account/region.

**Fix:** Run bootstrap locally (this is a one-time operation):
```bash
cd infra
CDK_DEFAULT_ACCOUNT=<YOUR_ACCOUNT_ID> \
CDK_DEFAULT_REGION=ap-southeast-2 \
cdk bootstrap
```

---

### `synth` job passes but `deploy` job is never triggered

**Cause:** The `deploy` job only runs on `push` events to `main`, not on pull request events.

**This is expected behaviour.** The `synth` job validates the PR. The `deploy` job only fires after the PR is merged and the resulting push to `main` is detected.

---

### Pipeline is slow (10+ minutes)

**Cause:** Docker image is being rebuilt from scratch on every run.

**Note:** CDK currently does not use Docker layer caching in GitHub Actions out of the box. Each `cdk deploy` triggers a full `docker build`. This is normal for the first implementation. Advanced optimisation (using `cache-from` in the Dockerfile and a dedicated ECR cache repo) can be added later.

---

*For questions about the application architecture itself, refer to `README.md` at the project root.*
