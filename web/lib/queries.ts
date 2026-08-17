"use client";

/**
 * TanStack Query bindings over `lib/api.ts`. Components call these; they never
 * call the API module directly and never call `fetch` at all (PRD → Stack:
 * "State — TanStack Query").
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "./api";
import type {
  AutoscalingOperationRequest,
  Deployment,
  ResourceOperationRequest,
  ServiceUpdate,
} from "./types";

export const keys = {
  githubImportStatus: ["github-import-status"] as const,
  githubImportTemplates: ["github-import-templates"] as const,
  githubInstallations: ["github-installations"] as const,
  githubRepositories: (installationId: number) => ["github-repositories", installationId] as const,
  githubBranches: (installationId: number, repository: string) =>
    ["github-branches", installationId, repository] as const,
  githubPreview: (installationId: number, repository: string, branch: string, templateId: string) =>
    ["github-preview", installationId, repository, branch, templateId] as const,
  githubImport: (importId: string) => ["github-import", importId] as const,
  nodes: ["nodes"] as const,
  projects: ["projects"] as const,
  environments: (projectId: string) => ["environments", projectId] as const,
  services: (environmentId: string) => ["services", environmentId] as const,
  domains: (environmentId: string) => ["domains", environmentId] as const,
  deployments: (serviceId: string) => ["deployments", serviceId] as const,
  instances: (serviceId: string) => ["instances", serviceId] as const,
  metrics: (serviceId: string) => ["metrics", serviceId] as const,
  variables: (serviceId: string) => ["variables", serviceId] as const,
  operations: (serviceId: string) => ["service-operations", serviceId] as const,
};

export function useGitHubImportStatus() {
  return useQuery({ queryKey: keys.githubImportStatus, queryFn: api.getGitHubImportStatus });
}

export function useGitHubImportTemplates() {
  return useQuery({ queryKey: keys.githubImportTemplates, queryFn: api.listGitHubImportTemplates });
}

export function useGitHubInstallations(enabled: boolean) {
  return useQuery({
    queryKey: keys.githubInstallations,
    queryFn: api.listGitHubInstallations,
    enabled,
  });
}

export function useGitHubRepositories(installationId: number | null) {
  return useQuery({
    queryKey: keys.githubRepositories(installationId ?? 0),
    queryFn: () => api.listGitHubRepositories(installationId ?? 0),
    enabled: installationId !== null,
  });
}

export function useGitHubBranches(installationId: number | null, repository: string | null) {
  return useQuery({
    queryKey: keys.githubBranches(installationId ?? 0, repository ?? ""),
    queryFn: () => api.listGitHubBranches(installationId ?? 0, repository ?? ""),
    enabled: installationId !== null && repository !== null,
  });
}

export function useGitHubImportPreview(
  installationId: number | null,
  repository: string | null,
  branch: string | null,
  templateId: string | null,
) {
  return useQuery({
    queryKey: keys.githubPreview(installationId ?? 0, repository ?? "", branch ?? "", templateId ?? ""),
    queryFn: () =>
      api.previewGitHubImport({
        installationId: installationId ?? 0,
        repository: repository ?? "",
        branch: branch ?? "",
        templateId,
      }),
    enabled: installationId !== null && repository !== null && branch !== null,
  });
}

export function useConfirmGitHubImport() {
  return useMutation({ mutationFn: api.confirmGitHubImport });
}

export function useGitHubImport(importId: string | null) {
  return useQuery({
    queryKey: keys.githubImport(importId ?? ""),
    queryFn: () => api.getGitHubImport(importId ?? ""),
    enabled: importId !== null,
    refetchInterval: LIVE_POLL_MS,
  });
}

/** Slow enough not to hammer the control plane, fast enough to watch a deploy. */
const LIVE_POLL_MS = 2_000;

export function useProjects() {
  // CLI and web mutations share the same control plane. Polling keeps the
  // project inventory current when an operator works in a terminal elsewhere.
  return useQuery({ queryKey: keys.projects, queryFn: api.listProjects, refetchInterval: LIVE_POLL_MS });
}

export function useUpdateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { projectId: string; name: string }) => api.updateProject(args.projectId, { name: args.name }),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useDeleteProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => api.deleteProject(projectId),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useEnvironments(projectId: string | undefined) {
  return useQuery({
    queryKey: keys.environments(projectId ?? ""),
    queryFn: () => api.listEnvironments(projectId ?? ""),
    enabled: Boolean(projectId),
  });
}

