import { describe, it, expect } from 'vitest'
import router from '../index'

describe('Router', () => {
  it('has all required routes', () => {
    const paths = router.getRoutes().map(r => r.path)
    expect(paths).toContain('/login')
    expect(paths).toContain('/')
    expect(paths).toContain('/files/:fileType')
    expect(paths).toContain('/files/:fileType/:id/preview')
    expect(paths).toContain('/admin/users')
  })

  it('default route is bid analysis', () => {
    const route = router.getRoutes().find(r => r.path === '/')
    expect(route).toBeDefined()
    expect(route?.name).toBe('bid-analysis')
  })
})
