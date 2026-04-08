import client from './client'

export const authApi = {
  login: (username: string, password: string) =>
    client.post('/auth/login', { username, password }),
  me: () => client.get('/auth/me'),' '
}
