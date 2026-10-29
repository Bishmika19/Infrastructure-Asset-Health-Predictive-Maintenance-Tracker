import { expect, test } from '@playwright/test';
import { expectNoWcag21AaViolations } from './test_a11y';
import { loginAs, TEST_ACCOUNTS } from './test_authentication';

test('manager screens work with hardcoded data and no backend requests', async ({ page }) => {
  const backendRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/') || url.pathname === '/healthz' || url.port === '8000') {
      backendRequests.push(request.url());
    }
  });
  await loginAs(page, TEST_ACCOUNTS.manager);
  await expectNoWcag21AaViolations(page, 'Asset register');
  await page.getByPlaceholder('Filter by location').fill('North Grid');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  const row = page.locator('tr', { hasText: 'TR-001' });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'Details', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'TR-001', exact: true })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Asset detail');
  await page.getByRole('button', { name: 'View history' }).click();
  await expect(page.getByRole('heading', { name: 'History for TR-001' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Inspection logged' })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'History');
  await page.getByRole('button', { name: 'Maintenance queue', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Maintenance queue', exact: true })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Maintenance queue');
  await page.getByRole('button', { name: 'Cases', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Cases', exact: true })).toBeVisible();
  await expect(page.getByText('WO-001', { exact: true })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Cases');
  expect(backendRequests).toEqual([]);
});

test('login rejects a wrong password', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Login');
  await page.getByLabel('Username').fill('asset manager');
  await page.getByLabel('Password', { exact: true }).fill('wrong password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toHaveText('Incorrect username or password.');
  await expectNoWcag21AaViolations(page, 'Login error');
});

test('crew can sign in, open inspection and sign out', async ({ page }) => {
  await loginAs(page, TEST_ACCOUNTS.crew);
  await expect(page.getByRole('button', { name: 'Create asset' })).toHaveCount(0);
  await page.locator('tr', { hasText: 'TR-001' }).getByRole('button', { name: 'Log inspection' }).click();
  await expect(page.getByRole('heading', { name: 'Log inspection for TR-001' })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Inspection');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
});
