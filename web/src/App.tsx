import { useEffect, useState } from 'react'

import { type Mode } from './lib/palette'
import NetworkView from './views/NetworkView'

/**
 * Dark mode is *selected*, not an automatic inversion: each mode has its own validated
 * steps from the same ramps. Follows the OS setting, with an explicit toggle that wins.
 */
function useMode(): [Mode, () => void] {
  const [override, setOverride] = useState<Mode | null>(null)
  const [system, setSystem] = useState<Mode>(() =>
    window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
  )

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setSystem(e.matches ? 'dark' : 'light')
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const mode = override ?? system
  return [mode, () => setOverride(mode === 'dark' ? 'light' : 'dark')]
}

export default function App() {
  const [mode, toggle] = useMode()

  useEffect(() => {
    document.documentElement.style.colorScheme = mode
    document.body.style.margin = '0'
    document.body.style.fontFamily =
      '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'
  }, [mode])

  return (
    <>
      <button
        onClick={toggle}
        aria-label={`Switch to ${mode === 'dark' ? 'light' : 'dark'} mode`}
        style={{
          position: 'fixed',
          top: 12,
          right: 14,
          zIndex: 10,
          background: 'transparent',
          border: '1px solid rgba(128,128,128,.35)',
          borderRadius: 6,
          padding: '4px 8px',
          fontSize: 12,
          cursor: 'pointer',
          color: 'inherit',
        }}
      >
        {mode === 'dark' ? '☀' : '☾'}
      </button>
      <NetworkView mode={mode} />
    </>
  )
}
