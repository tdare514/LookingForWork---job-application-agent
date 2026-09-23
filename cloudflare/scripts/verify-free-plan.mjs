const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;

if (
  !accountId ||
  !token ||
  process.env.FREE_TIER_ENABLED !== "true" ||
  process.env.ACCOUNT_PLAN !== "free"
) {
  console.error(
    "Free-plan check refused: set account credentials and explicitly set " +
      'FREE_TIER_ENABLED="true" and ACCOUNT_PLAN="free".',
  );
  process.exit(1);
}

const response = await fetch(
  `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}`,
  {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  },
);

if (!response.ok) {
  if (response.status === 401 || response.status === 403) {
    console.error(
      `Free-plan check refused: the token cannot read account metadata (HTTP ${response.status}). ` +
        "Create a token with Account > Read permission.",
    );
  } else {
    console.error(`Free-plan check refused: Cloudflare returned HTTP ${response.status}.`);
  }
  process.exit(1);
}

const payload = await response.json();
if (payload?.success !== true || !payload?.result?.id) {
  console.error(
    "Free-plan check refused: Cloudflare did not confirm access to this account.",
  );
  process.exit(1);
}

console.log(`Cloudflare account ${accountId} is accessible and explicitly configured as free.`);
