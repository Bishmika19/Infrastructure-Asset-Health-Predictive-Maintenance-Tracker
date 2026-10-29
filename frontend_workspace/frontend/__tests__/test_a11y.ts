import AxeBuilder from '@axe-core/playwright';
import { expect, type Page } from '@playwright/test';

const WCAG_21_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

/**
 * Format axe findings so a failure identifies the affected screen, rule, and target elements.
 */
function formatViolations(
  violations: Array<{ id: string; help: string; nodes: Array<{ target: string[] }> }>,
): string {
  return violations
    .map((violation) => {
      const targets = violation.nodes.map((node) => node.target.join(' ')).join(', ');
      return `${violation.id}: ${violation.help} (${targets})`;
    })
    .join('\n');
}

// PUBLIC_INTERFACE
/**
 * Assert that the currently rendered screen has no WCAG 2.1 A or AA axe violations.
 *
 * @param page - Browser page already settled on the screen under test.
 * @param screenName - Human-readable screen name included in assertion output.
 */
export async function expectNoWcag21AaViolations(page: Page, screenName: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(WCAG_21_TAGS)
    .analyze();

  expect(
    formatViolations(results.violations),
    `${screenName} must not contain WCAG 2.1 A or AA axe violations.`,
  ).toBe('');
}
