import { expect, test } from '@playwright/test'

test('admin completes the read-only learner journey without a full page reload', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('pytest_admin')
  await page.getByLabel('Password').fill('admin-pass')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByRole('heading', { name: 'HR home' })).toBeVisible()
  await page.getByRole('button', { name: 'Learners' }).click()
  await page.getByLabel('Search by employee code or name').fill('Directory Alpha')
  await page.getByRole('button', { name: 'Search' }).click()
  await page.getByRole('button', { name: /Directory Alpha/ }).click()

  await expect(page.getByRole('heading', { name: 'Directory Alpha' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Course history' })).toBeVisible()
  await expect(page.getByText('learner.onboard')).toBeVisible()
  await page.getByRole('button', { name: 'Edit profile' }).click()
  await page.getByLabel('Full name').fill('Directory Alpha Updated')
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByRole('heading', { name: 'Directory Alpha Updated' })).toBeVisible()
  await expect(page.getByText('Profile saved.')).toBeVisible()
  await expect(page.getByText('employee.upsert')).toBeVisible()
})

test('viewer sees the approved summary but no HR learner navigation', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('pytest_viewer')
  await page.getByLabel('Password').fill('viewer-pass')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.getByRole('heading', { name: 'Workspace summary' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Learners' })).toHaveCount(0)
})
