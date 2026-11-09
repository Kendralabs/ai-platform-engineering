import { requireResourcePermission } from "@/lib/rbac/resource-authz";

import { createConfiguredPayloadStore } from "./payload-store-factory";
import { CredentialRetrievalService } from "./retrieval-service";

export async function getCredentialRetrievalService(): Promise<CredentialRetrievalService> {
  return new CredentialRetrievalService({
    expectedAudience: process.env.CREDENTIAL_SERVICE_AUDIENCE || "caipe-credential-service",
    payloadStore: await createConfiguredPayloadStore(),
    authorize: requireResourcePermission,
  });
}
