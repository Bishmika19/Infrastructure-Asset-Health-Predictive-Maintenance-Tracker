import { expect, test, type APIRequestContext } from '@playwright/test';
import { expectNoWcag21AaViolations } from './test_a11y';
import { loginAs, TEST_ACCOUNTS } from './test_authentication';

const apiBaseUrl = 'http://127.0.0.1:8000';

interface AccessibleAsset {
  assetId: string;
  location: string;
}

async function createAccessibleAsset(request: APIRequestContext): Promise<AccessibleAsset> {
  const loginResponse = await request.post(`${apiBaseUrl}/api/v1/auth/login`, {
    data: TEST_ACCOUNTS.manager,
  });
  expect(loginResponse.ok(), 'The browser fixture manager must be able to authenticate.').toBeTruthy();

  const loginPayload = await loginResponse.json() as { accessToken: string };
  const uniqueSuffix = `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
  const asset: AccessibleAsset = {
    assetId: `A11Y-${uniqueSuffix}`,
    location: `Accessibility scan site ${uniqueSuffix}`,
  };

  const createResponse = await request.post(`${apiBaseUrl}/api/v1/assets`, {
    data: {
      assetId: asset.assetId,
      assetType: 'Transformer',
      installationDate: '2020-01-01',
      location: asset.location,
      manufacturer: 'Playwright Test Fixtures',
    },
    headers: {
      Authorization: `Bearer ${loginPayload.accessToken}`,
    },
  });
  expect(createResponse.ok(), 'The browser fixture asset must be created.').toBeTruthy();

  return asset;
}

async function filterToAsset(
  page: Parameters<typeof loginAs>[0],
  asset: AccessibleAsset,
): Promise<void> {
  await page.getByPlaceholder('Filter by location').fill(asset.location);
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.locator('tr', { hasText: asset.assetId })).toBeVisible();
}

test.describe.configure({ mode: 'serial' });

test('test_manager_screens_have_no_wcag_21_aa_violations', async ({ page, request }) => {
  const asset = await createAccessibleAsset(request);

  await page.goto('/');
  await expectNoWcag21AaViolations(page, 'Login');

  await loginAs(page, TEST_ACCOUNTS.manager);
  await filterToAsset(page, asset);
  await expectNoWcag21AaViolations(page, 'Asset register for an Asset Manager');

  const assetRow = page.locator('tr', { hasText: asset.assetId });
  await assetRow.getByRole('button', { name: 'Details' }).click();
  await expect(page.getByRole('heading', { name: asset.assetId })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Asset detail');

  await page.getByRole('button', { name: 'View history' }).click();
  await expect(page.getByRole('heading', { name: `History for ${asset.assetId}` })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Asset history');

  await page.getByRole('button', { name: 'Maintenance queue' }).click();
  await expect(page.getByRole('heading', { name: 'Maintenance queue' })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Maintenance queue');

  await page.getByRole('button', { name: 'Cases' }).click();
  await expect(page.getByRole('heading', { name: 'Cases' })).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Cases');
});

test('test_crew_screens_have_no_wcag_21_aa_violations', async ({ page, request }) => {
  const asset = await createAccessibleAsset(request);

  await loginAs(page, TEST_ACCOUNTS.crew);
  await filterToAsset(page, asset);
  await expect(page.getByRole('button', { name: 'Create asset' })).toHaveCount(0);
  await expectNoWcag21AaViolations(page, 'Asset register for Maintenance Crew');

  const assetRow = page.locator('tr', { hasText: asset.assetId });
  await assetRow.getByRole('button', { name: 'Log inspection' }).click();
  await expect(
    page.getByRole('heading', { name: `Log inspection for ${asset.assetId}` }),
  ).toBeVisible();
  await expectNoWcag21AaViolations(page, 'Inspection logging');
});
