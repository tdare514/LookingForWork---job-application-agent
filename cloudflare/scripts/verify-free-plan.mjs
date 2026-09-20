const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;

if (!accountId || !token) {
  console.error(
    "Free-plan check refused: set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN.",
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
  console.error(`Free-plan check refused: Cloudflare returned HTTP ${response.status}.`);
  process.exit(1);
}

const payload = await response.json();
const planId = payload?.result?.plan?.id;
if (planId !== "free") {
  console.error(
    `Free-plan check refused: account plan is ${planId ?? "unknown"}; only plan id "free" is allowed.`,
  );
  process.exit(1);
}

console.log(`Cloudflare account ${accountId} is on the free plan.`);
