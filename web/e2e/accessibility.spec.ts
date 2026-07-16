import AxeBuilder from '@axe-core/playwright'
import { expect, Page, test } from '@playwright/test'


async function expectAccessible(page: Page, surface: string) {
  const results = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze()
  const details = results.violations.map(violation => ({
    id: violation.id,
    impact: violation.impact,
    nodes: violation.nodes.map(node => node.target),
  }))
  expect(details, `${surface} accessibility violations`).toEqual([])
}


test('admin workspaces have no WCAG A or AA axe violations',async({page})=>{
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'English Class'})).toBeVisible()
  await expectAccessible(page,'sign in')
  await page.getByLabel('Username').fill('pytest_admin')
  await page.getByLabel('Password').fill('admin-pass')
  await page.getByRole('button',{name:'Sign in'}).click()

  const workspaces = [
    ['Home','HR home'],
    ['Learners','Learners'],
    ['Attendance','Attendance'],
    ['Final results','Final results'],
    ['Monthly review','Monthly review'],
    ['Follow-ups','Follow-ups'],
    ['Classes & schedule','Classes and schedule'],
    ['Reports','Reports'],
  ] as const
  for(const [navigation,heading] of workspaces){
    await page.getByRole('button',{name:navigation,exact:true}).click()
    await expect(page.getByRole('heading',{name:heading,exact:true})).toBeVisible()
    await expectAccessible(page,navigation)
  }
})


test('viewer report surface remains accessible and hides HR navigation',async({page})=>{
  await page.goto('/')
  await page.getByLabel('Username').fill('pytest_viewer')
  await page.getByLabel('Password').fill('viewer-pass')
  await page.getByRole('button',{name:'Sign in'}).click()
  await page.getByRole('button',{name:'Reports'}).click()
  await expect(page.getByLabel('Registered report')).toBeVisible()
  await expect(page.getByRole('button',{name:'Learners'})).toHaveCount(0)
  await expectAccessible(page,'viewer reports')
})
