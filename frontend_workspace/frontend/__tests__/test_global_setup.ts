import { execFileSync } from 'node:child_process';
import { env } from 'node:process';

const backendRoot = '../../backend_workspace/backend';

const seededAccountEnvironment = {
  ...env,
  SEED_MANAGER_USERNAME: 'playwright_manager',
  SEED_MANAGER_PASSWORD: 'PlaywrightManagerPassword-2026',
  SEED_CREW_USERNAME: 'playwright_crew',
  SEED_CREW_PASSWORD: 'PlaywrightCrewPassword-2026',
  SMTP_HOST: '',
  SMTP_TO: '',
};

/** Apply migrations and provision deterministic development-only accounts for browser tests. */
function prepareBrowserTestData(): void {
  execFileSync('python', ['-m', 'alembic', 'upgrade', 'head'], {
    cwd: backendRoot,
    env: seededAccountEnvironment,
    stdio: 'inherit',
  });
  execFileSync('python', ['-m', 'scripts.seed_dev_users'], {
    cwd: backendRoot,
    env: seededAccountEnvironment,
    stdio: 'inherit',
  });
}

export default prepareBrowserTestData;
