type Service = {
  id: string;
  name: string;
  source_repo: string | null;
  build_config: Record<string, unknown>;
};

export type ServiceGraph = {
  services: Array<{ id: string; name: string; compose_service?: string; compose_role?: string; managed_by_service_id?: string }>;
  relationships: Array<{ owner_id: string; service_id: string; relationship: "included in release" }>;
};

/** Mirrors the web canvas' persisted Compose lifecycle ownership, not application dependencies. */
export function serviceGraph(services: Service[]): ServiceGraph {
  const releaseOwnerId = services.find(service => service.source_repo !== null && typeof service.build_config.compose_service === "string")?.id;
  const graphServices = services.map(service => ({
    id: service.id,
    name: service.name,
    ...(typeof service.build_config.compose_service === "string" ? { compose_service: service.build_config.compose_service } : {}),
    ...(typeof service.build_config.compose_role === "string" ? { compose_role: service.build_config.compose_role } : {}),
    ...(typeof service.build_config.managed_by_service_id === "string" ? { managed_by_service_id: service.build_config.managed_by_service_id } : {}),
  }));
  const relationships = services.flatMap(service => {
    const explicitOwner = service.build_config.managed_by_service_id;
    const ownerId = typeof explicitOwner === "string" ? explicitOwner
      : releaseOwnerId && service.id !== releaseOwnerId && typeof service.build_config.compose_service === "string" ? releaseOwnerId : undefined;
    return ownerId && service.id !== ownerId
      ? [{ owner_id: ownerId, service_id: service.id, relationship: "included in release" as const }]
      : [];
  });
  return { services: graphServices, relationships };
}

export function formatServiceGraph(graph: ServiceGraph): string {
  const names = new Map(graph.services.map(service => [service.id, service.name]));
  const nodes = graph.services.map(service => `• ${service.name}${service.compose_role ? ` (${service.compose_role})` : ""}`).join("\n") || "(no services)";
  const edges = graph.relationships.map(edge => `• ${names.get(edge.owner_id) ?? edge.owner_id} → ${names.get(edge.service_id) ?? edge.service_id}: ${edge.relationship}`).join("\n") || "(no recorded release ownership)";
  return `Services\n${nodes}\n\nPersisted Compose release ownership\n${edges}`;
}
