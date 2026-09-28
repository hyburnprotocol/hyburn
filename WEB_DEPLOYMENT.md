# Website deployment

The public repository belongs to `hyburnprotocol`. Hosting stays in the existing
`ahnteahyeons-projects` Vercel Pro team and `hyburn` project, serving `hyburn.xyz`.
Turborepo is not required: the single Next.js app lives in `web/`.

## Production

`.github/workflows/test.yml` publishes trusted pushes to `main` only after the
contracts, website and all four mining implementations pass. Fork pull requests
run tests but never receive the production environment or deployment token.
Production jobs are serialized. Before publication, the job checks that its web
and deployment inputs still match main; newer website inputs skip the old build.
A later CLI-only commit does not suppress a pending website deployment. A web
push arriving during publication is deployed by its own subsequent successful run.

Production deployment is additionally restricted to pushes that change `web/`
or `.github/workflows/test.yml` (the website's CI/deployment configuration).
The comparison covers the complete push, including multiple commits, deletions
and moves. CLI-only, contract-only and general documentation pushes still run
CI but do not publish the website. A new branch's first push is treated as changed.

GitHub environment `production` holds a project-scoped `VERCEL_TOKEN` secret and
the `VERCEL_ORG_ID` / `VERCEL_PROJECT_ID` variables. Restrict this environment to
the `main` branch. Rotate or replace the token through the owning Vercel account;
never commit it, put it in NEXT_PUBLIC variables, or print it in build logs.

Vercel settings: Next.js, root directory `web`, Node 22.x, install `npm ci`, build
`npm run build`, default Next.js output handling. CLI commands run from repository
root so Vercel applies the `web` root exactly once. `web/vercel.json` disables
automatic Git deployments: Actions is the sole production publisher. Git repository
linking is optional for this CLI pipeline and separately requires GitHub App access.

`web/deployment.json` records public mainnet facts. `web/.env.example` is the
equivalent contributor template. Production/Preview variables on Vercel should
match these facts; production builds fail on missing or mismatched values.
`NEXT_PUBLIC_COMMIT` identifies the deployed contract source, not the latest web
commit. Do not replace it with the current GitHub Actions SHA.

The pipeline pulls production settings, builds once with `vercel build --prod`,
and publishes the same output with `vercel deploy --prebuilt --prod`. A failed
build or test leaves the previous production deployment serving traffic.

After deployment, check `/`, `/mine/`, `/whitepaper/` and the displayed Token,
Miner and Vault addresses. Use Vercel's previous successful deployment to roll
back if needed. Contract deployment and wallet signing are not part of web CI/CD.

## Preview

To review a change without assigning the production domain, use the existing
project from repository root with `vercel` (without `--prod`). Configure Preview
public variables as well. Never publish developer wallet files or a local mining
session; CLI/source deployments must originate from a clean checkout.
