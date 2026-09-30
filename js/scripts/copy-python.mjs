import { cpSync, rmSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '../../python')
const dest = resolve(here, '../python')

if (!existsSync(src)) {
  console.error(`[copy-python] source engine not found at ${src}`)
  process.exit(1)
}

// What `pip install` of the bundled engine reads, and nothing else: the npm package is the JS driver, and the
// engine's examples, tests and Dockerfile are the Python package's own business.
const SHIPPED = ['pyproject.toml', 'README.md', 'LICENSE', 'NOTICE', 'AGENTS.md', 'src']
const SKIP = new Set(['__pycache__', '.pytest_cache', '.ruff_cache'])

rmSync(dest, { recursive: true, force: true })
for (const entry of SHIPPED) {
  cpSync(resolve(src, entry), resolve(dest, entry), {
    recursive: true,
    filter: (p) => !p.split(/[\\/]/).some((seg) => SKIP.has(seg) || seg.endsWith('.egg-info')),
  })
}
console.log('[copy-python] bundled python/ engine -> js/python/')
