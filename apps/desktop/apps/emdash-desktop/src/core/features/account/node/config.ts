export const ACCOUNT_CONFIG = {
  authServer: {
    // The inherited hosted account service is intentionally disabled. Hardcore
    // connects GitHub through the local CLI or GitHub's device flow instead.
    baseUrl: 'http://127.0.0.1:9',
    authTimeoutMs: Number(process.env.EMDASH_AUTH_TIMEOUT_MS || 300000),
  },
};
