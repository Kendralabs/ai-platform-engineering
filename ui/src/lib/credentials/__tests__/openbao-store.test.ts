import {
  createOpenBaoCredentialStore,
  OpenBaoCredentialStore,
} from "@/lib/credentials/openbao-store";

class FakeResponse {
  constructor(
    private readonly body: unknown,
    readonly status: number,
  ) {}

  get ok(): boolean {
    return this.status >= 200 && this.status < 300;
  }

  async json(): Promise<unknown> {
    return this.body;
  }
}

class FakeOpenBao {
  readonly secrets = new Map<string, Record<string, string>>();

  fetch: typeof fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const path = url.split("/v1/")[1];

    if (path.startsWith("secret/data/")) {
      const secretRefId = path.slice("secret/data/".length);

      if (method === "POST") {
        const body = JSON.parse(String(init?.body)) as { data: Record<string, string> };
        this.secrets.set(secretRefId, body.data);
        return new FakeResponse({}, 200) as unknown as Response;
      }

      if (method === "GET") {
        const data = this.secrets.get(secretRefId);
        if (!data) {
          return new FakeResponse({}, 404) as unknown as Response;
        }
        return new FakeResponse({ data: { data } }, 200) as unknown as Response;
      }
    }

    if (path.startsWith("secret/metadata/") && method === "DELETE") {
      const secretRefId = path.slice("secret/metadata/".length);
      this.secrets.delete(secretRefId);
      return new FakeResponse(null, 204) as unknown as Response;
    }

    return new FakeResponse({}, 404) as unknown as Response;
  }) as typeof fetch;
}

describe("OpenBaoCredentialStore", () => {
  it("writes, reads, rotates, and deletes credential payloads via KV v2", async () => {
    const bao = new FakeOpenBao();
    const store = new OpenBaoCredentialStore({
      addr: "http://openbao:8200",
      token: "test-token",
      fetchImpl: bao.fetch,
    });

    await store.putSecret({
      secretRefId: "azure-power-ops/arm-client-secret",
      plaintext: "super-secret-value",
      maskedPreview: "supe...alue",
    });

    await expect(store.getSecret("azure-power-ops/arm-client-secret")).resolves.toBe(
      "super-secret-value",
    );
    await expect(store.getMaskedPreview("azure-power-ops/arm-client-secret")).resolves.toBe(
      "supe...alue",
    );

    await store.rotateSecret("azure-power-ops/arm-client-secret");
    await expect(store.getSecret("azure-power-ops/arm-client-secret")).resolves.toBe(
      "super-secret-value",
    );

    await store.deleteSecret("azure-power-ops/arm-client-secret");
    await expect(store.getSecret("azure-power-ops/arm-client-secret")).rejects.toMatchObject({
      reasonCode: "credential_not_found",
      status: 404,
    });
  });

  it("raises credential_not_found when reading a secret that was never written", async () => {
    const bao = new FakeOpenBao();
    const store = new OpenBaoCredentialStore({
      addr: "http://openbao:8200",
      token: "test-token",
      fetchImpl: bao.fetch,
    });

    await expect(store.getSecret("does-not-exist")).rejects.toMatchObject({
      reasonCode: "credential_not_found",
      status: 404,
    });
    await expect(store.getMaskedPreview("does-not-exist")).rejects.toMatchObject({
      reasonCode: "credential_not_found",
      status: 404,
    });
  });

  it("raises credential_preview_not_found when a secret has no masked preview", async () => {
    const bao = new FakeOpenBao();
    const store = new OpenBaoCredentialStore({
      addr: "http://openbao:8200",
      token: "test-token",
      fetchImpl: bao.fetch,
    });

    await store.putSecret({ secretRefId: "secret-1", plaintext: "value-only" });

    await expect(store.getMaskedPreview("secret-1")).rejects.toMatchObject({
      reasonCode: "credential_preview_not_found",
      status: 404,
    });
  });

  it("fails closed with credential_store_unavailable when OpenBao is sealed", async () => {
    const sealedFetch: typeof fetch = (async () =>
      new FakeResponse({ errors: ["Vault is sealed"] }, 503) as unknown as Response) as typeof fetch;
    const store = new OpenBaoCredentialStore({
      addr: "http://openbao:8200",
      token: "test-token",
      fetchImpl: sealedFetch,
    });

    await expect(store.getSecret("secret-1")).rejects.toMatchObject({
      reasonCode: "credential_store_unavailable",
      status: 503,
    });
  });

  it("fails closed with credential_store_unavailable when the network request itself fails", async () => {
    const throwingFetch: typeof fetch = (async () => {
      throw new Error("ECONNREFUSED");
    }) as typeof fetch;
    const store = new OpenBaoCredentialStore({
      addr: "http://openbao:8200",
      token: "test-token",
      fetchImpl: throwingFetch,
    });

    await expect(store.getSecret("secret-1")).rejects.toMatchObject({
      reasonCode: "credential_store_unavailable",
      status: 503,
    });
  });

  it("respects a custom KV mount and path prefix when building request URLs", async () => {
    const requestedUrls: string[] = [];
    const recordingFetch: typeof fetch = (async (input: RequestInfo | URL) => {
      requestedUrls.push(typeof input === "string" ? input : input.toString());
      return new FakeResponse({}, 404) as unknown as Response;
    }) as typeof fetch;
    const store = new OpenBaoCredentialStore({
      addr: "http://openbao:8200/",
      token: "test-token",
      mount: "/caipe/",
      pathPrefix: "/custom/prefix/",
      fetchImpl: recordingFetch,
    });

    await expect(store.getSecret("secret-1")).rejects.toMatchObject({
      reasonCode: "credential_not_found",
    });
    expect(requestedUrls).toEqual([
      "http://openbao:8200/v1/caipe/data/custom/prefix/secret-1",
    ]);
  });
});

describe("createOpenBaoCredentialStore", () => {
  const ENV_KEYS = [
    "OPENBAO_ADDR",
    "OPENBAO_TOKEN",
    "OPENBAO_KV_MOUNT",
    "OPENBAO_CREDENTIALS_PATH_PREFIX",
  ] as const;
  const previous: Partial<Record<(typeof ENV_KEYS)[number], string>> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      previous[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (previous[key] === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = previous[key];
      }
    }
  });

  it("throws credential_store_unavailable when OPENBAO_ADDR/OPENBAO_TOKEN are not configured", () => {
    expect(() => createOpenBaoCredentialStore()).toThrow(
      "OPENBAO_ADDR and OPENBAO_TOKEN must be set to use the OpenBao credential store backend",
    );
  });

  it("builds a store from environment variables when configured", () => {
    process.env.OPENBAO_ADDR = "http://openbao:8200";
    process.env.OPENBAO_TOKEN = "env-token";

    expect(() => createOpenBaoCredentialStore()).not.toThrow();
  });
});
