import type { NextConfig } from "next";
import { dirname } from "path";
import { fileURLToPath } from "url";

// Silences a spurious "detected multiple lockfiles" warning caused by an
// unrelated package-lock.json in the user's home directory — explicitly
// declaring this project's own root avoids Next.js guessing wrong.
const __dirname = dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
