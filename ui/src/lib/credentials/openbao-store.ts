import { createCredentialError } from "./errors";

export interface OpenBaoCredentialStoreOptions {
  /** Base URL of the OpenBao server, e.g. http://openbao:8200 */
  addr: string;
  /** Token used to authenticate to OpenBao (AppRole login token, or a root/dev token locally). */
  token: string;
  /** KV v2 mount point. Secrets live under `<mount>/data/<prefix>/<secretRefId>`. */
  mount?: string;
  /** Path prefix under the mount, e.g. "caipe/credentials". */
  pathPrefix?: string;
  fetchImpl?: typeof fetch;
}

interface KvV2ReadResponse {
  data?: {
    data?: Record<string, string> | null;
  };
}

function secretPath(prefix: string, secretRefId: string): string {
  return `${prefix}/${secretRefId}`;
}

function unavailable(message: string): never {
  throw createCredentialError({
    reasonCode: "credential_store_unavailable",
    message,
    status: 503,
  });
}

/**
 * CredentialStore backed by OpenBao's KV v2 secrets engine. Implements the
 * same duck-typed PayloadStore shape as MongoEnvelopeCredentialStore
 * (putSecret/getSecret/getMaskedPreview/rotateSecret/deleteSecret) so it is a
 * drop-in swap in secret-service-factory.ts / retrieval-service-factory.ts.
 *
 * OpenBao owns encryption-at-rest and key rotation for the secret material,
 * so there is no key-wrapper layer here — unlike the Mongo-envelope store,
 * which encrypts client-side before writing to Mongo.
 */
export class OpenBaoCredentialStore {
  private readonly addr: string;
  private readonly token: string;
  private readonly mount: string;
  private readonly pathPrefix: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: OpenBaoCredentialStoreOptions) {
    this.addr = options.addr.replace(/\/+$/, "");
    this.token = options.token;
    this.mount = options.mount?.replace(/^\/+|\/+$/g, "") || "secret";
    this.pathPrefix = options.pathPrefix?.replace(/^\/+|\/+$/g, "") || "caipe/credentials";
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private dataUrl(secretRefId: string): string {
    return `${this.addr}/v1/${this.mount}/data/${secretPath(this.pathPrefix, secretRefId)}`;
  }

  private async request(url: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        ...init,
        headers: {
          "X-Vault-Token": this.token,
          "Content-Type": "application/json",
          ...init.headers,
        },
      });
    } catch (error) {
      unavailable(
        `OpenBao request failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    if (response.status === 503) {
      unavailable("OpenBao is sealed or unavailable");
    }

    return response;
  }

  async putSecret(input: {
    secretRefId: string;
    plaintext: string;
    maskedPreview?: string;
  }): Promise<void> {
    const data: Record<string, string> = { plaintext: input.plaintext };
    if (input.maskedPreview !== undefined) {
      data.maskedPreview = input.maskedPreview;
    }

    const response = await this.request(this.dataUrl(input.secretRefId), {
      method: "POST",
      body: JSON.stringify({ data }),
    });

    if (!response.ok) {
      throw createCredentialError({
        reasonCode: "key_wrap_failed",
        message: `OpenBao write failed with status ${response.status}`,
        status: 500,
      });
    }
  }

  private async readData(secretRefId: string): Promise<Record<string, string>> {
    const response = await this.request(this.dataUrl(secretRefId), { method: "GET" });

    if (response.status === 404) {
      throw createCredentialError({
        reasonCode: "credential_not_found",
        message: "Credential payload was not found",
        status: 404,
      });
    }

    if (!response.ok) {
      throw createCredentialError({
        reasonCode: "decrypt_failed",
        message: `OpenBao read failed with status ${response.status}`,
        status: 500,
      });
    }

    const body = (await response.json()) as KvV2ReadResponse;
    const data = body.data?.data;
    if (!data) {
      throw createCredentialError({
        reasonCode: "credential_not_found",
        message: "Credential payload was not found",
        status: 404,
      });
    }

    return data;
  }

  async getSecret(secretRefId: string): Promise<string> {
    const data = await this.readData(secretRefId);
    if (typeof data.plaintext !== "string") {
      throw createCredentialError({
        reasonCode: "credential_not_found",
        message: "Credential payload was not found",
        status: 404,
      });
    }
    return data.plaintext;
  }

  async getMaskedPreview(secretRefId: string): Promise<string> {
    const data = await this.readData(secretRefId);
    if (typeof data.maskedPreview !== "string") {
      throw createCredentialError({
        reasonCode: "credential_preview_not_found",
        message: "Credential preview payload was not found",
        status: 404,
      });
    }
    return data.maskedPreview;
  }

  async rotateSecret(secretRefId: string): Promise<void> {
    const data = await this.readData(secretRefId);
    await this.putSecret({
      secretRefId,
      plaintext: data.plaintext,
      maskedPreview: data.maskedPreview,
    });
  }

  async deleteSecret(secretRefId: string): Promise<void> {
    const url = `${this.addr}/v1/${this.mount}/metadata/${secretPath(this.pathPrefix, secretRefId)}`;
    const response = await this.request(url, { method: "DELETE" });
    if (!response.ok && response.status !== 404) {
      throw createCredentialError({
        reasonCode: "credential_store_unavailable",
        message: `OpenBao delete failed with status ${response.status}`,
        status: 500,
      });
    }
  }
}

export function createOpenBaoCredentialStore(): OpenBaoCredentialStore {
  const addr = process.env.OPENBAO_ADDR;
  const token = process.env.OPENBAO_TOKEN;
  if (!addr || !token) {
    unavailable(
      "OPENBAO_ADDR and OPENBAO_TOKEN must be set to use the OpenBao credential store backend",
    );
  }

  return new OpenBaoCredentialStore({
    addr,
    token,
    mount: process.env.OPENBAO_KV_MOUNT || "secret",
    pathPrefix: process.env.OPENBAO_CREDENTIALS_PATH_PREFIX || "caipe/credentials",
  });
}
