export function routeToDocId(rawPath: string | string[] | undefined): string {
  if (Array.isArray(rawPath)) return rawPath.join('/')
  return rawPath ?? ''
}
