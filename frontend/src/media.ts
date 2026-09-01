import { useEffect, useState } from 'react'

/** `window.matchMedia`, kept live as the viewport changes. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)

  useEffect(() => {
    const mq = window.matchMedia(query)
    const sync = () => setMatches(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [query])

  return matches
}

/**
 * Phones and tablets: there is no hover and no right-click, so anything hung off
 * a context menu needs a tap-sized way in as well.
 */
export const useTouchLayout = () => useMediaQuery('(pointer: coarse), (max-width: 640px)')
