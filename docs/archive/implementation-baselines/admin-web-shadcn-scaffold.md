# Admin Web shadcn scaffold provenance

Validated on 2026-07-20 before migrating the existing frontend.

- pnpm runtime used for implementation: `11.9.0`
- shadcn CLI resolved from `shadcn@latest`: `4.13.1`
- command: `pnpm dlx shadcn@latest init --preset b0 --template vite --monorepo --pointer`
- staging directory: `/private/tmp/enterprise-agent-shadcn-b0-20260720/enterprise-agent-admin`
- generated project name: `enterprise-agent-admin`
- generated style: `base-nova`
- generated structure: `apps/web` plus `packages/ui`
- pointer behavior: generated global CSS applies `cursor: pointer` to enabled buttons and button roles

The CLI accepted `b0`, checked the registry, installed dependencies and completed initialization. The command was deliberately run outside the repository so it could not overwrite the current `frontend` tree. The generated skeleton is a reference input; repository adoption renames `apps/web` to `apps/admin-web` and adds the required `api-client` and `config` workspaces.
