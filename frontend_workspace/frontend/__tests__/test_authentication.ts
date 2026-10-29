import { expect, type Page } from '@playwright/test';

export const TEST_ACCOUNTS = { manager: 'Asset Manager', crew: 'Maintenance Crew' } as const;

// PUBLIC_INTERFACE
export async function loginAs(page: Page, role: typeof TEST_ACCOUNTS[keyof typeof TEST_ACCOUNTS]): Promise<void> {
  /** Select a demo persona using the rendered role picker; no server or account exists. */
  await page.goto('/');
  await page.getByRole('button', { name: 'Switch demo role' }).click();
  await page.getByRole('button', { name: `Continue as ${role}` }).click();
  await expect(page.getByRole('heading', { name: 'Infrastructure assets' })).toBeVisible();
}
