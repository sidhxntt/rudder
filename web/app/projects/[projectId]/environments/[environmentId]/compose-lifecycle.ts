type ComposeService = {
  id: string;
  source_repo: string | null;
  build_config: Record<string, unknown>;
};

/**
 * Imported Compose releases are owned by the one source-backed app service.
 * Generated database/cache records are created before that app, so insertion
 * order is not a reliable way to find the shared deployment.
 */
export function composeReleaseOwnerId(services: ComposeService[]): string | undefined {
  return services.find(
    (service) =>
      service.source_repo !== null &&
      typeof service.build_config.compose_service === "string",
  )?.id;
}

export function composeManagedByServiceId(
  service: ComposeService,
  releaseOwnerId: string | undefined,
): string | undefined {
  const explicitOwner = service.build_config.managed_by_service_id;
  if (typeof explicitOwner === "string") return explicitOwner;
  if (
    releaseOwnerId &&
    service.id !== releaseOwnerId &&
    typeof service.build_config.compose_service === "string"
  ) {
    return releaseOwnerId;
  }
  return undefined;
}
