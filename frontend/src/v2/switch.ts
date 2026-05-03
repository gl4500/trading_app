export function isV2Enabled(search: string = window.location.search): boolean {
  const params = new URLSearchParams(search)
  return params.get('v') === '2'
}