export function useCloneEnvironment(projectId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { environmentId: string; name: string }) =>
      api.cloneEnvironment(args.environmentId, args.name),
    onSuccess: () => {
      if (projectId) void client.invalidateQueries({ queryKey: keys.environments(projectId) });
    },
  });
}

export function useDeleteEnvironment(projectId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (environmentId: string) => api.deleteEnvironment(environmentId),
    onSuccess: () => {
      if (projectId) void client.invalidateQueries({ queryKey: keys.environments(projectId) });
    },
  });
}

export function useServices(environmentId: string | undefined) {
  return useQuery({
    queryKey: keys.services(environmentId ?? ""),
    queryFn: () => api.listServices(environmentId ?? ""),
    enabled: Boolean(environmentId),
  });
}

export function useDomains(environmentId: string | undefined) {
  return useQuery({
    queryKey: keys.domains(environmentId ?? ""),
    queryFn: () => api.listDomains(environmentId ?? ""),
    enabled: Boolean(environmentId),
  });
}

export function useDeployments(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.deployments(serviceId ?? ""),
    queryFn: () => api.listDeployments(serviceId ?? ""),
    enabled: Boolean(serviceId),
    refetchInterval: LIVE_POLL_MS,
  });
}

export function useInstances(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.instances(serviceId ?? ""),
    queryFn: () => api.listInstances(serviceId ?? ""),
    enabled: Boolean(serviceId),
    refetchInterval: LIVE_POLL_MS,
  });
}

export function useServiceMetrics(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.metrics(serviceId ?? ""),
    queryFn: () => api.listServiceMetrics(serviceId ?? ""),
    enabled: Boolean(serviceId),
    refetchInterval: LIVE_POLL_MS,
  });
}

export function useVariables(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.variables(serviceId ?? ""),
    queryFn: () => api.listVariables(serviceId ?? ""),
    enabled: Boolean(serviceId),
  });
}

export function useNodes() {
  return useQuery({
    queryKey: keys.nodes,
    queryFn: api.listNodes,
    refetchInterval: LIVE_POLL_MS,
  });
}

/** Desired/observed Kubernetes operation state, refreshed while a release applies. */
export function useServiceOperations(serviceId: string | undefined) {
  return useQuery({
    queryKey: keys.operations(serviceId ?? ""),
    queryFn: () => api.getServiceOperations(serviceId ?? ""),
    enabled: Boolean(serviceId),
    refetchInterval: LIVE_POLL_MS,
  });
}

/** Compare-and-swap replacement for advanced desired-state editors. */
export function useUpdateServiceOperations(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { changes: Record<string, unknown>; etag: string }) =>
      api.updateServiceOperations(serviceId ?? "", args.changes, args.etag),
    onSuccess: () => {
      if (serviceId) void client.invalidateQueries({ queryKey: keys.operations(serviceId) });
    },
  });
}

function useOperationMutation<T>(
  serviceId: string | undefined,
  operation: (serviceId: string, payload: T) => Promise<unknown>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: T) => operation(serviceId ?? "", payload),
    onSuccess: () => {
      if (serviceId) void client.invalidateQueries({ queryKey: keys.operations(serviceId) });
    },
  });
}

export function useScaleOperation(serviceId: string | undefined) {
  return useOperationMutation(serviceId, (id, replicas: number) => api.requestScale(id, replicas));
}

export function useResourcesOperation(serviceId: string | undefined) {
  return useOperationMutation(serviceId, (id, payload: ResourceOperationRequest) => api.requestResources(id, payload));
}

export function useAutoscalingOperation(serviceId: string | undefined) {
  return useOperationMutation(serviceId, (id, payload: AutoscalingOperationRequest) => api.requestAutoscaling(id, payload));
}

export function usePlacementOperation(serviceId: string | undefined) {
  return useOperationMutation(
    serviceId,
    (id, payload: {
      node_selector: Record<string, string>;
      topology_spread: boolean;
      anti_affinity: boolean;
      max_unavailable?: number;
    }) =>
      api.requestPlacement(id, payload),
  );
}

export function useRolloutOperation(serviceId: string | undefined) {
  return useOperationMutation(
    serviceId,
    (id, payload: { strategy: "rolling" | "blue_green" | "canary"; canary_steps?: number[] }) =>
      api.requestRollout(id, payload),
  );
}

