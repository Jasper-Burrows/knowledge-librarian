import { expect, test } from '@playwright/test'

test('desktop offline answer is cited and source is inspectable', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium')
  await page.goto('/')
  await expect(page.getByText('Offline demo')).toBeVisible()
  await expect(page.getByText('Customer Incident Playbook')).toBeVisible()
  await page.getByRole('button', { name: 'What is the Sev-1 response process?' }).click()
  await expect(page.getByText('Citation check passed')).toBeVisible()
  await page.getByRole('button', { name: /Customer Incident Playbook/ }).first().click()
  await expect(page.getByText('Selected source')).toBeVisible()
  await expect(
    page.getByRole('complementary', { name: 'Source library' })
      .getByText(/A severity-one incident is a complete production outage/),
  ).toBeVisible()
  await page.screenshot({ path: 'public/screenshots/knowledge-librarian-offline.png', fullPage: true })
  await page.screenshot({ path: testInfo.outputPath('offline-grounded-answer.png'), fullPage: true })
})

test('mobile workspace starts focused and can open the source drawer', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-chromium')
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Ask the Librarian' })).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Source library' })).toBeHidden()
  await page.getByRole('button', { name: 'Show source panel' }).click()
  await expect(page.getByRole('complementary', { name: 'Source library' })).toBeVisible()
  await page.getByRole('button', { name: 'Close source panel' }).click()
  await expect(page.getByRole('textbox', { name: 'Question' })).toBeVisible()
})
