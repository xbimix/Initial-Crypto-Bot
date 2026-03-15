import type { NextConfig } from "next";

const skipBuildValidation =
  process.env.REVBOT_SKIP_NEXT_BUILD_VALIDATION === "1";
const useLocalBuildWorkaround =
  process.env.REVBOT_NEXT_LOCAL_BUILD_WORKAROUND === "1";

const nextConfig: NextConfig = {
  // check_local.ps1 runs eslint/tsc explicitly to avoid Windows spawn EPERM in Next's internal type-check step
  typescript: {
    ignoreBuildErrors: skipBuildValidation,
  },
  ...(useLocalBuildWorkaround
    ? {
        experimental: {
          // use worker threads for local check builds to avoid child-process spawn EPERM in this environment
          workerThreads: true,
          cpus: 1,
        },
      }
    : {}),
};

export default nextConfig;