export function useOperationRollback(serviceId: string | undefined) {
  return useOperationMutation(serviceId, (id, deploymentId: string) => api.requestOperationRollback(id, deploymentId));
}

export function useBackupOperation(serviceId: string | undefined) {
  return useOperationMutation(serviceId, (id, retentionDays: number) => api.requestBackup(id, retentionDays));
}

export function useReadReplicasOperation(serviceId: string | undefined) {
  return useOperationMutation(serviceId, (id, replicas: number) => api.requestReadReplicas(id, replicas));
}

export function useStorageOperation(serviceId: string | undefined) {
  return useOperationMutation(
    serviceId,
    (id, payload: { currentSizeMb: number; requestedSizeMb: number }) =>
      api.requestStorage(id, payload.currentSizeMb, payload.requestedSizeMb),
  );
}

export function useScheduleOperation(serviceId: string | undefined) {
  return useOperationMutation(
    serviceId,
    (id, payload: { cron: string; command: string[]; timeout_seconds?: number; retries?: number }) =>
      api.requestSchedule(id, payload),
  );
}

export function useJobOperation(serviceId: string | undefined) {
  return useOperationMutation(
    serviceId,
    (id, payload: { command: string[]; timeout_seconds?: number; retries?: number }) => api.requestJob(id, payload),
  );
}

export function useObservabilityOperation(serviceId: string | undefined) {
  return useOperationMutation(
    serviceId,
    (id, payload: { prometheus: boolean; grafana: boolean }) => api.requestObservability(id, payload),
  );
}

export function useDeleteScheduleOperation(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (operationId: string) => api.deleteSchedule(serviceId ?? "", operationId),
    onSuccess: () => {
      if (serviceId) void client.invalidateQueries({ queryKey: keys.operations(serviceId) });
    },
  });
}

// Build logs are deliberately absent from this file. `GET
// /deployments/{id}/build-log` is an SSE stream, not a document with a URL you
// can refetch, so there is nothing for a query cache to hold. `build-logs.tsx`
// subscribes to `api.streamBuildLog` directly. Build logs only — runtime logs
// are Phase 5 (D4) and no view for them exists anywhere in this tree.

/** Canvas drag → PATCH /services/{id}. UI metadata only (D6). */
export function useUpdateServicePosition(environmentId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { serviceId: string; patch: ServiceUpdate }) =>
      api.updateService(args.serviceId, args.patch),
    onSuccess: () => {
      if (environmentId) {
        void client.invalidateQueries({ queryKey: keys.services(environmentId) });
      }
    },
  });
}

/** Rename is service metadata only: it does not enqueue a deployment. */
export function useRenameService(environmentId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { serviceId: string; name: string }) =>
      api.updateService(args.serviceId, { name: args.name }),
    onSuccess: () => {
      if (environmentId) void client.invalidateQueries({ queryKey: keys.services(environmentId) });
    },
  });
}

export function useDeploy(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.createDeployment(serviceId ?? ""),
    onSuccess: (deployment: Deployment) => {
      void client.invalidateQueries({ queryKey: keys.deployments(deployment.service_id) });
      void client.invalidateQueries({ queryKey: keys.instances(deployment.service_id) });
    },
  });
}

export function useRollbackDeployment(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (deploymentId: string) => api.rollbackDeployment(deploymentId),
    onSuccess: (deployment: Deployment) => {
      void client.invalidateQueries({ queryKey: keys.deployments(deployment.service_id) });
      void client.invalidateQueries({ queryKey: keys.instances(deployment.service_id) });
      if (serviceId && serviceId !== deployment.service_id) {
        void client.invalidateQueries({ queryKey: keys.deployments(serviceId) });
        void client.invalidateQueries({ queryKey: keys.instances(serviceId) });
      }
    },
  });
}

export function usePutVariable(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (args: { key: string; value: string }) =>
      api.putVariable(serviceId ?? "", args.key, args.value),
    onSuccess: () => {
      if (serviceId) void client.invalidateQueries({ queryKey: keys.variables(serviceId) });
    },
  });
}

export function useDeleteVariable(serviceId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.deleteVariable(serviceId ?? "", key),
    onSuccess: () => {
      if (serviceId) void client.invalidateQueries({ queryKey: keys.variables(serviceId) });
    },
  });
}
