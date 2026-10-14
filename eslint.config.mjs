import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    '.next/**',
    'out/**',
    'build/**',
    '.course-cache/**',
    '.four-school-course-cache/**',
    '.place-course-cache/**',
    '.python-packages/**',
    '.uv-cache/**',
    '.venv/**',
    'next-env.d.ts',
  ]),
]);

export default eslintConfig;
