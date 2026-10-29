import { expect, type Page } from '@playwright/test';

export interface SeededAccount {
  username: string;
  password: string;
}

export const TEST_ACCOUNTS = {
  manager: {
    username: 'playwright_manager',
    password: 'PlaywrightManagerPassword-2026',
  },
  crew: {
    username: 'playwright_crew',
    password: 'PlaywrightCrewPassword-2026',
  },
} as const satisfies Record<string, SeededAccount>;

// PUBLIC_INTERFACE
/**
 * Sign in through the rendered login form and wait for the authenticated shell.
 *
 * @param page - Browser page displaying the frontend.
 * @param account - Development-only seeded account credentials.
 */
export async function loginAs(page: Page, account: SeededAccount): Promise<void> {
  await page.goto('/');
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Password').fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page.getByText(account.username, { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Infrastructure assets' })).toBeVisible();
}
