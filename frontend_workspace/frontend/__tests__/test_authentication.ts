import { expect, type Page } from '@playwright/test';

export const TEST_ACCOUNTS = {
  manager: { username: 'asset manager', password: 'asset manager' },
  crew: { username: 'maintenance crew', password: 'maintenance crew' },
} as const;

// PUBLIC_INTERFACE
export async function loginAs(page: Page, account: typeof TEST_ACCOUNTS[keyof typeof TEST_ACCOUNTS]): Promise<void> {
  /** Sign in through the rendered login form with the given username and password. */
  await page.goto('/');
  await page.getByLabel('Username').fill(account.username);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Infrastructure assets' })).toBeVisible();
}
