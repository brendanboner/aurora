#!/usr/bin/env bash
# =============================================================================
# Aurora - GitHub Actions OIDC Setup
# =============================================================================
# One-time setup: creates an AWS IAM OIDC provider and deploy role so
# GitHub Actions can push to ECR without any stored credentials.
#
# Requirements:
#   - AWS CLI with AdministratorAccess (or IAM write permissions)
#   - gh CLI authenticated to GitHub
#   - jq
#
# Usage:
#   ./scripts/setup-oidc.sh                              # uses default profile
#   AWS_PROFILE=AdministratorAccess ./scripts/setup-oidc.sh
#   make setup-oidc
# =============================================================================

set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

log()  { echo -e "${CYAN}→ $*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠  $*${NC}"; }
fail() { echo -e "${RED}✗ $*${NC}"; exit 1; }

# ─── Config ──────────────────────────────────────────────────────────────────
REPO=$(git remote get-url origin | sed 's|.*github.com/||' | sed 's|\.git||')
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=${AWS_REGION:-us-east-1}
ROLE_NAME="aurora-github-actions-deploy"
POLICY_NAME="aurora-ecr-push"
OIDC_URL="https://token.actions.githubusercontent.com"
OIDC_PROVIDER="token.actions.githubusercontent.com"

echo ""
echo -e "${CYAN}Aurora GitHub Actions OIDC Setup${NC}"
echo "  Repo:    $REPO"
echo "  Account: $ACCOUNT_ID"
echo "  Region:  $REGION"
echo "  Role:    $ROLE_NAME"
echo ""

# ─── 1. OIDC Provider ────────────────────────────────────────────────────────
log "Checking for existing OIDC provider..."
EXISTING=$(aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?ends_with(Arn,'/$OIDC_PROVIDER')].Arn" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING" ]; then
  ok "OIDC provider already exists: $EXISTING"
  PROVIDER_ARN="$EXISTING"
else
  log "Creating OIDC provider for token.actions.githubusercontent.com..."
  PROVIDER_ARN=$(aws iam create-open-id-connect-provider \
    --url "$OIDC_URL" \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 1c58a3a8518e8759bf075b76b750d4f2df264fcd \
    --query OpenIDConnectProviderArn \
    --output text)
  ok "Created OIDC provider: $PROVIDER_ARN"
fi

# ─── 2. Trust policy ─────────────────────────────────────────────────────────
log "Building trust policy (scoped to repo: $REPO, branch: main)..."
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "$PROVIDER_ARN"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${REPO}:ref:refs/heads/main"
        }
      }
    }
  ]
}
EOF
)

# ─── 3. IAM Role ─────────────────────────────────────────────────────────────
EXISTING_ROLE=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_ROLE" ]; then
  ok "Role already exists: $EXISTING_ROLE"
  ROLE_ARN="$EXISTING_ROLE"
  log "Updating trust policy on existing role..."
  aws iam update-assume-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-document "$TRUST_POLICY"
  ok "Trust policy updated"
else
  log "Creating IAM role: $ROLE_NAME..."
  ROLE_ARN=$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Assumed by GitHub Actions for Aurora ECR push (repo: $REPO)" \
    --query 'Role.Arn' \
    --output text)
  ok "Created role: $ROLE_ARN"
fi

# ─── 4. ECR push policy ──────────────────────────────────────────────────────
log "Creating ECR push policy..."
ECR_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "ECRPush",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "arn:aws:ecr:${REGION}:${ACCOUNT_ID}:repository/aurora-*"
    }
  ]
}
EOF
)

# Create or update the inline policy
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "$ECR_POLICY"
ok "ECR push policy attached to role"

# ─── 5. Push role ARN to GitHub Actions secrets ──────────────────────────────
log "Pushing AWS_ROLE_ARN to GitHub Actions secrets..."
if command -v gh &>/dev/null; then
  echo "$ROLE_ARN" | gh secret set AWS_ROLE_ARN --repo "$REPO"
  ok "Secret set: AWS_ROLE_ARN = $ROLE_ARN"
else
  warn "gh CLI not found — set this secret manually in GitHub:"
  echo "  Secret name:  AWS_ROLE_ARN"
  echo "  Secret value: $ROLE_ARN"
fi

# ─── Done ────────────────────────────────────────────────────────────────────
echo ""
ok "OIDC setup complete!"
echo ""
echo "  Role ARN:  $ROLE_ARN"
echo "  Scoped to: $REPO (main branch only)"
echo ""
echo "GitHub Actions will now authenticate automatically on every push to main."
echo "No credentials stored, no rotation needed."
